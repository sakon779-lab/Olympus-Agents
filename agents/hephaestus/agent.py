import sys
import json
import logging
import re
import os
import subprocess
import ast
from typing import Dict, Any, List
import core.network_fix
import asyncio
# ✅ Core Configuration & LLM
from core.config import settings
from core.llm_client import query_qwen

# ✅ Core Tools (Updated)
from core.tools.jira_ops import get_jira_issue  # ใช้ตัวใหม่ที่ return dict
from core.tools.file_ops import read_file, write_file, append_file, list_files, edit_file
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr, git_pull
from core.tools.git_ops import run_git_cmd  # ใช้สำหรับ validation ภายใน

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Hephaestus] %(message)s')
logger = logging.getLogger("Hephaestus")

def sanitize_json_input(raw_text):
    """
    Professional Fix: ทำความสะอาด JSON string ที่ Model อาจจะเขียนผิดมา
    โดยเฉพาะกรณีใช้ Triple Quotes  แทนที่จะใช้ \n
    """
    # 1. ลบ Markdown Code Blocks (```json ... ```) ถ้ามี
    clean_text = re.sub(r'^```json\s*', '', raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r'^```\s*', '', clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r'```$', '', clean_text, flags=re.MULTILINE)

    # 2. แก้ปัญหา Triple Quotes  ที่
    # Logic: หา string ที่อยู่ระหว่าง """ ... """ แล้วแปลง newlines เป็น \n ให้หมด

    def fix_triple_quotes(match):
        content = match.group(1)
        # Escape backslashes first
        content = content.replace('\\', '\\\\')
        # Escape double quotes
        content = content.replace('"', '\\"')
        # Replace newlines with \n
        content = content.replace('\n', '\\n')
        return f'"{content}"'

    # Regex ค้นหา """...""" (แบบ non-greedy)
    clean_text = re.sub(r'"""(.*?)"""', fix_triple_quotes, clean_text, flags=re.DOTALL)

    return clean_text.strip()

# ==============================================================================
# 🛠️ HEPHAESTUS SPECIFIC TOOLS (Sandbox Commanders)
# ==============================================================================

def run_sandbox_command(command: str, timeout: int = 300) -> str:
    """
    Executes a shell command inside the Agent's Workspace.
    Handles venv activation and UTF-8 encoding automatically.
    """
    workspace = settings.AGENT_WORKSPACE

    if not os.path.exists(workspace):
        return f"❌ Error: Workspace not found. Did you run 'git_setup_workspace'?"

    logger.info(f"⚡ Executing in Sandbox: {command}")

    try:
        env = os.environ.copy()
        # เพิ่ม Workspace เข้า PYTHONPATH
        env["PYTHONPATH"] = workspace + os.pathsep + env.get("PYTHONPATH", "")

        # 🔧 Environment Fixes
        env["PYTHONUTF8"] = "1"  # บังคับ UTF-8 (แก้ปัญหา Windows)
        env["PIP_NO_INPUT"] = "1"  # ห้าม pip ถาม

        # =========================================================
        # 🛡️ VENV AUTO-LOADER (The Hero Logic)
        # =========================================================
        venv_path = os.path.join(workspace, ".venv")
        if os.path.exists(venv_path):
            if os.name == 'nt':  # Windows
                venv_scripts = os.path.join(venv_path, "Scripts")
            else:  # Linux/Mac
                venv_scripts = os.path.join(venv_path, "bin")

            if os.path.exists(venv_scripts):
                # ยัดเข้า PATH เป็นลำดับแรก เพื่อให้เรียก python/pip ของ venv ก่อนเสมอ
                env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")
                env["VIRTUAL_ENV"] = venv_path
                # logger.info(f"🔌 Activated venv at: {venv_path}")

        result = subprocess.run(
            command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            input="",
            timeout=timeout
        )

        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode == 0:
            return f"✅ Command Success:\n{output}"
        else:
            return f"❌ Command Failed (Exit Code {result.returncode}):\n{output}\nERROR LOG:\n{error}"

    except subprocess.TimeoutExpired:
        return f"⏰ Command Timeout! (Over {timeout}s). Process killed."

    except Exception as e:
        return f"❌ Execution Error: {e}"


def install_package(package_name: str) -> str:
    """Installs a Python package using the sandbox environment."""
    if any(char in package_name for char in [";", "&", "|", ">"]):
        return "❌ Error: Invalid package name."
    return run_sandbox_command(f"pip install {package_name}")


# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    "get_jira_issue": get_jira_issue,
    "list_files": list_files,
    "read_file": read_file,
    "edit_file": edit_file,
    "git_setup_workspace": git_setup_workspace,
    "git_commit": git_commit,
    "git_push": git_push,
    "git_pull": git_pull,
    "create_pr": create_pr,
    "write_file": write_file,
    "append_file": append_file,
    "run_command": run_sandbox_command,
    "install_package": install_package
}

import sys
from typing import Dict, Any, Tuple

# 1. นิยาม Schema (กฎเหล็ก) ของแต่ละ Tool
TOOL_SCHEMAS = {
    "edit_file": {
        "required": ["target_text", "replacement_text"],
        "file_path": True
    },
    "write_file": {
        "required": ["content"],
        "file_path": True
    },
    "append_file": {
        "required": ["content"],
        "file_path": True
    },
    "read_file": {
        "required": [],
        "file_path": True
    },
    # Tool อื่นๆ ใส่เพิ่มตรงนี้...
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    # 0. เช็คว่ารู้จัก Tool นี้ไหม
    if tool_name not in TOOLS:
        return {"success": False, "output": f"Error: Unknown tool '{tool_name}'"}

    # 🛡️ VALIDATION LAYER: ตรวจสอบ Argument ก่อนรันจริง
    if tool_name in TOOL_SCHEMAS:
        schema = TOOL_SCHEMAS[tool_name]

        # สร้าง Set ของ Key ที่ถูกต้อง
        valid_keys = set(schema["required"])
        if schema.get("file_path"):
            valid_keys.add("file_path")

        received_keys = set(args.keys())
        unknown_keys = received_keys - valid_keys

        # 1. เช็ค Key ผี (เกินมา)
        if unknown_keys:
            error_msg = (
                f"[ERROR] Invalid arguments for '{tool_name}'.\n"
                f"❌ Unknown arguments: {list(unknown_keys)}\n"
                f"✅ Expected arguments: {list(valid_keys)}\n"
                f"👉 Please CORRECT your JSON and try again."
            )
            # ⚠️ ต้อง return Dict เสมอ!
            return {"success": False, "output": error_msg}

        # 2. เช็ค Key ขาด (หายไป)
        missing_keys = [k for k in schema["required"] if k not in args]
        if missing_keys:
            return {"success": False, "output": f"[ERROR] Missing required arguments for '{tool_name}': {missing_keys}"}

        # 3. เช็ค file_path (ถ้าจำเป็น)
        if schema.get("file_path") and "file_path" not in args:
            return {"success": False, "output": f"[ERROR] Missing required arguments for '{tool_name}': ['file_path']"}

    # 🚀 EXECUTION LAYER: รันของจริง
    try:
        func = TOOLS[tool_name]

        # 1. รันฟังก์ชัน
        raw_result = str(func(**args))

        # 2. ตรวจสอบ "เจตนา" ของผลลัพธ์ (Success Detection)
        is_success = "✅" in raw_result or "SUCCESS" in raw_result.upper()

        # 3. 🧹 Cleaning: ลบ Emoji เพื่อความปลอดภัยของ MCP บน Windows
        clean_output = raw_result.replace("✅", "[SUCCESS]").replace("❌", "[ERROR]")

        # 4. ส่งกลับ
        return {
            "success": is_success,
            "output": clean_output
        }

    except Exception as e:
        # ถ้าพังกลางทาง ให้ถือว่า Error
        return {
            "success": False,
            "output": f"Error executing {tool_name}: {str(e)}"
        }

# ==============================================================================
# 🧠 SYSTEM PROMPT (UPDATED)
# ==============================================================================
SYSTEM_PROMPT = """
You are "Hephaestus", the Senior Python Developer of Olympus.
Your goal is to complete Jira tasks with high quality, Verify with Tests (TDD), CONTAINERIZE (Compose), and Submit a PR.

*** 🛑 SUPER STRICT ATOMICITY (ZERO TOLERANCE) ***
- You are PROHIBITED from sending multiple JSON actions in one turn.
- ❌ BAD: `[{"action": "write_file"...}, {"action": "run_command"...}]`
- ✅ GOOD: `{"action": "write_file"...}` (Wait for result) -> `{"action": "run_command"...}`
- If you batch commands, the second command WILL FAIL and you will lose progress.

*** 🛡️ SPECIALIZED CODING RULES ***
1. **PYDANTIC VALIDATORS**: When fixing Pydantic validators (`@validator`, `@field_validator`), DO NOT use `edit_file`. Always use `write_file` to redefine the entire Pydantic model class.

*** 👑 CORE PHILOSOPHY & METHODOLOGY ***
1. **JIRA IS GOD**: The Jira Ticket is the ONLY truth. Ignore legacy code intent; build what Jira asks.
   - 🛑 **DO NOT ASSUME**: Do not use "standard practices" if they conflict with the prompt.
   - 🛑 **LITERAL INTERPRETATION**: If the prompt implies "Start at 0 and add points", DO NOT use subtraction unless explicitly asked.
   - 🛑 **NO OVER-ENGINEERING**: Build EXACTLY what is asked. Do not add extra features or validation rules not specified.
2. **SDD (Spec-Driven)**: You MUST create `docs/specs.md` before writing code. All Logic/Tests derive from this.
3. **TDD (Test-Driven)**: 🔴 RED (Fail) -> 🟢 GREEN (Pass) -> 🔵 REFACTOR. Never commit failing tests.
4. **STRICT ATOMICITY**: One JSON action per turn. Never batch commands.
5. **NO HALLUCINATIONS**: If you didn't call `write_file`, the file wasn't created. Verify everything.

*** 🤖 AGENT BEHAVIOR (NO CHAT MODE) ***
1. **YOU ARE HANDS-ON**: Never say "Please run this command". YOU run it using `run_command`.
2. **NO CONVERSATION**: Do not offer advice, tutorials, or steps for the user. Just DO the work.
3. **SILENT EXECUTION**: If you need to check something, use a Tool. Do not ask the user for permission or confirmation.

*** 📉 JSON SAFETY PROTOCOL (CRITICAL) ***
- **KEEP IT SHORT**: When using `write_file`, do not put extremely long markdown content in a single JSON string if possible.
- **ESCAPE PROPERLY**: Ensure all double quotes (`"`) inside the content are escaped as (`\"`) and newlines as (`\\n`).
- **NO NESTED JSON BLOCKS**: When writing Markdown that contains JSON examples, DO NOT use triple backticks + json syntax inside the `write_file` content string. It breaks the parser.
  - ❌ BAD: "... ```json {\\\"key\\\": \\\"val\\\"} ``` ..."
  - ✅ GOOD: "... Input: { key: val } ..." (Use simplified text representation instead)
- **RETRY STRATEGY**: If writing `docs/specs.md` fails, try writing a simpler version without complex formatting.

*** 🧹 CODE ARCHITECTURE RULE ***
1. **SEPARATION OF CONCERNS**:
   - `src/` must ONLY contain Application Logic (FastAPI, Classes, Utils).
   - `tests/` must ONLY contain Test Logic (pytest functions, TestClient).
   - 🚫 **NEVER** put `test_...` functions or `TestClient` inside `src/`.
2. **IMPORT SAFETY**:
   - Before using a class (e.g., `TestClient`), make sure you imported it (`from fastapi.testclient import TestClient`).
3. **EXECUTION ORDER**:
   - Always define variables (e.g., `app = FastAPI()`) BEFORE using them.

*** 🔄 WORKFLOW (STRICT ORDER) ***
1. **PHASE 1: INIT**: `git_setup_workspace(issue_key)`. Memorize the branch.
2. **PHASE 2: SPEC**: `get_jira_issue`. Write `docs/specs.md` (Mandatory).
   - *Constraint*: Specs MUST include API Endpoint, JSON Schema (Req/Res), and Business Logic.
3. **PHASE 3: EXPLORE**: `read_file` legacy `src/` and `tests/`.
4. **PHASE 4: TDD CYCLE**: 
   - `read_file("docs/specs.md")` to refresh context.
   - Write failing test in `tests/`. Run `pytest` (Expect Fail).
   - Write/Update code in `src/`. Run `pytest` (Expect Pass).
5. **PHASE 5: CONTAINERIZE**: 
   - `Dockerfile` (Python 3.10-slim, Port from Jira).
   - `docker-compose.yml` (Service `api` & `mockserver`).
6. **PHASE 6: DELIVERY**: 
   - Final `pytest`. 
   - `git_commit` -> `git_push` (Handle conflicts if rejected).
   - `create_pr` (Handle existing PRs gracefully). -> `task_complete`.

*** 🛡️ FILE EDITING & OPERATIONS PROTOCOL ***
**A. TOOL SELECTION STRATEGY**
1. **NEW Feature / New File** 👉 Use `write_file`.
2. **ADD to END of file** (New endpoints/classes) 👉 Use `append_file` (Safest).
3. **MODIFY Existing Logic** 👉 Use `edit_file`.
4. **SMALL FILES (<100 lines)** 👉 Use `write_file` to rewrite the ENTIRE file (Prevents "layered" code & import errors).
5. *** 🛠️ TOOL USAGE RULES (CRITICAL) ***
   - **edit_file**:
     - ❌ WRONG: `{"content": "..."}`
     - ✅ RIGHT: `{"target_text": "...", "replacement_text": "..."}`
     - Note: `target_text` must be EXACTLY what is currently in the file.
   - **edit_file vs write_file**: 
     - If you need to fix IndentationErrors or complex nested blocks, DO NOT use `edit_file`.
     - Use `write_file` to rewrite the whole file immediately. It is cheaper than failing 3 times.

**B. EDITING RULES (Smart Editing)**
- **Safety**: `read_file` before `edit_file`. Target text MUST exist exactly.
- **Indentation**: Target a SINGLE unique line (Anchor) and replace with "Anchor + New Block".
- **Escalation**: If `edit_file` fails twice, STOP. Use `write_file` to rewrite the whole file.

**C. ROBUST EDITING STRATEGY (CRITICAL)**
- **PREFER OVERWRITE**: When fixing bugs or failing tests, DO NOT use `edit_file`.
  - ❌ Risky: Trying to match exact whitespace with `edit_file`.
  - ✅ Safe: Use `write_file` to provide the FULL corrected file content.
- **SIZE LIMIT**: If modifying > 5 lines of code, ALWAYS use `write_file`.
- **SINGLE LINE ONLY**: `edit_file` is ONLY for small, single-line fixes.

**D. FORMATTING (The "Last Code Block" Rule)**
- You MUST wrap code in **TRIPLE BACKTICKS** (```python ... ```).
- **For `write_file` / `append_file`**: JSON arg `"content": "LAST_CODE_BLOCK"`.
- **For `edit_file`**: JSON arg `"replacement_text": "LAST_CODE_BLOCK"`.
- `target_text` must be the EXACT code string to remove. NEVER use "LAST_CODE_BLOCK" in `target_text`.

*** 🕵️ TROUBLESHOOTING & SELF-CORRECTION ***
**1. IMPORT RULE**: If you use `re`, `json`, `os`, `BaseModel`, you MUST verify imports exist at the top. `edit_file` often misses this.
**2. JSON POST RULE**: In FastAPI, ALWAYS use Pydantic `BaseModel` for JSON bodies. Never use raw dicts.
**3. LOOP DETECTION**: If a test fails with the same error after an edit, DO NOT repeat the same action.
   - Check: Did I miss an import? (`NameError`)
   - Check: Is my Pydantic schema correct? (`422 Unprocessable Entity`)
   - Check: Did `edit_file` actually apply? (Read the file again).
**4. TEST MATH**: If code matches spec but test fails, check if the *test expectation* is wrong based on scoring rules.
**5. GIT CONFLICTS**: If `git_pull` fails, `read_file` to find `<<<<<<<`. Manually merge with `write_file`. NEVER commit markers.
**6. DEBUGGING PROTOCOL**: 
   - 🛑 STOP AND READ: If `pytest` fails, DO NOT randomly change numbers/logic immediately.
   - 🔍 ANALYZE: Use `run_command` to check the EXACT error message or assertion failure.
   - 💡 FIX: Only apply a fix when you understand WHY it failed.

*** 💻 TECHNICAL CONSTRAINTS ***
1. **JSON SYNTAX**: No triple quotes (`\"\"\"`) inside JSON values. Use `\\n`.
2. **PR HANDLING**: If "PR already exists", assume success. Do NOT use placeholders (`<token>`).
3. **WINDOWS SHELL (CRITICAL)**: 
   - 🚫 **NEVER use Single Quotes (`'`)** for arguments in `run_command`. Windows CMD does not support them.
   - ✅ **ALWAYS use Double Quotes (`"`)** for strings with spaces.
   - ❌ WRONG: `git commit -m 'My Message'`
   - ✅ RIGHT: `git commit -m "My Message"`

RESPONSE FORMAT (JSON ONLY):
{ "action": "tool_name", "args": { ... } }
"""


# ==============================================================================
# 🧩 HELPER: PARSERS
# ==============================================================================
def extract_code_block(text: str) -> str:
    matches = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if not matches: return ""
    return max(matches, key=len).strip()


def _extract_all_jsons(text: str) -> List[Dict[str, Any]]:
    results = []
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text):
        try:
            search = re.search(r"\{", text[pos:])
            if not search: break
            start_index = pos + search.start()
            obj, end_index = decoder.raw_decode(text, idx=start_index)
            if isinstance(obj, dict) and "action" in obj:
                results.append(obj)
            pos = end_index
        except:
            pos += 1

    # Fallback: ลองใช้ ast.literal_eval เผื่อ AI ตอบเป็น Python Dict string
    if not results:
        try:
            matches = re.findall(r"(\{.*?\})", text, re.DOTALL)
            for match in matches:
                try:
                    # Clean up common JSON vs Python issues
                    clean = match.replace("true", "True").replace("false", "False").replace("null", "None")
                    obj = ast.literal_eval(clean)
                    if isinstance(obj, dict) and "action" in obj: results.append(obj)
                except:
                    continue
        except:
            pass

    return results


# ==============================================================================
# 🚀 MAIN LOOP
# ==============================================================================
def run_hephaestus_task(task: str, max_steps: int = 45):
    if settings.CURRENT_AGENT_NAME != "Hephaestus":
        settings.CURRENT_AGENT_NAME = "Hephaestus"

    print(f"🔨 Launching Hephaestus (The Builder)...")
    print(f"📋 Task: {task}")

    history = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task}
    ]

    last_code_block = None
    persistent_code_block = None  # ต้องอยู่เหนือ while step_count < max_steps:

    for step in range(max_steps):
        print(f"\n🔄 Thinking (Step {step + 1})...")
        try:
            response = query_qwen(history)
            if isinstance(response, dict):
                content = response.get('message', {}).get('content', '') or response.get('content', '')
            else:
                content = str(response)
        except Exception as e:
            print(f"❌ Error querying LLM: {e}")
            return

        print(f"🤖 Hephaestus: {content[:100]}...")

        # =========================================================
        # 🟢 [แทรกตรงนี้ 1] ดึง Code Block ล่าสุดเตรียมไว้
        # =========================================================
        # ดึง Code Block ทั้งหมด
        all_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", content, re.DOTALL)

        # วนลูปหา Block สุดท้าย ที่ "ไม่ใช่" JSON Action ของเรา
        found_new_code = False  # รีเซ็ตธงทุกรอบ
        for block in reversed(all_blocks):
            if '"action":' in block: continue
            persistent_code_block = block  # จำลงความจำถาวร
            found_new_code = True  # ปักธงว่ารอบนี้มีของใหม่
            print(f"📦 Captured NEW code block ({len(block)} chars)")
            break
        # =========================================================

        if found_new_code:
            print(f"✨ NEW memory captured: {len(persistent_code_block)} characters.")
        else:
            if persistent_code_block:
                print("♻️  No new code found, using existing memory.")
            else:
                print("⚠️  No code in memory yet.")

        # ✅ [แก้ตรงนี้] เรียกใช้ฟังก์ชันล้างข้อมูลก่อนส่งไปแกะ JSON
        content = sanitize_json_input(content)

        tool_calls = _extract_all_jsons(content)

        # =========================================================
        # 🚑 SMART RECOVERY (ซ่อม JSON อัตโนมัติ)
        # =========================================================
        # ถ้า JSON พัง แต่เราเห็นความตั้งใจ (Action + File Path + Code Block)
        if not tool_calls and ('"action":' in content or "```json" in content):
            print("🚨 DETECTED MALFORMED JSON. Attempting Smart Recovery...")

            # 1. พยายามแกะ Action และ File Path ด้วย Regex (ไม่ง้อ JSON Parser)
            # หาคำว่า "action": "write_file" (รองรับช่องว่าง)
            action_match = re.search(r'"action"\s*:\s*"(\w+)"', content)
            # หาคำว่า "file_path": "..." (รองรับช่องว่าง)
            path_match = re.search(r'"file_path"\s*:\s*"([^"]+)"', content)

            recovered = False

            # 2. ถ้าข้อมูลครบองค์ประชุม (Action + Path + Markdown Block) -> ลุยเลย!
            if action_match and path_match and last_code_block:
                found_action = action_match.group(1)
                found_path = path_match.group(1)

                # รองรับเฉพาะ write/append (edit_file เสี่ยงไปถ้าแกะ target ไม่ได้)
                if found_action in ["write_file", "append_file"]:
                    print(f"🔧 Auto-Recovered: Executing {found_action} on {found_path} using Last Code Block.")

                    # สร้าง Tool Call เทียมขึ้นมา
                    tool_calls = [{
                        "action": found_action,
                        "args": {
                            "file_path": found_path,
                            "content": last_code_block  # ยัด Code Block ใส่ปากเลย
                        }
                    }]
                    recovered = True

            # 3. ถ้าซ่อมไม่ได้จริงๆ (เช่น เป็น edit_file หรือหา path ไม่เจอ) -> ค่อยด่าตามเดิม
            if not recovered:
                print("❌ Recovery Failed. Sending Error Message.")
                history.append({"role": "assistant", "content": content})

                error_msg = (
                    "❌ SYSTEM ERROR: JSON Validation Failed!\n"
                    "🛑 STOP putting large text in JSON fields.\n"
                    "👉 FIX: Write code in a Markdown block first, then send JSON with 'content': 'LAST_CODE_BLOCK'."
                )

                history.append({
                    "role": "user",
                    "content": error_msg
                })
                continue

        # 🟢 [FIX] เพิ่ม Logic กรองคำสั่งซ้ำ (Deduplicate)
        # แก้ปัญหา AI พูดติดอ่าง (Output JSON เดิมซ้ำ 2 รอบ)
        unique_tools = []
        seen_tools = set()
        for tool in tool_calls:
            # แปลง Dict เป็น String เพื่อใช้เช็คใน Set
            tool_str = json.dumps(tool, sort_keys=True)
            if tool_str not in seen_tools:
                seen_tools.add(tool_str)
                unique_tools.append(tool)

        tool_calls = unique_tools

        step_outputs = []
        task_finished = False

        for tool_call in tool_calls:
            action = tool_call.get("action")
            args = tool_call.get("args", {})

            # ---------------------------------------------------------
            # 🛡️ TASK COMPLETION CHECK (Safety Gate) - FULL VERSION
            # ---------------------------------------------------------
            if action == "task_complete":
                # รับค่า mode (Default = code)
                task_mode = args.get("mode", "code").lower()
                validation_error = None
                workspace = settings.AGENT_WORKSPACE

                # 1. Check Uncommitted Changes
                status = run_git_cmd("git status --porcelain", cwd=workspace)
                if status.strip():
                    validation_error = "❌ REJECTED: You have uncommitted changes. Please commit or discard them before finishing."

                # 2. Verify Work (Mode Based)
                if not validation_error:
                    current_branch = run_git_cmd("git branch --show-current", cwd=workspace)
                    is_main = current_branch in ["main", "master"]

                    # เตรียมตัวแปร
                    source_files = []
                    config_files = []
                    test_files = []
                    has_changes = False

                    if not is_main:
                        diff_output = run_git_cmd(f"git diff --name-only main...{current_branch}", cwd=workspace)
                        changed_files = diff_output.strip().splitlines()

                        if changed_files:
                            has_changes = True
                            for f in changed_files:
                                f = f.strip()
                                if not f: continue
                                # แยกประเภทไฟล์
                                if f.startswith("src/") or f.startswith("app/") or (
                                        f.endswith(".py") and "test" not in f):
                                    source_files.append(f)
                                elif f.startswith("tests/") or "test" in f:
                                    test_files.append(f)
                                else:
                                    config_files.append(f)
                    else:
                        has_changes = False

                    # === CASE A: Code Mode ===
                    if task_mode == "code":
                        if not has_changes:
                            validation_error = (
                                "❌ REJECTED: No file changes detected compared to main branch.\n"
                                "If you made changes, did you forget to 'git push'?\n"
                                "If this is just analysis, please use mode='analysis'."
                            )
                        # เช็คว่าแก้แต่ Config หรือเปล่า
                        elif not source_files and (config_files or test_files):
                            validation_error = (
                                "❌ REJECTED: No SOURCE CODE changes detected!\n"
                                f"   - Config/Docs changed: {config_files}\n"
                                f"   - Tests changed: {test_files}\n"
                                "⚠️ But NO changes in 'src/' or logic files found.\n"
                                "Feature implementation MUST include source code changes."
                            )

                        # เช็ค PR
                        elif not is_main and not validation_error:
                            pr_check = run_git_cmd(f"gh pr list --head {current_branch}", cwd=workspace)
                            if "no open pull requests" in pr_check or not pr_check.strip():
                                validation_error = "❌ REJECTED: Code committed but NO Pull Request (PR) found. Please create a PR first."

                    # === CASE B: Analysis Mode ===
                    elif task_mode == "analysis":
                        if has_changes:
                            print(
                                f"⚠️ WARNING: Task completed in 'analysis' mode, but file changes were detected on {current_branch}.")

                # ---------------------------------------------------------
                # 🚦 Decide
                # ---------------------------------------------------------
                if validation_error:
                    print(f"🚫 {validation_error}")
                    step_outputs.append(validation_error)
                    break
                else:
                    task_finished = True
                    result_for_ai = args.get("summary", "Done")
                    step_outputs.append(f"Task Completed: {result_for_ai}")
                    break

            if action not in TOOLS:
                step_outputs.append(f"❌ Error: Tool '{action}' not found.")
                continue

            # 🛠️ LONG-TERM FIX: ตรวจสอบก่อนรันจริง
            if "LAST_CODE_BLOCK" in str(args):
                # ถ้าไม่มี Code Block ในรอบนี้ และไม่มีของเก่าค้างใน Memory
                if not persistent_code_block:
                    print("🛡️ INTERCEPTED: Agent forgot code block. Rejecting action.", file=sys.stderr)

                    # สร้าง Error Message แบบสอนงานทันที
                    rejection_msg = (
                        "🛑 PRE-EXECUTION ERROR: You used 'LAST_CODE_BLOCK' but you forgot to write the Markdown code block!\n"
                        "RULE: You MUST write the code block (```python ... ```) in the SAME message as the JSON.\n"
                        "👉 Please rewrite the code block NOW, then send the JSON again."
                    )

                    # ยัดใส่ History ให้มันรู้ตัว แล้วข้ามไปรอบถัดไปเลย (ไม่กิน Step ฟรี)
                    history.append({"role": "assistant", "content": content})
                    history.append({"role": "user", "content": rejection_msg})
                    continue  # 🔄 วนกลับไปเริ่ม Loop ใหม่ทันที

            # =========================================================
            # 🟢 [แก้ตรงนี้ 2] แทนที่ Logic เดิมด้วยอันนี้
            # =========================================================
            if action == "edit_file":
                # ให้ AI ส่ง replacement="LAST_CODE_BLOCK" ได้เหมือนกัน
                if args.get("replacement_text") == "LAST_CODE_BLOCK":
                    if last_code_block:
                        args["replacement_text"] = last_code_block
                        print(f"✏️ Auto-attached replacement text from Markdown block.")
                    else:
                        print("⚠️ Warning: edit_file called but no code block found.")

                # =========================================================
                # 🛡️ 2. เพิ่ม MARKDOWN STRIPPER ให้ edit_file ด้วย! (สำคัญมาก)
                # =========================================================
                current_replacement = args.get("replacement_text", "")
                if "```" in current_replacement:
                    # ลบบรรทัดแรกที่เป็น ```python
                    current_replacement = re.sub(r"^```[a-zA-Z0-9]*\n", "", current_replacement)
                    # ลบบรรทัดสุดท้ายที่เป็น ```
                    current_replacement = re.sub(r"\n```$", "", current_replacement)
                    args["replacement_text"] = current_replacement.strip()
                    # print("🧹 Auto-cleaned Markdown from edit_file replacement text.")
            elif action in ["write_file", "append_file"]:
                # เงื่อนไข: ถ้า AI สั่งให้ใช้ Block ล่าสุด หรือส่งมาสั้นผิดปกติ
                current_content = args.get("content", "")
                if not current_content or len(current_content) < 10 or current_content == "LAST_CODE_BLOCK":

                    # ✅ เปลี่ยนจาก last_code_block เป็น persistent_code_block
                    if persistent_code_block:
                        args["content"] = persistent_code_block

                        # แสดง Log ให้เราเห็นว่าดึงมาจากรอบไหน
                        origin = "Current Step" if found_new_code else "Previous Step"
                        print(f"📝 Auto-attached content from {origin} to {args.get('file_path')}")

                    else:
                        # ❌ กรณีที่หา Code Block ไม่เจอ
                        print("🚫 ERROR: No Markdown block found in memory.", file=sys.stderr)

                        # --- 🛡️ ANTI-LOOP LOGIC (เพิ่มส่วนนี้) ---
                        # เช็คว่า Error นี้เพิ่งเกิดขึ้นในรอบที่แล้วหรือเปล่า?
                        if len(history) >= 2 and "SYNTAX ERROR" in history[-1]["content"]:
                            # ถ้าซ้ำ 2 รอบติด ให้ด่าแรงขึ้นและบังคับหยุด
                            critical_error_msg = (
                                "🛑 SYSTEM HALT: You are stuck in a loop!\n"
                                "You keep trying to use 'LAST_CODE_BLOCK' without writing the code first.\n"
                                "RULE: You MUST write the Python code in a Markdown block (```python ... ```) in your message BEFORE sending the JSON."
                            )
                            step_outputs.append(critical_error_msg)
                            history.append({"role": "user", "content": critical_error_msg})

                            # (Option) ถ้าอยากให้หยุดโปรแกรมเลยเมื่อ Loop เกิน 3 รอบ
                            # raise Exception("AI Stuck in Infinite Loop")
                        else:
                            # Error รอบแรก (แจ้งเตือนปกติ)
                            error_msg = (
                                "❌ SYNTAX ERROR: I cannot find any code block to write!\n"
                                "⚠️ You used 'LAST_CODE_BLOCK', but no Markdown code block was found in your current or previous responses.\n"
                                "👉 STOP APOLOGIZING. JUST WRITE THE CODE BLOCK NOW."
                            )
                            step_outputs.append(error_msg)
                            history.append({"role": "assistant", "content": content})
                            history.append({"role": "user", "content": error_msg})

                        continue

                # =========================================================
                # 🛡️ 2. MARKDOWN STRIPPER (เพิ่มใหม่ตรงนี้!)
                # =========================================================
                # ถ้าเนื้อหามี ``` ครอบอยู่ ให้แกะออก
                if "```" in current_content:
                    # ลบบรรทัดแรกที่เป็น ```yaml, ```python, etc.
                    current_content = re.sub(r"^```[a-zA-Z0-9]*\n", "", current_content)
                    # ลบบรรทัดสุดท้ายที่เป็น ```
                    current_content = re.sub(r"\n```$", "", current_content)
                    # อัปเดตกลับเข้าไปใน args
                    args["content"] = current_content.strip()  # strip() เพื่อลบช่องว่างหัวท้าย
                    # print("🧹 Auto-cleaned Markdown artifacts from file content.")
            # =========================================================

            # =========================================================
            # 🛡️ 1. FILENAME GUARDRAIL (ดักชื่อไฟล์ผิด) <-- เพิ่มตรงนี้
            # =========================================================
            if action in ["write_file", "edit_file", "append_file"]:
                target_file = args.get("file_path", "").replace("\\", "/")  # Normalize path

                # กฎ: ถ้าเขียนลง docs/ ต้องชื่อ specs.md เท่านั้น
                if target_file.startswith("docs/") and target_file != "docs/specs.md":
                    print(f"🚫 BLOCKED: Wrong spec filename '{target_file}'")
                    error_msg = (
                        f"❌ FILENAME ERROR: You are trying to write to '{target_file}'.\n"
                        f"⚠️ STANDARD VIOLATION: The spec file MUST be named exactly 'docs/specs.md'.\n"
                        f"👉 ACTION: Rename the file path to 'docs/specs.md' and try again."
                    )
                    step_outputs.append(error_msg)
                    history.append({"role": "assistant", "content": content})
                    history.append({"role": "user", "content": error_msg})
                    continue  # 🛑 หยุดทันที

            # =========================================================
            # 2️⃣ SPEC GUARDRAIL (อันใหม่ - เพิ่มต่อท้ายตรงนี้!)
            # =========================================================
            if action in ["write_file", "edit_file", "append_file"]:
                target_file = args.get("file_path", "")

                # เช็คว่าไฟล์ที่จะเขียนคือ Source Code หรือ Test หรือไม่
                if target_file.startswith("src/") or target_file.startswith("tests/"):

                    # เช็คว่ามีไฟล์ Spec หรือยัง?
                    spec_path = os.path.join(settings.AGENT_WORKSPACE, "docs/specs.md")
                    if not os.path.exists(spec_path):
                        # 🚫 ถ้ายังไม่มี Spec -> บล็อกทันที!
                        print(f"🚫 BLOCKED: Attempt to modify code without specs.md")
                        error_msg = (
                            "❌ SYSTEM POLICY VIOLATION: You CANNOT modify 'src/' or 'tests/' yet.\n"
                            "⚠️ REASON: The file 'docs/specs.md' does not exist on disk.\n"
                            "👉 ACTION REQUIRED: You MUST write the 'docs/specs.md' file first to define the requirements.\n"
                            "Please execute write_file('docs/specs.md', content) now."
                        )

                        # บันทึก Error ลง History เพื่อให้ AI รู้ตัว
                        step_outputs.append(error_msg)
                        history.append({"role": "assistant", "content": content})
                        history.append({"role": "user", "content": error_msg})
                        continue  # 🚀 ข้ามการทำงานรอบนี้ไปเลย (ไม่รัน execute_tool_dynamic)

            # =========================================================

            # =========================================================
            # 🛡️ 3️⃣ SAFETY LOCK (ป้องกันการเขียนทับไฟล์มั่วซั่ว) <-- เพิ่มตรงนี้
            # =========================================================
            if action == "write_file":
                target_path = args.get("file_path", "")
                full_path = os.path.join(settings.AGENT_WORKSPACE, target_path)  # ต้องใช้ path เต็มเพื่อเช็คไฟล์จริง

                # เงื่อนไข: ถ้าไฟล์มีอยู่แล้ว และเป็นไฟล์ Python (.py) (ไม่นับพวก config/md)
                if os.path.exists(full_path) and target_path.endswith(".py"):
                    try:
                        # อ่านไฟล์เดิมมาเช็คความยาว
                        with open(full_path, 'r', encoding='utf-8') as f:
                            old_content = f.read()

                        new_content = args.get("content", "")

                        # 🚨 กฎเหล็ก: ถ้าของใหม่สั้นกว่าของเก่าเกิน 50% แสดงว่า AI กำลังจะลบโค้ดทิ้ง!
                        if len(new_content) < len(old_content) * 0.5:
                            print(f"🚫 BLOCKED: Prevented accidental overwrite of {target_path}")
                            error_msg = (
                                f"🚫 SAFETY BLOCK: You are trying to overwrite '{target_path}' with content significantly shorter than the original.\n"
                                f"⚠️ DANGER: Using `write_file` will DELETE the existing code! (Old: {len(old_content)} chars -> New: {len(new_content)} chars)\n"
                                f"👉 ACTION: \n"
                                f"   1. Use `append_file` to add new endpoints/classes at the bottom.\n"
                                f"   2. Use `edit_file` to modify specific parts.\n"
                                f"   3. If you really mean to rewrite, verify the content matches the full file logic."
                            )

                            # บันทึก Error และเด้งกลับ
                            step_outputs.append(error_msg)
                            history.append({"role": "assistant", "content": content})
                            history.append({"role": "user", "content": error_msg})
                            continue  # 🛑 หยุดทันที รักษาชีวิตโค้ดเก่าไว้
                    except Exception as e:
                        print(f"⚠️ Safety check warning: {e}")

            # =========================================================

            print(f"🔧 Executing: {action}")
            # 1. รันเครื่องมือตามปกติ
            res_data = execute_tool_dynamic(action, args)
            result_for_ai = res_data["output"]

            # 2. ตรวจสอบผลลัพธ์: ถ้าเป็นการ "แก้ไขไฟล์" และ "สำเร็จ"
            file_tools = ["write_file", "append_file", "edit_file"]
            if action in file_tools and res_data["success"]:
                persistent_code_block = None
                # ใช้ sys.stderr เพื่อให้ Log ไปโผล่ใน Claude Desktop โดยไม่ทำให้ระบบพัง
                print(f"DEBUG: Memory flushed for {action}", file=sys.stderr)

            # =========================================================
            # 🟢 [NEW] BATCHING DETECTOR (แจ้งเตือน AI ถ้ามันเผลอรัวคำสั่ง)
            # =========================================================
            if len(tool_calls) > 1:
                print(f"⚠️ Warning: Agent tried to batch {len(tool_calls)} tools. Executing only the first one.")
                result_for_ai += (
                    f"\n\n🚨 SYSTEM ALERT: You violated the 'No Batching' rule! "
                    f"You sent {len(tool_calls)} actions at once. "
                    f"I executed ONLY the first one ('{action}'). "
                    f"The other {len(tool_calls) - 1} actions were IGNORED. "
                    f"Wait for this result before sending the next command."
                )

            # Show brief result
            display = f"✅ File operation success: {args.get('file_path')}" if "success" in str(
                result_for_ai).lower() and action.startswith("write") else result_for_ai
            print(f"📄 Result: {display[:300]}..." if len(display) > 300 else f"📄 Result: {display}")

            step_outputs.append(f"Tool Output ({action}): {result_for_ai}")
            break  # Atomic execution

        if task_finished:
            print(f"\n✅ BUILD COMPLETE: {result_for_ai}")
            return result_for_ai

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")


if __name__ == "__main__":
    # Support command line args for testing
    if len(sys.argv) > 1:
        run_hephaestus_task(sys.argv[1])
    else:
        run_hephaestus_task("Fix bug on SCRUM-29")
import sys
import json
import logging
import re
import os
import subprocess
import ast
import time
from datetime import datetime
import uuid
from typing import Dict, Any, List, Tuple
try:
    import core.network_fix
except ImportError:
    pass

# ✅ Core Configuration & LLM
from core.config import settings
from core.llm_client import query_qwen

# ✅ Core Tools
from core.tools.jira_ops import get_jira_issue
from core.tools.file_ops import read_file, write_file, append_file, list_files, edit_file
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr, git_pull
from core.tools.git_ops import run_git_cmd

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Hephaestus] %(message)s')
logger = logging.getLogger("Hephaestus")

# ==============================================================================
# 📝 DUAL LOGGER CLASS (New Feature!)
# ==============================================================================
class DualLogger:
    """
    Writes output to BOTH the terminal (stdout) and a log file simultaneously.
    """
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log_file = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
        self.log_file.flush()  # Ensure real-time saving

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        self.log_file.close()

# ==============================================================================
# 🧠 SYSTEM PROMPT (FULL ORIGINAL + MD FIX + MIDDLEWARE PROTOCOL)
# ==============================================================================
MD_QUOTE = "```"

SYSTEM_PROMPT = f"""
You are "Hephaestus", the Senior Python Developer of Olympus.
Your goal is to complete Jira tasks with high quality, Verify with Tests (TDD), CONTAINERIZE (Compose), and Submit a PR.

*** 🛡️ SAFE CONTENT WRITING PROTOCOL (CRITICAL) ***
Writing complex code or documentation inside a JSON string is dangerous (escaping issues).
You MUST use the **"Reference Pattern"** instead:

✅ **STEP 1: Write the Content**
Write the full file content inside a standard Markdown code block ({MD_QUOTE}python, {MD_QUOTE}markdown, etc.).

✅ **STEP 2: Call the Tool**
Immediately after the code block, provide the JSON action.
In the `content` or `replacement_text` argument, use the EXACT placeholder string: `"LAST_CODE_BLOCK"`.

**EXAMPLE:**
User: "Create main.py"
Agent:
Here is the code:
{MD_QUOTE}python
def main():
    print("Hello World")
{MD_QUOTE}
{{ "action": "write_file", "args": {{ "file_path": "src/main.py", "content": "LAST_CODE_BLOCK" }} }}

⚠️ RULES:
The middleware will automatically replace "LAST_CODE_BLOCK" with the content of the code block you just wrote.
DO NOT try to escape the code yourself inside JSON. Let the system handle it.
This applies to write_file, append_file, and edit_file.

*** 🛑 SUPER STRICT ATOMICITY (ZERO TOLERANCE) ***
- You are PROHIBITED from sending multiple JSON actions in one turn.
- ❌ BAD: `[{{ "action": "write_file"... }}, {{ "action": "run_command"... }}]`
- ✅ GOOD: `[{{ "action": "write_file"... }}]` (Wait for result) -> `[{{ "action": "run_command"... }}]`
- If you batch commands, the second command WILL FAIL and you will lose progress.

*** 🛡️ SPECIALIZED CODING RULES ***
1. **PYDANTIC VALIDATORS**: When fixing Pydantic validators (`@validator`, `@field_validator`), DO NOT use `edit_file`. Always use `write_file` to redefine the entire Pydantic model class.
2. **DOCKER RULES**: 
   - ALWAYS use `docker-compose up -d --build` to restart services. 
   - This ensures the old container is replaced by the new version and prevents port conflicts.
   - NEVER run `docker-compose up` without `-d`.
3. **PYTHON VERSION (CRITICAL)**: 
   - ALWAYS use `python:3.11-slim` as the base image in your `Dockerfile`. 
   - DO NOT use 3.10 or other versions because modern libraries in this project (like Numpy 2.x) require Python 3.11+.

*** 🛡️ DATA TRANSMISSION PROTOCOL (THE "REFERENCE PATTERN") ***
⚠️ CRITICAL RULE: ONE FILE PER TURN
- You MUST NOT write multiple code blocks for different files in a single response.
- The middleware ONLY captures the VERY LAST code block.
- ❌ BAD:
  {MD_QUOTE}python (code for main.py){MD_QUOTE}
  {MD_QUOTE}python (code for test.py){MD_QUOTE}
  {{ "action": "write_file", "args": {{ "file_path": "src/main.py"... }} }}
  (System will write TEST code into MAIN file -> DISASTER!)

- ✅ GOOD:
  {MD_QUOTE}python (code for main.py){MD_QUOTE}
  {{ "action": "write_file", "args": {{ "file_path": "src/main.py"... }} }}
  (Wait for next turn to write test.py)

*** 👑 CORE PHILOSOPHY & METHODOLOGY ***
1. **JIRA IS GOD**: The Jira Ticket is the ONLY truth for *new requirements*.
2. **🛡️ DO NOT DELETE LEGACY CODE (CRITICAL)**: 
   - You are working on an *existing* codebase. 
   - **NEVER** overwrite/delete existing functions, classes, or endpoints unless explicitly asked to refactor/delete them.
   - **MERGE STRATEGY**: When adding a new feature to `main.py`, you MUST:
     1. `read_file("src/main.py")` to see existing code.
     2. Keep all existing imports and endpoints (e.g., `/hello`, `/reverse`).
     3. Add your NEW code *below* the existing code.
     4. Use `write_file` with the *COMBINED* content (Old + New).

3. **SDD (Spec-Driven)**: You MUST create `docs/specs.md` first.
4. **TDD (Test-Driven)**: 🔴 Write failing test -> 🟢 Write code -> 🔵 Refactor.
5. **STRICT ATOMICITY**: One JSON action per turn. Never batch commands.
6. **NO HALLUCINATIONS**: If you didn't call `write_file`, the file wasn't created. Verify everything.
7. **LOGICAL CONFLICT RESOLUTION (CRITICAL)**:
   - If a test fails more than 2 times despite your code changes, STOP editing the source code.
   - **THINK**: "Is the test case itself logically sound?"
   - **ACTION**: Open the test file, read the inputs (e.g., "Medium1"), and compare them with the expected outputs (e.g., "Add an uppercase letter").
   - If the input already satisfies the rule (e.g., 'M' is an uppercase), you MUST fix the TEST file instead of the source code.

*** 🤖 AGENT BEHAVIOR (NO CHAT MODE) ***
1. **YOU ARE HANDS-ON**: Never say "Please run this command". YOU run it using `run_command`.
2. **NO CONVERSATION**: Do not offer advice, tutorials, or steps for the user. Just DO the work.
3. **SILENT EXECUTION**: If you need to check something, use a Tool. Do not ask the user for permission or confirmation.

*** 📉 JSON SAFETY PROTOCOL (CRITICAL) ***
- **KEEP IT SHORT**: When using `write_file`, do not put extremely long markdown content in a single JSON string if possible.
- **ESCAPE PROPERLY**: Ensure all double quotes (`"`) inside the content are escaped as (`\"`) and newlines as (`\\n`).
- **NO NESTED JSON BLOCKS**: When writing Markdown that contains JSON examples, DO NOT use triple backticks + json syntax inside the `write_file` content string. It breaks the parser.
  - ❌ BAD: "... {MD_QUOTE}json {{\\"key\\": \\"val\\"}} {MD_QUOTE} ..."
  - ✅ GOOD: "... Input: {{ key: val }} ..." (Use simplified text representation instead)
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
     - ❌ WRONG: `{{"content": "..."}}`
     - ✅ RIGHT: `{{"target_text": "...", "replacement_text": "..."}}`
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
- You MUST wrap code in **TRIPLE BACKTICKS** ({MD_QUOTE}python ... {MD_QUOTE}).
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

*** 🐳 DOCKER RULES ***
- ALWAYS use detached mode for services: `docker-compose up -d`.
- NEVER run blocking commands like `uvicorn` or `python main.py` directly without `&` or background mode. The system waits for exit codes.

*** 💻 TECHNICAL CONSTRAINTS ***
1. **JSON SYNTAX**: No triple quotes (`\"\"\"`) inside JSON values. Use `\\n`.
2. **PR HANDLING**: If "PR already exists", assume success. Do NOT use placeholders (`<token>`).
3. **WINDOWS SHELL (CRITICAL)**: 
   - 🚫 **NEVER use Single Quotes (`'`)** for arguments in `run_command`. Windows CMD does not support them.
   - ✅ **ALWAYS use Double Quotes (`"`)** for strings with spaces.
   - ❌ WRONG: `git commit -m 'My Message'`
   - ✅ RIGHT: `git commit -m "My Message"`

RESPONSE FORMAT (JSON ONLY):
{{ "action": "tool_name", "args": {{ ... }} }}
"""


# ==============================================================================
# 🛠️ SANDBOX TOOLS
# ==============================================================================
# แก้ไขบรรทัดนี้: เพิ่ม cwd: str = None เข้าไป
def run_sandbox_command(command: str, cwd: str = None, timeout: int = 300) -> str:
    workspace = settings.AGENT_WORKSPACE

    # ถ้ามีการส่ง cwd มาให้ใช้ค่าที่ส่งมา ถ้าไม่มีให้ใช้ workspace ปกติ
    target_cwd = cwd if cwd else workspace

    # เช็คว่า path มีอยู่จริงไหม
    if not os.path.exists(target_cwd):
        return f"❌ Error: Working directory not found: {target_cwd}"

    logger.info(f"⚡ Executing in Sandbox: {command} (cwd={target_cwd})")

    try:
        # ตั้งค่า Environment (ใช้ workspace หลักในการหา .venv เสมอ เพื่อความชัวร์)
        env = os.environ.copy()
        env["PYTHONPATH"] = workspace + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUTF8"] = "1"
        env["PIP_NO_INPUT"] = "1"

        venv_path = os.path.join(workspace, ".venv")
        if os.path.exists(venv_path):
            if os.name == 'nt':
                venv_scripts = os.path.join(venv_path, "Scripts")
            else:
                venv_scripts = os.path.join(venv_path, "bin")
            if os.path.exists(venv_scripts):
                env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")
                env["VIRTUAL_ENV"] = venv_path

        # รันคำสั่งโดยใช้ target_cwd ที่เราเลือกมา
        result = subprocess.run(
            command,
            shell=True,
            cwd=target_cwd,  # <--- ใช้ตัวแปรนี้แทน
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
            # ถ้า output ยาวเกินไป ตัดให้สั้นลงหน่อย (Optional)
            if len(output) > 2000:
                return f"✅ Command Success:\n{output[:2000]}\n... [Output Truncated]"
            return f"✅ Command Success:\n{output}"
        else:
            return f"❌ Command Failed (Exit Code {result.returncode}):\n{output}\nERROR LOG:\n{error}"

    except subprocess.TimeoutExpired:
        return f"⏰ Command Timeout! (Over {timeout}s)."
    except Exception as e:
        return f"❌ Execution Error: {e}"


def install_package(package_name: str) -> str:
    if any(char in package_name for char in [";", "&", "|", ">"]): return "❌ Error: Invalid package name."
    return run_sandbox_command(f"pip install {package_name}")


# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    "get_jira_issue": get_jira_issue, "list_files": list_files, "read_file": read_file,
    "edit_file": edit_file, "git_setup_workspace": git_setup_workspace, "git_commit": git_commit,
    "git_push": git_push, "git_pull": git_pull, "create_pr": create_pr, "write_file": write_file,
    "append_file": append_file, "run_command": run_sandbox_command, "install_package": install_package
}

TOOL_SCHEMAS = {
    "edit_file": {"required": ["target_text", "replacement_text"], "file_path": True},
    "write_file": {"required": ["content"], "file_path": True},
    "append_file": {"required": ["content"], "file_path": True},
    "read_file": {"required": [], "file_path": True},
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name not in TOOLS: return {"success": False, "output": f"Error: Unknown tool '{tool_name}'"}
    if tool_name in TOOL_SCHEMAS:
        schema = TOOL_SCHEMAS[tool_name]
        valid_keys = set(schema["required"])
        if schema.get("file_path"): valid_keys.add("file_path")
        if set(args.keys()) - valid_keys: return {"success": False,
                                                  "output": f"[ERROR] Invalid arguments. Expected: {list(valid_keys)}"}
        missing = [k for k in schema["required"] if k not in args]
        if missing: return {"success": False, "output": f"[ERROR] Missing required arguments: {missing}"}
    try:
        func = TOOLS[tool_name]
        raw_result = str(func(**args))
        is_success = "✅" in raw_result or "SUCCESS" in raw_result.upper()
        clean_output = raw_result.replace("✅", "[SUCCESS]").replace("❌", "[ERROR]")
        return {"success": is_success, "output": clean_output}
    except Exception as e:
        return {"success": False, "output": f"Error executing {tool_name}: {str(e)}"}


# ==============================================================================
# 🧩 HELPER FUNCTIONS
# ==============================================================================

def sanitize_json_input(raw_text):
    clean_text = re.sub(r'^```json\s*', '', raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r'^```\s*', '', clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r'```$', '', clean_text, flags=re.MULTILINE)

    def fix_triple_quotes(match):
        content = match.group(1).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{content}"'

    clean_text = re.sub(r'"""(.*?)"""', fix_triple_quotes, clean_text, flags=re.DOTALL)
    return clean_text.strip()


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
            if isinstance(obj, dict) and "action" in obj: results.append(obj)
            pos = end_index
        except:
            pos += 1
    if not results:
        try:
            matches = re.findall(r"(\{.*?\})", text, re.DOTALL)
            for match in matches:
                try:
                    clean = match.replace("true", "True").replace("false", "False").replace("null", "None")
                    obj = ast.literal_eval(clean)
                    if isinstance(obj, dict) and "action" in obj: results.append(obj)
                except:
                    continue
        except:
            pass
    return results


def extract_code_block(text: str) -> str:
    all_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if not all_blocks: return None
    for block in reversed(all_blocks):
        if '"action":' in block: continue
        return block
    return None


# ==============================================================================
# 🚀 MAIN LOOP
# ==============================================================================
def run_hephaestus_task(task: str, job_id: str = None, max_steps: int = 45):
    if settings.CURRENT_AGENT_NAME != "Hephaestus":
        settings.CURRENT_AGENT_NAME = "Hephaestus"

    # 1️⃣ SETUP LOGGING
    if not job_id:
        job_id = f"manual_{uuid.uuid4().hex[:8]}"

    # --- แก้ไขส่วนนี้ ---
    # หาตำแหน่งของไฟล์ agent.py นี้ (D:\Project\Olympus-Agents\agents\hephaestus\agent.py)
    current_script_path = os.path.abspath(__file__)
    # ถอยกลับไป 2 ระดับ เพื่อไปที่โฟลเดอร์หลักของโปรเจกต์ (D:\Project\Olympus-Agents)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_script_path)))

    # บังคับให้สร้างโฟลเดอร์ logs ใน Project Root
    logs_dir = os.path.join(project_root, "logs", "hephaestus")
    # ------------------

    os.makedirs(logs_dir, exist_ok=True)
    log_filename = os.path.join(logs_dir, f"job_{job_id}.log")

    # 🌟 Redirect print to BOTH console and file
    original_stdout = sys.stdout
    dual_logger = DualLogger(log_filename)
    sys.stdout = dual_logger

    try:
        print(f"\n==================================================")
        print(f"🔨 Launching Hephaestus (The Builder)...")
        print(f"▶️ [Worker] Starting Job {job_id}")
        print(f"📅 Time: {datetime.now()}")
        print(f"📋 Task: {task}")
        print(f"📁 Log File: {os.path.abspath(log_filename)}")
        print(f"==================================================\n")

        agent_action_history = []
        consecutive_test_failures = 0

        history = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task}
        ]


        persistent_code_block = None

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
            # 🟢 1. MIDDLEWARE: CAPTURE & VALIDATE CODE BLOCK (SMART & SAFE)
            # =========================================================

            all_raw_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", content, re.DOTALL)
            # กรอง JSON Action ออก
            valid_code_blocks = [b for b in all_raw_blocks if '"action":' not in b]

            new_code_block = None

            if not valid_code_blocks:
                # Case 0: ไม่เจอ Code เลย
                pass

            elif len(valid_code_blocks) == 1:
                # Case 1: เจออันเดียว -> จบข่าว ใช้เลย
                new_code_block = valid_code_blocks[0]

            else:
                # Case 2: เจอหลายอัน -> ต้องระวัง! ⚠️
                # เรียงลำดับจาก ยาวมาก -> สั้นน้อย
                sorted_blocks = sorted(valid_code_blocks, key=len, reverse=True)
                big_block = sorted_blocks[0]
                second_block = sorted_blocks[1]

                # 🕵️‍♂️ เช็คก่อนว่ากำลังเขียนไฟล์อะไร?
                target_file = args.get("file_path", "").lower()
                is_markdown = target_file.endswith(".md")

                # 📏 DOMINANCE CHECK (กฎ 20%)
                # ถ้าก้อนรอง (Second) มีขนาดใหญ่เกิน 20% ของก้อนหลัก (Main)
                # แปลว่ามันน่าจะเป็น "ไฟล์แยก" ไม่ใช่แค่ "Snippet ประกอบ"
                if not is_markdown and len(second_block) > len(big_block) * 0.2:
                    print(
                        f"🚫 BLOCKED: Ambiguous! Found 2 significant code blocks ({len(big_block)} chars vs {len(second_block)} chars).")
                    error_msg = (
                        "🛑 SYSTEM ERROR: Multiple Files Detected!\n"
                        "I found two large code blocks. I cannot determine which one to write.\n"
                        "👉 RULE: Send ONE file per message. Wait for the result before sending the next one."
                    )
                    history.append({"role": "assistant", "content": content})
                    history.append({"role": "user", "content": error_msg})
                    continue

                # ถ้าผ่าน (ก้อนรองเล็กจิ๋ว) -> สรุปว่าเป็น Docs ที่มี Snippet -> เลือกก้อนใหญ่สุด
                new_code_block = big_block

            # -------------------------------------------------------------
            # Update Memory
            if new_code_block:
                persistent_code_block = new_code_block.strip()
                print(f"📦 Captured NEW code block ({len(persistent_code_block)} chars)")
                print(f"✨ NEW memory captured.")
            elif persistent_code_block:
                print("♻️  No new code found, using existing memory.")
            else:
                print("⚠️  No code in memory yet.")

            # 🟢 2. PARSE TOOLS
            content_cleaned = sanitize_json_input(content)
            tool_calls = _extract_all_jsons(content_cleaned)

            # 🟢 3. SMART RECOVERY
            if not tool_calls and ('"action":' in content or "```json" in content):
                print("🚨 DETECTED MALFORMED JSON. Attempting Smart Recovery...")
                action_match = re.search(r'"action"\s*:\s*"(\w+)"', content)
                path_match = re.search(r'"file_path"\s*:\s*"([^"]+)"', content)

                if action_match and path_match and persistent_code_block:
                    found_action = action_match.group(1)
                    found_path = path_match.group(1)
                    if found_action in ["write_file", "append_file"]:
                        print(f"🔧 Auto-Recovered: Executing {found_action} on {found_path}")
                        tool_calls = [
                            {"action": found_action, "args": {"file_path": found_path, "content": persistent_code_block}}]

                if not tool_calls:
                    print("❌ Recovery Failed. Sending Error Message.")
                    history.append({"role": "assistant", "content": content})
                    history.append({"role": "user",
                                    "content": "❌ SYSTEM ERROR: JSON Validation Failed! Please use the 'LAST_CODE_BLOCK' pattern."})
                    continue

            # 🟢 4. EXECUTION LOOP
            seen_tools = set()
            unique_tools = []
            for tool in tool_calls:
                tool_str = json.dumps(tool, sort_keys=True)
                if tool_str not in seen_tools:
                    seen_tools.add(tool_str)
                    unique_tools.append(tool)

            step_outputs = []
            task_finished = False

            for tool_call in unique_tools:
                action = tool_call.get("action")
                args = tool_call.get("args", {})

                # --- Task Complete Logic (Verified & Restored) ---
                if action == "task_complete":
                    task_mode = args.get("mode", "code").lower()
                    validation_error = None
                    workspace = settings.AGENT_WORKSPACE

                    # 1. Check Uncommitted Changes
                    status = run_sandbox_command("git status --porcelain", cwd=workspace)
                    if status.strip():
                        validation_error = "❌ REJECTED: You have uncommitted changes. Please commit or discard them before finishing."

                    # 2. Verify Work (Mode Based)
                    if not validation_error:
                        current_branch = run_sandbox_command("git branch --show-current", cwd=workspace)
                        if "HEAD detached" in current_branch or not current_branch:
                            current_branch = "HEAD"

                        is_main = current_branch in ["main", "master"]
                        source_files = []
                        config_files = []
                        test_files = []
                        has_changes = False

                        if not is_main:
                            diff_output = run_sandbox_command(f"git diff --name-only main...{current_branch}",
                                                              cwd=workspace)
                            changed_files = diff_output.strip().splitlines()
                            if changed_files:
                                has_changes = True
                                for f in changed_files:
                                    f = f.strip()
                                    if not f: continue
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
                            elif not source_files and (config_files or test_files):
                                # อนุโลมให้ผ่านถ้าแก้แค่ Config/Test แต่เตือนหน่อย
                                print("⚠️ Note: Only config/test files changed. Assuming infrastructure/testing task.")

                            elif not is_main and not validation_error:
                                pr_check = run_sandbox_command(f"gh pr list --head {current_branch}", cwd=workspace)
                                if "no open pull requests" in pr_check or not pr_check.strip():
                                    validation_error = "❌ REJECTED: Code committed but NO Pull Request (PR) found. Please create a PR first."

                            # ---------------------------------------------------------
                            # 🐳 DOCKER CHECK (แทรกตรงนี้! เฉพาะ Code Mode และไม่มี Error ก่อนหน้า)
                            # ---------------------------------------------------------
                            if not validation_error:
                                # 1. เช็คประวัติ (History Check)
                                has_deployed = False
                                valid_deploy_actions = ["up", "restart", "start"]

                                for record in agent_action_history:
                                    if record['action'] == 'run_command':
                                        cmd = record['args'].get('command', '').strip().lower()
                                        is_docker_compose = "docker" in cmd and "compose" in cmd
                                        cmd_parts = cmd.split()
                                        if is_docker_compose and any(act in cmd_parts for act in valid_deploy_actions):
                                            has_deployed = True
                                            break

                                if not has_deployed:
                                    validation_error = (
                                        "❌ REJECTED: Definition of Done (DoD) failed!\n"
                                        "You haven't restarted the services to verify your changes.\n"
                                        "👉 You MUST run: `docker-compose up -d --build`"
                                    )

                                # 2. เช็คสถานะจริง (Status Check) - กันเหนียว
                                else:
                                    docker_check = run_sandbox_command("docker ps", cwd=workspace)
                                    # ปรับ Keyword ตามชื่อ Container/Image ของคุณ
                                    if "api" not in docker_check and "payment" not in docker_check and "hephaestus" not in docker_check:
                                        validation_error = (
                                            "❌ REJECTED: Deployment Failed!\n"
                                            "You ran the command, but 'docker ps' shows NO running containers.\n"
                                            "Did the container crash? Check logs."
                                        )
                            # ---------------------------------------------------------

                        # === CASE B: Analysis Mode ===
                        elif task_mode == "analysis":
                            if has_changes:
                                print(
                                    f"⚠️ WARNING: Task completed in 'analysis' mode, but file changes were detected on {current_branch}.")

                    # 3. Final Decision
                    if validation_error:
                        print(f"🚫 {validation_error}")
                        step_outputs.append(validation_error)
                        break  # ดีดกลับไปทำใหม่
                    else:
                        # ✅ ผ่านทุกด่าน จบงานได้
                        task_finished = True
                        step_outputs.append(f"Task Completed: {args.get('summary', 'Done')}")
                        break

                if action not in TOOLS:
                    step_outputs.append(f"❌ Error: Tool '{action}' not found.")
                    continue

                # =========================================================
                # 🟢 5. MIDDLEWARE INJECTION (Replace LAST_CODE_BLOCK)
                # =========================================================
                if "LAST_CODE_BLOCK" in str(args):
                    if not persistent_code_block:
                        print("🛡️ INTERCEPTED: Agent tried to use LAST_CODE_BLOCK but memory is empty.")
                        error_msg = "🛑 PRE-EXECUTION ERROR: You used 'LAST_CODE_BLOCK' but forgot to write the Markdown code block first."
                        step_outputs.append(error_msg)
                        break

                    if action == "edit_file" and args.get("replacement_text") == "LAST_CODE_BLOCK":
                        args["replacement_text"] = persistent_code_block
                        print("✏️ Auto-attached replacement text from memory.")
                    elif action in ["write_file", "append_file"] and args.get("content") == "LAST_CODE_BLOCK":
                        args["content"] = persistent_code_block
                        print(f"📝 Auto-attached content to {args.get('file_path')} from memory.")

                # =========================================================
                # 🧹 6. MARKDOWN STRIPPER
                # =========================================================
                for key in ["content", "replacement_text"]:
                    if key in args and isinstance(args[key], str) and "```" in args[key]:
                        args[key] = re.sub(r"^```[a-zA-Z0-9]*\n", "", args[key])
                        args[key] = re.sub(r"\n```$", "", args[key]).strip()

                # =========================================================
                # 🛡️ 7. GUARDRAILS & SAFETY LOCKS (✅ RESTORED & VERIFIED)
                # =========================================================
                target_file = args.get("file_path", "")

                # --- 7.1 Filename Guardrail ---
                if action in ["write_file", "edit_file", "append_file"]:
                    clean_target = target_file.replace("\\", "/")
                    if clean_target.startswith("docs/") and clean_target != "docs/specs.md":
                        print(f"🚫 BLOCKED: Wrong spec filename '{clean_target}'")
                        error_msg = f"❌ FILENAME ERROR: Spec file MUST be named 'docs/specs.md'. Rename it."
                        step_outputs.append(error_msg)
                        history.append({"role": "assistant", "content": content})
                        history.append({"role": "user", "content": error_msg})
                        break

                # --- 7.2 Spec Guardrail ---
                if action in ["write_file", "edit_file", "append_file"]:
                    if target_file.startswith("src/") or target_file.startswith("tests/"):
                        spec_path = os.path.join(settings.AGENT_WORKSPACE, "docs/specs.md")
                        if not os.path.exists(spec_path):
                            msg = "❌ POLICY VIOLATION: You MUST write 'docs/specs.md' before modifying code."
                            print(msg)
                            step_outputs.append(msg)
                            history.append({"role": "assistant", "content": content})
                            history.append({"role": "user", "content": msg})
                            break

                # --- 7.3 Safety Lock (Overwrite Protection) ---
                if action == "write_file":
                    full_path = os.path.join(settings.AGENT_WORKSPACE, target_file)
                    if os.path.exists(full_path) and target_file.endswith(".py"):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                old_content = f.read()
                            new_content = args.get("content", "")
                            if len(new_content) < len(old_content) * 0.5:
                                msg = f"🚫 SAFETY BLOCK: Preventing accidental large delete on {target_file}."
                                print(msg)
                                step_outputs.append(msg)
                                history.append({"role": "assistant", "content": content})
                                history.append({"role": "user", "content": msg})
                                break
                        except Exception as e:
                            print(f"⚠️ Safety check warning: {e}")

                # =========================================================
                # 🚀 8. EXECUTE
                # =========================================================
                # =========================================================
                # 1️⃣ PRE-EXECUTION: แก้ไขคำสั่งก่อนรัน (Docker Auto-Fix)
                # =========================================================
                if action == "run_command":
                    cmd = args.get("command", "")

                    # กฎ 1: ถ้าสั่ง up เฉยๆ ให้เติม --build และ -d
                    if "docker-compose up" in cmd:
                        if "--build" not in cmd:
                            cmd = cmd.replace("docker-compose up", "docker-compose up --build")
                        if "-d" not in cmd:
                            cmd = cmd.replace("docker-compose up", "docker-compose up -d")
                        print(f"🔧 Auto-fixing command to: {cmd}")
                        args["command"] = cmd

                    # กฎ 2: ป้องกัน BuildKit ค้าง
                    if "docker-compose" in cmd:
                        # 1. เช็คก่อนว่า Agent พยายามตั้งค่าเองหรือยัง? (ถ้าตั้งแล้ว ปล่อยมัน)
                        if "DOCKER_BUILDKIT" not in cmd:
                            # 2. ⚠️ FIX: ลบเว้นวรรคหลังเลข 0 ออก! (Windows CMD เรื่องมากตรงนี้)
                            # จาก "set ...=0 &&" เป็น "set ...=0&&"
                            args["command"] = f"set DOCKER_BUILDKIT=0&& {args['command']}"
                            print(f"🔧 Network Fix Applied: Forced IPv4 & Disabled BuildKit")

                # บันทึก History ว่าจะทำอะไร
                agent_action_history.append({"action": action, "args": args})
                print(f"🔧 Executing: {action}")

                # =========================================================
                # 2️⃣ EXECUTION: รันของจริง!
                # =========================================================
                # ส่ง args ที่แก้แล้วไปรัน
                res_data = execute_tool_dynamic(action, args)
                result_for_ai = res_data["output"]

                if action in ["write_file", "append_file", "edit_file"] and res_data["success"]:
                    persistent_code_block = None
                    print("DEBUG: Memory flushed.", file=sys.stderr)

                # =========================================================
                # 3️⃣ POST-EXECUTION: ตรวจสอบผลลัพธ์ (Loop Detector อยู่ตรงนี้!)
                # =========================================================
                # 🛑 LOOP DETECTOR: เช็คว่า Pytest พังซ้ำซากไหม?
                if action == "run_command" and "pytest" in args.get("command", ""):
                    if "FAILURES" in str(result_for_ai) or "ERRORS" in str(result_for_ai) or "[ERROR]" in str(
                            result_for_ai):
                        consecutive_test_failures += 1
                        print(f"⚠️ Pytest Failed! Count: {consecutive_test_failures}")
                    else:
                        consecutive_test_failures = 0  # Reset ถ้ารันผ่าน

                    # ถ้าผิดซ้ำ 2 รอบขึ้นไป แทรกแซงทันที!
                    if consecutive_test_failures >= 2:
                        # 🕵️‍♂️ หาชื่อไฟล์ล่าสุดที่เพิ่งแก้ไป (ย้อนหลังดูจาก History)
                        last_edited_file = "the source code"  # ค่า Default
                        for record in reversed(agent_action_history):
                            if record['action'] in ["write_file", "edit_file", "append_file"]:
                                last_edited_file = record['args'].get('file_path', "the source code")
                                break

                        # สร้างคำเตือนแบบ Dynamic
                        warning_msg = (
                            "\n\n🛑 SYSTEM INTERVENTION (RULE #7 TRIGGERED):\n"
                            f"You have failed the tests {consecutive_test_failures} times in a row!\n"
                            f"👉 STOP editing `{last_edited_file}`.\n"  # <--- ตรงนี้จะเปลี่ยนตามไฟล์จริง
                            "👉 The error is likely in the TEST file expectation, not the code.\n"
                            "👉 ACTION: Check the TEST file logic and fix the assertion if it's unrealistic."
                        )

                        print(warning_msg)
                        result_for_ai += warning_msg

                # --- Batching Detector Logic ---
                if len(unique_tools) > 1:
                    print(
                        f"⚠️ Warning: Agent tried to batch {len(unique_tools)} tools. Executing only the first one.")
                    result_for_ai += (
                        f"\n\n🚨 SYSTEM ALERT: You violated the 'No Batching' rule! "
                        f"You sent {len(unique_tools)} actions at once. "
                        f"I executed ONLY the first one ('{action}'). "
                        f"The other {len(unique_tools) - 1} actions were IGNORED. "
                        f"Wait for this result before sending the next command."
                    )

                # =========================================================
                # 🎨 SMART LOGGING DISPLAY
                # =========================================================
                if action == "run_command":
                    log_display = result_for_ai
                    if len(log_display) > 2000:
                        log_display = log_display[:2000] + "\n... [Output Truncated] ..."
                    print(f"📄 Result:\n{log_display}")
                else:
                    target_file = args.get("file_path", "unknown")
                    display = f"✅ File operation success: {target_file}" if "success" in str(
                        res_data).lower() and action.startswith("write") else str(result_for_ai)
                    print(f"📄 Result: {display[:300]}..." if len(display) > 300 else f"📄 Result: {display}")

                # ส่งผลลัพธ์กลับไปให้ AI
                step_outputs.append(f"Tool Output ({action}): {result_for_ai}")
                break


            if task_finished:
                print(f"\n✅ BUILD COMPLETE.")
                return

            history.append({"role": "assistant", "content": content})
            history.append({"role": "user", "content": "\n".join(step_outputs)})

        print("❌ FAILED: Max steps reached.")


    finally:

        # ✅ ใช้ locals() เช็คก่อนว่าตัวแปรมีอยู่จริงไหม กันโปรแกรมพังซ้ำซ้อน

        if 'original_stdout' in locals():
            sys.stdout = original_stdout

        if 'dual_logger' in locals():
            dual_logger.close()

            print(f"🔒 Log file closed: {log_filename}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_hephaestus_task(sys.argv[1])
    else:
        run_hephaestus_task("Fix bug on SCRUM-29")
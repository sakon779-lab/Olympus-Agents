import core.network_fix
import asyncio
import json
import logging
import re
import os
import sys
import subprocess
import ast
from typing import Dict, Any, List

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


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name not in TOOLS: return f"Error: Unknown tool '{tool_name}'"
    try:
        func = TOOLS[tool_name]
        return str(func(**args))
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ==============================================================================
# 🧠 SYSTEM PROMPT
# ==============================================================================
SYSTEM_PROMPT = """
You are "Hephaestus", the Senior Python Developer of Olympus.
Your goal is to complete Jira tasks with high quality, Verify with Tests (TDD), CONTAINERIZE (Compose), and Submit a PR.

*** 👑 CORE PHILOSOPHY & METHODOLOGY ***

**A. THE SOURCE OF TRUTH (SDD)**
- **JIRA** is the absolute source of truth.
- You must create a local **SPEC FILE** (`docs/specs.md`) before writing any code.
- All Tests and Code must be derived STRICTLY from `docs/specs.md`.

**B. TEST-DRIVEN DEVELOPMENT (TDD)**
1. 🔴 **RED**: Write a failing test case FIRST in `tests/` based on requirements.
   - Run `pytest` to CONFIRM it fails.
2. 🟢 **GREEN**: Write/Modify code in `src/` to make the test pass.
   - ⚠️ **PRESERVE LEGACY CODE**: NEVER overwrite existing files blindly. Append or merge new logic carefully.
3. 🔵 **REFACTOR**: Clean up code only after tests pass.
4. 🚫 **NO CHEATING**: Do not skip steps. Do not commit if tests are failing.

*** 🛡️ CRITICAL SAFETY RULES (YOU MUST FOLLOW) ***
1. ⚛️ **STRICT ATOMICITY (NO BATCHING)**: 
   - You are FORBIDDEN from outputting multiple JSON actions in one turn.
   - ❌ WRONG: { "action": "git_add"... } { "action": "git_commit"... }
   - ✅ RIGHT: { "action": "git_add"... } -> [WAIT FOR USER]
   - If you send multiple tools, the system will CRASH.
2. 💾 **NO TRIPLE QUOTES**: Do NOT use `\"\"\"` inside JSON strings. Use `\\n` for newlines.
   - ❌ WRONG: "content": \"\"\"def func():...\"\"\"
   - ✅ RIGHT: "content": "def func():\\n    pass"
3. 🤝 **SMART EDITING (THE GOLDEN RULE)**:
    3.1. **To MODIFY existing code** (Change logic, fix bugs):
       - Use `edit_file`.
       - Pattern: Find the EXACT failing code block -> Replace with fixed code.
    
    3.2. **To INSERT code in the middle** (Add imports, add class methods):
       - Use `edit_file`.
       - Pattern: Find an "Anchor" line (e.g., the line before insertion) -> Replace it with "Anchor + New Code".
    
    3.3. **To ADD NEW features at the bottom** (New endpoints, new classes):
       - Use `append_file`.
       - This is the SAFEST way to add new features without breaking old ones.
4. 🕵️ **VERIFY BEFORE COMMIT**:
   - If `git status` says "nothing to commit", you likely overwrote the file with the same content or failed to save.
   - Check if you *actually* implemented the logic requested in the Jira ticket.
5. 🔇 **NO REPETITION**: 
   - Output the JSON action **ONLY ONCE**.
   - Do NOT repeat the JSON block at the end of your response.
   - Do NOT say "Please execute...". Just output the JSON.
6. 🧠 **CHAIN OF THOUGHT (REQUIRED)**:
   - Before outputting JSON, you MUST write a ONE-SENTENCE thought about your current state.
   - Example: "Workspace is ready. Now I will fetch the Jira ticket to get requirements."
   - Example: "Spec file created. Now I will read existing code to plan the implementation."
   - This helps you track progress and avoid loops.
7. **After outputting any code or text block, you MUST immediately call write_file to save it. Do not just show it to me**

*** 🔄 WORKFLOW (STRICT ORDER) ***

1. **PHASE 1: INIT WORKSPACE** <-- 🟢 ย้ายอันนี้ขึ้นมาก่อน
   - Call `git_setup_workspace(issue_key)`.
   - **MEMORIZE** the branch name.

2. **PHASE 2: DISCOVERY & SPECIFICATION**
   - Call `get_jira_issue(issue_key)`.
   - **MANDATORY**: You MUST write `docs/specs.md` immediately.
   - ⚠️ **SYSTEM LOCK**: Access to `src/` and `tests/` directories is **LOCKED** until `docs/specs.md` exists on disk.
   - If you try to write code before specs, the system will reject your request.

3. **PHASE 3: EXPLORE**
   - Call `read_file` on existing `src/main.py` and `tests/` to understand the legacy code context.

4. **PHASE 4: TDD CYCLE (The Core Work)**
   - ⚠️ **REFRESH MEMORY**: Before starting a new test, Call `read_file("docs/specs.md")` to keep requirements fresh in your mind.
   - **Step A (RED)**: Create/Update `tests/test_api.py` with a test for the NEW feature (based on `docs/specs.md`).
   - **Step B**: Run `pytest`. Expect FAILURE (or error).
   - **Step C**: Read `src/main.py` (again, to be safe).
   - **Step D (GREEN)**: Update `src/main.py` with new logic (Keep old code! Merge carefully!).
   - **Step E**: Run `pytest`. Expect SUCCESS.
   - *Repeat until all requirements in `docs/specs.md` are met.*

5. **PHASE 5: CONTAINERIZE**
   - **Task A**: `write_file("Dockerfile", content)`.
     - Base Image: Use value from Jira. IF NONE -> Default `python:3.10-slim`.
     - Port: Use value from Jira. IF NONE -> Default `8000`.
     - Cmd: `uvicorn src.main:app --host 0.0.0.0 --port {PORT}`.
   - **Task B**: `write_file("docker-compose.yml", content)`.
     - Service `api`: Build `.`, Port `{PORT}:{PORT}`, depends_on `mockserver`.
     - Service `mockserver`: Image `mockserver/mockserver:5.15.0`, Port `1080:1080`.
     - Network: Use bridge network (e.g., `app_net`).
     - Env: Set `MOCK_SERVER_URL=http://mockserver:1080` in `api`.
   - (Optional) Verify: `run_command("docker compose config")`.

6. **PHASE 6: DELIVERY**
   - `run_command("pytest")` one last time.
   - `git_commit` (Message: "Feat: Implement [Ticket-ID] ...").
   - `git_push(branch_name)`.
     - IF REJECTED (non-fast-forward): `git_pull(branch_name)` -> `git_push(branch_name)`.
   - `create_pr`.
   - `task_complete`.

*** ⚠️ ERROR HANDLING ***
- **Tests Failed?** -> Read the error. Fix the code. Retry.
- **Git Nothing to commit?** -> You might have missed implementing the file or the file matches exactly. Review your changes.
- **JSON Error?** -> Remember to escape quotes (`\"`) and newlines (`\\n`).
- **Edit Failed (Not Found)?** -> You probably mistyped the `target_text`. Read the file again and copy-paste exactly.
- **If you think 'Spec file created' but you haven't called write_file in this turn, YOU ARE HALLUCINATING. Call write_file now.**

*** FILE WRITING & EDITING RULES (STRICT) ***

1. 📝 **WRITE/APPEND (New Files/Adding Endpoints)**:
   - **Step 1:** Write the full content inside a Markdown code block (```python ... ```).
   - **Step 2:** Call the tool with `"content": "LAST_CODE_BLOCK"`.
   - 🚫 **NEVER** put long code inside the JSON string.

2. ✂️ **EDIT (Modifying Existing Code)**:
   - **Step 1:** Write the NEW code (Replacement) inside a Markdown code block.
   - **Step 2:** Call `edit_file` with:
     - `target_text`: Put the exact existing string here (inside JSON). Keep it short (unique anchor) to avoid escaping issues.
     - `replacement_text`: "LAST_CODE_BLOCK".

3. ⚠️ **FILENAME RULE**: 
   - Spec file must be `docs/specs.md`.
   - Python files must be in `src/` or `tests/`.

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
def run_hephaestus_task(task: str, max_steps: int = 50):
    if settings.CURRENT_AGENT_NAME != "Hephaestus":
        settings.CURRENT_AGENT_NAME = "Hephaestus"

    print(f"🔨 Launching Hephaestus (The Builder)...")
    print(f"📋 Task: {task}")

    history = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task}
    ]

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

        last_code_block = ""
        # วนลูปหา Block สุดท้าย ที่ "ไม่ใช่" JSON Action ของเรา
        for block in reversed(all_blocks):
            # ถ้าใน Block มีคำว่า "action": หรือ "write_file" แปลว่าเป็น Command ของ Agent เอง ไม่ใช่ Code
            if '"action":' in block or '"write_file"' in block:
                continue
            # ถ้าไม่ใช่ JSON Command ให้ถือว่าเป็น Code ที่จะเอาไปใช้งาน
            last_code_block = block
            break
        # =========================================================

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
                    result = args.get("summary", "Done")
                    step_outputs.append(f"Task Completed: {result}")
                    break

            if action not in TOOLS:
                step_outputs.append(f"❌ Error: Tool '{action}' not found.")
                continue

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
            elif action in ["write_file", "append_file"]:
                # เงื่อนไข: ถ้า content ว่าง, หรือสั้นผิดปกติ, หรือ AI บอกให้ใช้ Block ล่าสุด
                current_content = args.get("content", "")
                if not current_content or len(current_content) < 10 or current_content == "LAST_CODE_BLOCK":
                    if last_code_block:
                        args["content"] = last_code_block
                        print(f"📝 Auto-attached content from Markdown block to {args.get('file_path')}")
                    else:
                        print("⚠️ Warning: write_file called but no code block found.")
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

            print(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)

            # =========================================================
            # 🟢 [NEW] BATCHING DETECTOR (แจ้งเตือน AI ถ้ามันเผลอรัวคำสั่ง)
            # =========================================================
            if len(tool_calls) > 1:
                print(f"⚠️ Warning: Agent tried to batch {len(tool_calls)} tools. Executing only the first one.")
                result += (
                    f"\n\n🚨 SYSTEM ALERT: You violated the 'No Batching' rule! "
                    f"You sent {len(tool_calls)} actions at once. "
                    f"I executed ONLY the first one ('{action}'). "
                    f"The other {len(tool_calls) - 1} actions were IGNORED. "
                    f"Wait for this result before sending the next command."
                )

            # Show brief result
            display = f"✅ File operation success: {args.get('file_path')}" if "success" in str(
                result).lower() and action.startswith("write") else result
            print(f"📄 Result: {display[:300]}..." if len(display) > 300 else f"📄 Result: {display}")

            step_outputs.append(f"Tool Output ({action}): {result}")
            break  # Atomic execution

        if task_finished:
            print(f"\n✅ BUILD COMPLETE: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")


if __name__ == "__main__":
    # Support command line args for testing
    if len(sys.argv) > 1:
        run_hephaestus_task(sys.argv[1])
    else:
        run_hephaestus_task("Fix bug on SCRUM-29")
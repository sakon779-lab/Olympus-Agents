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

### 1. File Operations
- **read_file(file_path)**
- **write_file(file_path, content)**
- **append_file(file_path, content)**
- **edit_file(file_path, target_text, replacement_text)**
- **list_files(directory=".")**
  Lists files in a directory. Default is current directory.

### 2. Git & Workflow
- **git_setup_workspace(issue_key, base_branch="main", ...)**
  Initializes the workspace based on the JIRA issue.
- **git_commit(message)**
  Auto-stages (`git add .`) and commits.
- **git_push(branch_name=None)**
  Pushes to remote. If `branch_name` is omitted, pushes the current branch.
- **git_pull(branch_name=None)**
  Pulls latest changes.
- **create_pr(title, body="Automated PR...", base_branch="main", head_branch=None)**
  Creates a PR.
  - `title`: Required.
  - `body`: Optional description.
  - `base_branch`: Target branch (default: main).
  - `head_branch`: Source branch (default: current branch).

### 3. System & JIRA
- **get_jira_issue(issue_key)**
  Fetches requirements (e.g., "SCRUM-29").
- **run_command(command, cwd=None, timeout=300)**
  Runs a shell command.
- **install_package(package_name)**
  Installs packages.
- **task_complete(issue_key=None, summary=None)**
  Call ONLY when the task is fully done.

## Verification Rules
1. Rely primarily on automated tests (`pytest`).
2. If `pytest` passes, you do NOT need to manually verify endpoints using `curl` or `wget` unless explicitly asked.
3. Trust that if the Docker container is "Up" (via `docker ps`), the deployment is successful.

RESPONSE FORMAT (JSON ONLY):
{{ "action": "tool_name", "args": {{ ... }} }}
"""


def truncate_middle(text: str, limit: int = 2500) -> str:
    """ช่วยตัดข้อความตรงกลางออกเพื่อให้เห็นทั้งจุดเริ่มต้นและจุดจบของ Log"""
    if not text or len(text) <= limit:
        return text

    head_size = 800  # เก็บ 800 ตัวแรก (เพื่อดูบริบทการเริ่มรัน)
    tail_size = 1500  # เก็บ 1500 ตัวสุดท้าย (สำคัญที่สุด: เพื่อดู Error message)

    return (
        f"{text[:head_size]}\n\n"
        f"--- [ ✂️ TRUNCATED {len(text) - (head_size + tail_size)} CHARS ✂️ ] ---\n\n"
        f"{text[-tail_size:]}"
    )

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

        # --- แทนที่ในส่วนแสดงผลเดิม ---
        clean_output = truncate_middle(output)
        clean_error = truncate_middle(error)

        if result.returncode == 0:
            return f"✅ Command Success:\n{clean_output}"
        else:
            # ในเคสพัง เราต้องแสดงทั้ง output และ error log ที่ตัดแล้ว
            return f"❌ Command Failed (Exit Code {result.returncode}):\n{clean_output}\nERROR LOG:\n{clean_error}"

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
    # --- JIRA & Setup ---
    "get_jira_issue": {
        "required": ["issue_key"],
        "file_path": False,
        "description": "Fetches details of a JIRA issue."
    },
    "git_setup_workspace": {
        "required": ["issue_key"],
        "optional": ["base_branch", "agent_name", "job_id"],
        "file_path": False,
        "description": "Clones repo, checks out branch based on JIRA issue."
    },

    # --- File Operations ---
    "list_files": {
        "required": [],
        "optional": ["directory"], # มี default value = "."
        "file_path": False,
        "description": "Lists files in the specified directory."
    },
    "read_file": {
        "required": [],
        "file_path": True, # รับ file_path เป็น arg แรก
        "description": "Reads file content."
    },
    "write_file": {
        "required": ["content"],
        "file_path": True,
        "description": "Overwrites file with content."
    },
    "append_file": {
        "required": ["content"],
        "file_path": True,
        "description": "Appends content to end of file."
    },
    "edit_file": {
        "required": ["target_text", "replacement_text"],
        "file_path": True,
        "description": "Replaces exact string matches."
    },

    # --- Git Operations ---
    "git_commit": {
        "required": ["message"],
        "file_path": False,
        "description": "Stages all files and commits with message."
    },
    "git_push": {
        "required": [],
        "optional": ["branch_name"], # มี default value = None
        "file_path": False,
        "description": "Pushes changes to remote."
    },
    "git_pull": {
        "required": [],
        "optional": ["branch_name"], # มี default value = None
        "file_path": False,
        "description": "Pulls latest changes."
    },
    "create_pr": {
        "required": ["title"],
        "optional": ["body", "base_branch", "head_branch"], # มี default value หมด
        "file_path": False,
        "description": "Creates a GitHub Pull Request."
    },

    # --- System ---
    "run_command": { # Map กับ run_sandbox_command
        "required": ["command"],
        "optional": ["cwd", "timeout"],
        "file_path": False,
        "description": "Runs a shell command."
    },
    "install_package": {
        "required": ["package_name"],
        "file_path": False,
        "description": "Installs a Python/System package."
    },
    "task_complete": {
        "required": [],
        "optional": ["issue_key", "summary", "mode"],
        "file_path": False,
        "description": "Marks task as finished."
    }
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name not in TOOLS:
        return {"success": False, "output": f"Error: Unknown tool '{tool_name}'"}

    if tool_name in TOOL_SCHEMAS:
        schema = TOOL_SCHEMAS[tool_name]

        # ✅ FIX 1: เริ่มต้นด้วย Required keys
        valid_keys = set(schema.get("required", []))

        # ✅ FIX 2: เติม Optional keys เข้าไปด้วย! (นี่คือจุดที่ขาดไป)
        if "optional" in schema:
            valid_keys.update(schema["optional"])

        # ✅ FIX 3: เติม file_path (ถ้ามี)
        if schema.get("file_path"):
            valid_keys.add("file_path")

        # 🕵️‍♂️ Check: มีตัวแปรแปลกปลอมไหม?
        unknown_args = set(args.keys()) - valid_keys
        if unknown_args:
            return {
                "success": False,
                "output": f"[ERROR] Invalid arguments: {list(unknown_args)}. Allowed: {list(valid_keys)}"
            }

        # 🕵️‍♂️ Check: ตัวแปรบังคับครบไหม?
        missing = [k for k in schema.get("required", []) if k not in args]
        if missing:
            return {"success": False, "output": f"[ERROR] Missing required arguments: {missing}"}

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

import re
import ast
import json
import sys  # เพิ่ม import sys เพื่อใช้ print stderr


def sanitize_json_input(raw_text):
    # 1. Markdown Cleanup
    clean_text = re.sub(r'^```json\s*', '', raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r'^```\s*', '', clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r'```$', '', clean_text, flags=re.MULTILINE)

    # 2. Triple Quote Fix
    def fix_triple_quotes(match):
        content = match.group(1).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{content}"'

    clean_text = re.sub(r'"""(.*?)"""', fix_triple_quotes, clean_text, flags=re.DOTALL)

    clean_text = clean_text.strip()

    # 3. 🚀 Single Quote Auto-Fix (Python Dict -> JSON)
    try:
        # เทคนิค: แปลง Boolean/Null ให้เป็น Python
        py_compatible_text = clean_text.replace("true", "True").replace("false", "False").replace("null", "None")

        # ลอง Parse
        parsed = ast.literal_eval(py_compatible_text)

        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed)

    except Exception as e:
        # ⚠️ DEBUG: ปริ้นท์ออกมาดูว่าทำไม AST ถึงพัง (ช่วยได้เยอะมากตอนแก้บั๊ก)
        print(f"⚠️ [Sanitize] AST Parse Failed: {e}", file=sys.stderr)
        # print(f"⚠️ [Sanitize] Problematic Text: {clean_text[:100]}...", file=sys.stderr)
        pass

    # 4. Fallback: Regex Fix (ใช้เฉพาะตอนจำเป็นจริงๆ)
    # ข้อควรระวัง: Regex นี้อาจทำลาย string ที่มี " ซ้อนอยู่ข้างใน
    clean_text = re.sub(r"(?<=[\{\[\,\:])\s*'(?![s\w])", ' "', clean_text)
    clean_text = re.sub(r"(?<![s\w])'\s*(?=[\}\]\,\:])", '" ', clean_text)

    return clean_text


# def parse_agent_response_priority(text: str):
#     """
#     จัดลำดับความสำคัญ:
#     1. ถ้าเจอ JSON Action -> ให้ยึด Action เป็นหลัก (Ignore code blocks อื่นๆ ที่เป็นแค่ Summary)
#     2. ถ้าไม่เจอ Action -> ค่อยไปดูว่ามี Code Block ที่ต้องเขียนไฟล์ไหม
#     """
#
#     # 1. ลองหา JSON Action ก่อน (Priority สูงสุด)
#     jsons = _extract_all_jsons(text)
#
#     # กรองเอาเฉพาะที่มี key 'action' จริงๆ เพื่อความชัวร์
#     valid_actions = [j for j in jsons if "action" in j]
#
#     if valid_actions:
#         # ✅ เจอ Action! จบข่าว ไม่สน Code Block อื่น
#         # เอาตัวสุดท้าย (Latest thought) มาใช้
#         return {
#             "type": "action",
#             "content": valid_actions[-1]
#         }
#
#     # 2. ถ้าไม่มี Action เลย ค่อยลองหา Code Block (เช่น กรณีเขียนไฟล์)
#     code_block = extract_code_block(text)
#     if code_block:
#         return {
#             "type": "code",
#             "content": code_block
#         }
#
#     # 3. ถ้าไม่มีอะไรเลย ก็คือข้อความคุยเล่น
#     return {
#         "type": "text",
#         "content": text
#     }

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


# def extract_code_block(text: str) -> str:
#     all_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
#     if not all_blocks: return None
#     for block in reversed(all_blocks):
#         if '"action":' in block: continue
#         return block
#     return None


# ==============================================================================
# 🚀 MAIN LOOP
# ==============================================================================
import json
import re
import os
import sys
import uuid
from datetime import datetime


# (สมมติว่า imports และ functions อื่นๆ ครบถ้วนแล้ว)

def run_hephaestus_task(task: str, job_id: str = None, max_steps: int = 45):
    if settings.CURRENT_AGENT_NAME != "Hephaestus":
        settings.CURRENT_AGENT_NAME = "Hephaestus"

    # 1️⃣ SETUP LOGGING
    if not job_id:
        job_id = f"manual_{uuid.uuid4().hex[:8]}"

    # --- Path Setup ---
    current_script_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_script_path)))
    logs_dir = os.path.join(project_root, "logs", "hephaestus")

    os.makedirs(logs_dir, exist_ok=True)
    log_filename = os.path.join(logs_dir, f"job_{job_id}.log")

    # Setup Dual Logger
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
        persistent_code_block = None

        history = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task}
        ]

        for step in range(max_steps):
            print(f"\n🔄 Thinking (Step {step + 1})...")

            # --- LLM Query ---
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
            # 🟢 1. PARSE & PRIORITIZE (FIXED for Infinite Loop)
            # =========================================================

            # 1.1 Extract JSON Actions FIRST
            content_cleaned = sanitize_json_input(content)
            tool_calls = _extract_all_jsons(content_cleaned)

            # 🛑 IMMUNITY CHECK: ถ้าจบงาน ให้ข้ามการตรวจ Code Block ทั้งหมด
            # (แก้ปัญหาที่ Agent ชอบสรุปงานยาวๆ แล้วมี Code Block หลายอันจนโดนบล็อก)
            is_task_finishing = any(t.get("action") == "task_complete" for t in tool_calls)

            new_code_block = None

            if is_task_finishing:
                print("🏁 Task Completion Detected: Bypassing ambiguity checks (ignoring summary blocks).")
                # ไม่ต้องหา code block ปล่อยให้มันจบงานไปเลย
            else:
                # --- เข้าสู่โหมดปกติ (เฉพาะเมื่อยังไม่จบงาน) ---

                # 🕵️‍♂️ Sniff File Type
                is_markdown_mode = False
                if tool_calls:
                    first_args = tool_calls[0].get("args", {})
                    target_path = first_args.get("file_path", "").lower()
                    if target_path.endswith(".md"):
                        is_markdown_mode = True

                # 1.2 Extract Code Blocks
                all_code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", content, re.DOTALL)
                valid_code_blocks = [b for b in all_code_blocks if '"action":' not in b]

                if valid_code_blocks:
                    sorted_blocks = sorted(valid_code_blocks, key=len, reverse=True)
                    big_block = sorted_blocks[0]

                    # Check Ambiguity (กฎ 20%)
                    if len(sorted_blocks) > 1 and not is_markdown_mode:
                        second_block = sorted_blocks[1]
                        if len(second_block) > len(big_block) * 0.2 and len(tool_calls) <= 1:
                            print(f"🚫 BLOCKED: Ambiguous! Found 2 significant code blocks.")
                            error_msg = (
                                "🛑 SYSTEM ERROR: Multiple Files Detected!\n"
                                "I found two large code blocks but I'm not in Markdown mode.\n"
                                "👉 RULE: Send ONE file per message."
                            )
                            history.append({"role": "assistant", "content": content})
                            history.append({"role": "user", "content": error_msg})
                            continue

                    new_code_block = big_block

            # Update Memory (Update เฉพาะถ้าไม่ใช่การจบงาน หรือถ้ามี Block ใหม่)
            if new_code_block:
                persistent_code_block = new_code_block.strip()
                print(f"📦 Captured NEW code block ({len(persistent_code_block)} chars)")
                print(f"✨ NEW memory captured.")
            elif persistent_code_block and not is_task_finishing:
                print("♻️  No new code found, using existing memory.")
            elif is_task_finishing:
                print("ℹ️  Task finishing: Memory hold released.")
            else:
                print("⚠️  No code in memory yet.")

            # =========================================================
            # 🟢 2. RECOVERY & VALIDATION
            # =========================================================
            if not tool_calls and ('"action":' in content):
                print("🚨 DETECTED MALFORMED JSON. Attempting Smart Recovery...")
                action_match = re.search(r'"action"\s*:\s*"(\w+)"', content)
                path_match = re.search(r'"file_path"\s*:\s*"([^"]+)"', content)

                if action_match and path_match and persistent_code_block:
                    found_action = action_match.group(1)
                    found_path = path_match.group(1)
                    if found_action in ["write_file", "append_file"]:
                        print(f"🔧 Auto-Recovered: Executing {found_action} on {found_path}")
                        tool_calls = [{"action": found_action,
                                       "args": {"file_path": found_path, "content": persistent_code_block}}]

            if not tool_calls:
                print("❌ No valid action found.")
                history.append({"role": "assistant", "content": content})
                continue

            # =========================================================
            # 🟢 3. EXECUTION LOOP
            # =========================================================
            unique_tools = []
            seen = set()
            for t in tool_calls:
                s = json.dumps(t, sort_keys=True)
                if s not in seen:
                    seen.add(s)
                    unique_tools.append(t)

            step_outputs = []
            task_finished = False

            for tool_call in unique_tools:
                action = tool_call.get("action")
                args = tool_call.get("args", {})

                # 🛡️ GLOBAL VARIABLES
                target_file = args.get("file_path", "").replace("\\", "/")
                workspace = settings.AGENT_WORKSPACE

                # ---------------------------------------------------------
                # 🏆 TASK COMPLETE LOGIC
                # ---------------------------------------------------------
                if action == "task_complete":
                    task_mode = args.get("mode", "code").lower()
                    validation_error = None

                    # 🧹 CLEANLINESS CHECK
                    clean_preview = run_sandbox_command("git clean -nd", cwd=workspace)
                    status = run_sandbox_command("git status --porcelain", cwd=workspace)

                    # --- 🟢 FIX START: กรอง Noise ออก ---
                    dirty_items = []

                    # 1. เช็ค Untracked Files (จาก git clean)
                    if clean_preview.strip():
                        for line in clean_preview.splitlines():
                            line = line.strip()
                            # ข้ามบรรทัดว่าง หรือข้อความที่ไม่ใช่ไฟล์
                            if line and "Would remove" in line:
                                dirty_items.append(line)

                    # 2. เช็ค Modified Files (จาก git status --porcelain)
                    if status.strip():
                        for line in status.splitlines():
                            line = line.strip()
                            # ข้าม Warning หรือ Note
                            if not line: continue
                            if line.lower().startswith("warning") or line.lower().startswith("note"):
                                continue
                            # ถ้าเป็น ?? (Untracked) หรือ M (Modified) หรือ A (Added)
                            if line[:2].strip() in ["??", "M", "A", "D", "R", "C", "U"]:
                                dirty_items.append(line)
                    # --- 🔴 FIX END ---

                    if dirty_items:
                        error_msg = (
                            "❌ FATAL: WORKSPACE IS DIRTY.\n"
                            "I found untracked/uncommitted changes:\n"
                            f"{chr(10).join(dirty_items[:10])}\n"  # โชว์แค่ 10 บรรทัดแรกพอ
                            "(...and more)\n\n" if len(dirty_items) > 10 else "\n"
                                                                              f"--- [Suggested Cleanup] ---\n"
                                                                              f"1. Commit them: `git add .` -> `git commit`\n"
                                                                              f"2. Or delete them: `git clean -fd`\n"
                                                                              "👉 ACTION: Cleanup is REQUIRED before completing the task."
                        )
                        history.append({"role": "user", "content": error_msg})
                        print(f"🚫 blocked task_complete due to dirty files: {dirty_items}")
                        continue

                        # 🔍 VERIFY WORK
                    if not validation_error:
                        current_branch_raw = run_sandbox_command("git branch --show-current", cwd=workspace)
                        current_branch = current_branch_raw.strip() if current_branch_raw else "HEAD"

                        is_main = current_branch in ["main", "master", "HEAD"]
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
                                print("⚠️ Note: Only config/test files changed. Assuming infrastructure/testing task.")

                            elif not is_main and not validation_error:
                                pr_check = run_sandbox_command(f"gh pr list --head {current_branch}", cwd=workspace)
                                if "no open pull requests" in pr_check or not pr_check.strip():
                                    validation_error = "❌ REJECTED: Code committed but NO Pull Request (PR) found. Please create a PR first."

                            # DOCKER CHECK
                            if not validation_error:
                                has_deployed = False
                                valid_deploy_actions = ["up", "restart", "start"]
                                for record in agent_action_history:
                                    if record['action'] == 'run_command':
                                        cmd = record['args'].get('command', '').strip().lower()
                                        is_docker_compose = "docker" in cmd and "compose" in cmd
                                        if is_docker_compose:
                                            if any(act in cmd for act in valid_deploy_actions):
                                                has_deployed = True
                                                break

                                if not has_deployed:
                                    validation_error = (
                                        "❌ REJECTED: Definition of Done (DoD) failed!\n"
                                        "You haven't restarted the services to verify your changes.\n"
                                        "👉 You MUST run: `docker-compose up -d --build`"
                                    )
                                else:
                                    docker_check = run_sandbox_command("docker ps", cwd=workspace)
                                    if "api" not in docker_check and "payment" not in docker_check and "hephaestus" not in docker_check:
                                        validation_error = (
                                            "❌ REJECTED: Deployment Failed!\n"
                                            "You ran the command, but 'docker ps' shows NO running containers.\n"
                                            "Did the container crash? Check logs."
                                        )

                        # === CASE B: Analysis Mode ===
                        elif task_mode == "analysis":
                            if has_changes:
                                print(
                                    f"⚠️ WARNING: Task completed in 'analysis' mode, but file changes were detected on {current_branch}.")

                    if validation_error:
                        print(f"🚫 {validation_error}")
                        history.append({"role": "user", "content": validation_error})
                        continue
                    else:
                        task_finished = True
                        step_outputs.append(f"Task Completed: {args.get('summary', 'Done')}")
                        break

                if action not in TOOLS:
                    step_outputs.append(f"❌ Error: Tool '{action}' not found.")
                    continue

                # =========================================================
                # 💉 5. MIDDLEWARE INJECTION (LAST_CODE_BLOCK)
                # =========================================================
                if "LAST_CODE_BLOCK" in str(args):
                    if not persistent_code_block:
                        error_msg = "🛑 PRE-EXECUTION ERROR: You used 'LAST_CODE_BLOCK' but memory is empty."
                        step_outputs.append(error_msg)
                        break

                    if action in ["write_file", "append_file"]:
                        args["content"] = persistent_code_block
                        print(f"📝 Auto-attached content to {target_file}")
                    elif action == "edit_file":
                        args["replacement_text"] = persistent_code_block
                        print("✏️ Auto-attached replacement text.")

                # =========================================================
                # 🧹 6. MARKDOWN STRIPPER
                # =========================================================
                for key in ["content", "replacement_text"]:
                    if key in args and isinstance(args[key], str) and "```" in args[key]:
                        args[key] = re.sub(r"^```[a-zA-Z0-9]*\n", "", args[key])
                        args[key] = re.sub(r"\n```$", "", args[key]).strip()

                # =========================================================
                # 🛡️ 7. GUARDRAILS (Strict)
                # =========================================================
                if action.endswith("_file"):
                    clean_target = target_file.replace("\\", "/")
                    # Filename Guardrail
                    if clean_target.startswith("docs/") and clean_target != "docs/specs.md":
                        msg = f"❌ FILENAME ERROR: Spec file MUST be named 'docs/specs.md'."
                        step_outputs.append(msg)
                        history.append({"role": "assistant", "content": content})
                        history.append({"role": "user", "content": msg})
                        break

                    # Spec Guardrail
                    if clean_target.startswith("src/") or clean_target.startswith("tests/"):
                        spec_path = os.path.join(settings.AGENT_WORKSPACE, "docs/specs.md")
                        if not os.path.exists(spec_path):
                            msg = "❌ POLICY VIOLATION: Write 'docs/specs.md' first."
                            step_outputs.append(msg)
                            history.append({"role": "assistant", "content": content})
                            history.append({"role": "user", "content": msg})
                            break

                # Safety Lock (Overwrite)
                if action == "write_file":
                    full_path = os.path.join(settings.AGENT_WORKSPACE, target_file)
                    if os.path.exists(full_path) and target_file.endswith(".py"):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                old_content = f.read()
                            new_content = args.get("content", "")
                            if len(new_content) < len(old_content) * 0.5:
                                msg = f"🚫 SAFETY BLOCK: Preventing large delete on {target_file}."
                                step_outputs.append(msg)
                                break
                        except Exception:
                            pass

                # =========================================================
                # 🚀 8. EXECUTE
                # =========================================================

                # --- Auto-fix Docker commands ---
                elif action == "run_command":
                    cmd = args.get("command", "")

                    # 1. Fix: Ensure detached & build
                    if "docker-compose up" in cmd:
                        if "--build" not in cmd: cmd = cmd.replace("up", "up --build")
                        if "-d" not in cmd: cmd = cmd.replace("up", "up -d")
                        args["command"] = cmd
                        print(f"🔧 Auto-fixing command to: {cmd}")

                    # 2. Fix: Disable BuildKit (Network fix)
                    if "docker" in cmd and "DOCKER_BUILDKIT" not in cmd:
                        args["command"] = f"set DOCKER_BUILDKIT=0&& {args['command']}"
                        print(f"🔧 Network Fix Applied")

                # --- 💉 MIDDLEWARE INJECTION (System Overrides) ---
                elif action == "git_setup_workspace":
                    # 1. Inject Job ID
                    args["job_id"] = job_id

                    # 2. ✅ Inject Agent Name (Dynamic form Settings)
                    current_agent = getattr(settings, "CURRENT_AGENT_NAME", "Unknown").lower()
                    args["agent_name"] = current_agent

                    print(f"💉 System Injected: agent_name='{current_agent}', job_id='{job_id}'")

                # --- Record & Execute ---
                agent_action_history.append({"action": action, "args": args})
                print(f"🔧 Executing: {action}")

                res_data = execute_tool_dynamic(action, args)
                result_for_ai = res_data["output"]

                # Memory Flush
                if action in ["write_file", "append_file", "edit_file"] and res_data["success"]:
                    persistent_code_block = None
                    print("DEBUG: Memory flushed.", file=sys.stderr)

                # =========================================================
                # 🔁 LOOP & ERROR DETECTOR (Pytest) - RESTORED!
                # =========================================================
                if action == "run_command" and "pytest" in args.get("command", ""):
                    if "FAILURES" in str(result_for_ai) or "ERRORS" in str(result_for_ai):
                        consecutive_test_failures += 1
                        print(f"⚠️ Pytest Failed! Count: {consecutive_test_failures}")
                    else:
                        consecutive_test_failures = 0

                    if consecutive_test_failures >= 2:
                        last_edited_file = "the source code"
                        for record in reversed(agent_action_history):
                            if record['action'] in ["write_file", "edit_file", "append_file"]:
                                last_edited_file = record['args'].get('file_path', "the source code")
                                break

                        # ✅ RESTORED: Dynamic Warning Message
                        warning_msg = (
                            "\n\n🛑 SYSTEM INTERVENTION (RULE #7 TRIGGERED):\n"
                            f"You have failed the tests {consecutive_test_failures} times in a row!\n"
                            f"👉 STOP editing `{last_edited_file}`.\n"
                            "👉 The error is likely in the TEST file expectation, not the code.\n"
                            "👉 ACTION: Check the TEST file logic and fix the assertion if it's unrealistic."
                        )
                        print(warning_msg)
                        result_for_ai += warning_msg

                # --- ✅ RESTORED: Batching Detector Logic ---
                if len(unique_tools) > 1:
                    print(f"⚠️ Warning: Agent tried to batch {len(unique_tools)} tools. Executing only the first one.")
                    result_for_ai += (
                        f"\n\n🚨 SYSTEM ALERT: You violated the 'No Batching' rule! "
                        f"You sent {len(unique_tools)} actions at once. "
                        f"I executed ONLY the first one ('{action}'). "
                        f"The other {len(unique_tools) - 1} actions were IGNORED. "
                        f"Wait for this result before sending the next command."
                    )

                # Send Result
                if action == "run_command":
                    log_display = result_for_ai
                    if len(log_display) > 2000:
                        log_display = log_display[:800] + "\n... [TRUNCATED] ...\n" + log_display[-1200:]
                    print(f"📄 Result:\n{log_display}")
                else:
                    print(f"📄 Result: {str(result_for_ai)[:300]}...")

                step_outputs.append(f"Tool Output: {result_for_ai}")

                # ✅ Break loop to enforce anti-batching
                break

                # --- Check Finish ---
            if task_finished:
                print("\n✅ MISSION ACCOMPLISHED.")
                return

            # Append to history
            history.append({"role": "assistant", "content": content})
            history.append({"role": "user", "content": "\n".join(step_outputs)})

        print("❌ FAILED: Max steps reached.")

    finally:
        if 'original_stdout' in locals():
            sys.stdout = original_stdout
        if 'dual_logger' in locals():
            dual_logger.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_hephaestus_task(sys.argv[1])
    else:
        run_hephaestus_task("Fix bug on SCRUM-29")
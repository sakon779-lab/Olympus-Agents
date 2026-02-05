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
from core.tools.file_ops import read_file, write_file, append_file, list_files
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
Your goal is to complete Jira tasks, Verify with Tests, CONTAINERIZE (Compose), and Submit a PR.

*** CRITICAL RULES (YOU MUST FOLLOW THESE) ***
1. ⚛️ **ATOMICITY**: ONE ACTION PER TURN. Wait for result.
2. 🧠 **CONTEXT FIRST**: Read files before editing. NEVER overwrite blindly.
3. 🛠️ **ENVIRONMENT SETUP**:
   - Check for `requirements.txt`.
   - If exists -> `run_command("pip install -q -r requirements.txt")`.
   - Ensure `pytest`, `httpx` are installed.

*** WORKFLOW ***
1. **UNDERSTAND**: Call `get_jira_issue(issue_key)`.
   - Look for Ports, Image versions, and Logic in the output.

2. **INIT WORKSPACE**: Call `git_setup_workspace(issue_key)`.
   - **MEMORIZE BRANCH**: Remember the branch name returned.

3. **DEPENDENCIES**: Install requirements and tools.

4. **PLAN & EXPLORE**: `read_file` existing code.

5. **CODE & TEST**: 
   - Implement in `src/`.
   - Create tests in `tests/`.
   - `run_command("pytest tests/")`.
   - 🛑 IF TESTS FAIL: Fix and Retry.

6. **CONTAINERIZE (SMART MODE)**:
   - **Task A**: `write_file("Dockerfile", content)`.
     - Base Image: Use value from Jira. IF NONE -> Default `python:3.9-slim`.
     - Port: Use value from Jira. IF NONE -> Default `8000`.
     - Cmd: `uvicorn src.main:app --host 0.0.0.0 --port {PORT}`.

   - **Task B**: `write_file("docker-compose.yml", content)`.
     - **Structure**:
       1. `api`: Build `.`, Port `{PORT}:{PORT}`, depends_on `mockserver`.
       2. `mockserver`: Image `mockserver/mockserver:5.15.0`, Port `1080:1080`.
     - **Network**: Use bridge network (e.g., `app_net`).
     - **Env**: Set `MOCK_SERVER_URL=http://mockserver:1080` in `api`.

   - (Optional) Verify: `run_command("docker compose config")`.

7. **DELIVERY**:
   - `git_commit` (Only if tests pass).
   - `git_push(branch_name)`.
   - `create_pr`.
   - `task_complete`.

*** 🛡️ ERROR HANDLING STRATEGIES (GIT) ***
- **IF `git_push` FAILS** (rejected/non-fast-forward):
  1. STOP! Do NOT create PR yet.
  2. Call `git_pull(branch_name)` to sync changes.
  3. Call `git_push(branch_name)` AGAIN to retry.
  4. Only then, proceed to `create_pr`.

*** ERROR HANDLING ***
- Docker Build Error? -> Check syntax. If output is garbled but file exists, proceed.
- Create requirements.txt containing only top-level dependencies (e.g. fastapi, uvicorn, pydantic) without pinning specific versions or system packages
- Git Push Error? -> Ensure you are pushing the CURRENT branch.

*** ⚠️ CRITICAL JSON RULES (YOU MUST FOLLOW) ***
1. **NO TRIPLE QUOTES**: Do NOT use `\"\"\"` inside JSON strings. It is invalid.
2. **ESCAPE NEWLINES**: For multi-line code, you MUST use `\\n` explicitly.
   - ❌ WRONG: "content": \"\"\"def func():\n    pass\"\"\"
   - ✅ RIGHT: "content": "def func():\\n    pass"
3. **ATOMICITY**: ONE ACTION PER TURN.

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

        tool_calls = _extract_all_jsons(content)

        if not tool_calls:
            history.append({"role": "assistant", "content": content})
            continue

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

            # Content Detachment Logic (Fix empty content from LLM)
            if action in ["write_file", "append_file"]:
                if "content" not in args or len(args["content"]) < 10:
                    code_content = extract_code_block(content)
                    if code_content:
                        args["content"] = code_content
                        print("📝 Extracted content from Markdown block.")

            print(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)

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
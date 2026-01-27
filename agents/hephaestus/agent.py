import json
import logging
import re
import os
import sys
import subprocess
from typing import Dict, Any, List

# ✅ Core Configuration & LLM
from core.config import settings
from core.llm_client import query_qwen

# ✅ Core Tools
from core.tools.jira_ops import read_jira_ticket
from core.tools.file_ops import read_file, write_file, append_file, list_files
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Hephaestus] %(message)s')
logger = logging.getLogger("Hephaestus")


# ==============================================================================
# 🛠️ HEPHAESTUS SPECIFIC TOOLS (Sandbox Commanders)
# ==============================================================================

def run_sandbox_command(command: str) -> str:
    """Executes a shell command inside the Agent's Workspace."""
    workspace = settings.AGENT_WORKSPACE

    if not os.path.exists(workspace):
        return f"❌ Error: Workspace not found. Did you run 'git_setup_workspace'?"

    logger.info(f"⚡ Executing in Sandbox: {command}")

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = workspace + os.pathsep + env.get("PYTHONPATH", "")

        # ✅ FIX: UTF-8 encoding for Windows Docker output
        result = subprocess.run(
            command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env
        )

        output = result.stdout + result.stderr
        if result.returncode == 0:
            return f"✅ Command Success:\n{output.strip()}"
        else:
            return f"❌ Command Failed (Exit Code {result.returncode}):\n{output.strip()}"

    except Exception as e:
        return f"❌ Execution Error: {e}"


def install_package(package_name: str) -> str:
    """Installs a Python package in the current environment."""
    if any(char in package_name for char in [";", "&", "|", ">"]):
        return "❌ Error: Invalid package name."
    return run_sandbox_command(f"{sys.executable} -m pip install {package_name}")


# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    "read_jira_ticket": read_jira_ticket,
    "list_files": list_files,
    "read_file": read_file,
    "git_setup_workspace": git_setup_workspace,
    "git_commit": git_commit,
    "git_push": git_push,
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
# 🧠 SYSTEM PROMPT (SMART MODE: DOCKER + COMPOSE + MOCK)
# ==============================================================================
SYSTEM_PROMPT = """
You are "Hephaestus", the Senior Python Developer of Olympus.
Your goal is to complete Jira tasks, Verify with Tests, CONTAINERIZE (Compose), and Submit a PR.

*** CRITICAL: ATOMICITY ***
1. **ONE ACTION PER TURN**: Wait for tool result before proceeding.
2. **NO CHAINING**: Do not call multiple tools in one JSON.

*** WORKFLOW ***
1. **UNDERSTAND**: Call `read_jira_ticket(issue_key)`.
   - **EXTRACT CONFIGS**: Look for specific Ports, Image versions, or Env Vars in the description.

2. **INIT WORKSPACE**: Call `git_setup_workspace(issue_key)`.
   - **MEMORIZE BRANCH**: Remember the branch name returned.

3. **PLAN & EXPLORE**: `list_files` -> Decide files to edit.

4. **CODE & TEST**: 
   - Implement `src/` and `tests/`.
   - `run_command("pytest tests/")`.
   - 🛑 IF TESTS FAIL: Fix code and Re-run tests.

5. **CONTAINERIZE (SMART MODE)**:
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

6. **DELIVERY**:
   - `git_commit` (Only if tests pass).
   - `git_push(branch_name)`. 
     *IMPORTANT*: Use the SAME branch name from Step 2. Do NOT invent a new name.
   - `create_pr` (Leave `branch` arg empty/null).
   - `task_complete`.

*** 🛡️ ERROR HANDLING STRATEGIES (GIT) ***
- **IF `git_push` FAILS** (rejected/non-fast-forward):
  1. STOP! Do NOT create PR yet.
  2. Call `git_pull(branch_name)` to sync changes.
  3. Call `git_push(branch_name)` AGAIN to retry.
  4. Only then, proceed to `create_pr`.

*** ERROR HANDLING ***
- Docker Build Error? -> Check syntax. If output is garbled but file exists, proceed.
- Git Push Error? -> Ensure you are pushing the CURRENT branch.

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
    return results


# ==============================================================================
# 🚀 MAIN LOOP
# ==============================================================================
def run_hephaestus_task(task: str, max_steps: int = 30):
    print(f"🔨 Launching Hephaestus (The Builder)...")
    print(f"🆔 Identity: {settings.CURRENT_AGENT_NAME}")
    print(f"📂 Workspace: {settings.AGENT_WORKSPACE}")
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

            if action == "task_complete":
                task_finished = True
                result = args.get("summary", "Done")
                step_outputs.append(f"Task Completed: {result}")
                break

            if action not in TOOLS:
                step_outputs.append(f"❌ Error: Tool '{action}' not found.")
                continue

            # Content Detachment Logic
            if action in ["write_file", "append_file"]:
                if "content" not in args or len(args["content"]) < 10:
                    code_content = extract_code_block(content)
                    if code_content:
                        args["content"] = code_content
                        print("📝 Extracted content from Markdown block.")

            print(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)

            display_result = result
            if action in ["write_file", "append_file"] and "Error" not in result:
                display_result = f"✅ File operation success: {args.get('file_path')}"

            print(
                f"📄 Result: {display_result[:300]}..." if len(display_result) > 300 else f"📄 Result: {display_result}")
            step_outputs.append(f"Tool Output ({action}): {result}")

            break

        if task_finished:
            print(f"\n✅ BUILD COMPLETE: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")
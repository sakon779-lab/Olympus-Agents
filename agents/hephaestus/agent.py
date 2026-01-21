import json
import logging
import re
import os
import sys
import subprocess
import ast
from typing import Dict, Any, List

# ✅ Core Modules
from core.llm_client import query_qwen
from core.config import JIRA_URL, JIRA_EMAIL, JIRA_TOKEN

# ✅ Core Tools (Refactored)
from core.tools.file_ops import read_file, write_file, append_file, list_files
from core.tools.cmd_ops import run_command
from core.tools.jira_ops import read_jira_ticket
from core.tools.git_ops import git_commit, git_push, create_pr, git_setup_workspace

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Hephaestus] %(message)s')
logger = logging.getLogger("HephaestusAgent")

# ==============================================================================
# 📍 CONFIGURATION
# ==============================================================================
AGENT_WORKSPACE = os.getcwd()
# URL หลักของโปรเจกต์ (ปรับให้ตรงกับ Repo จริงของคุณ)
MAIN_REPO_URL = "https://github.com/sakon779-lab/payment-blockchain.git"


# ==============================================================================
# 🛠️ AGENT SPECIFIC TOOLS
# ==============================================================================

def init_workspace_wrapper(branch_name: str, base_branch: str = "main") -> str:
    """Wrapper เพื่อเรียก Core Tool โดยส่ง Identity ของ Hephaestus"""
    logger.info(f"🔥 Setting up Forge (Workspace) for branch: {branch_name}")
    return git_setup_workspace(
        repo_url=MAIN_REPO_URL,
        branch_name=branch_name,
        base_branch=base_branch,
        cwd=AGENT_WORKSPACE,
        git_username="Hephaestus Dev",
        git_email="hephaestus@olympus.ai"
    )


def run_unit_test(test_path: str) -> str:
    """Runs a unit test file using pytest within the workspace."""
    try:
        full_path = os.path.join(AGENT_WORKSPACE, test_path)
        if not os.path.exists(full_path):
            return f"❌ Error: Test file '{test_path}' not found."

        command = [sys.executable, "-m", "pytest", full_path]

        # เพิ่ม PYTHONPATH ให้รู้จัก src/
        env = os.environ.copy()
        env["PYTHONPATH"] = AGENT_WORKSPACE + os.pathsep + env.get("PYTHONPATH", "")

        logger.info(f"🧪 Running Unit Test: {test_path}...")
        result = subprocess.run(
            command,
            cwd=AGENT_WORKSPACE,
            env=env,
            capture_output=True,
            text=True
        )

        output = result.stdout + "\n" + result.stderr

        if result.returncode == 0:
            return f"✅ TESTS PASSED:\n{output}"
        else:
            return f"❌ TESTS FAILED:\n{output}\n\n👉 INSTRUCTION: Analyze the error and FIX the source code."

    except Exception as e:
        return f"❌ Execution Error: {e}"


def install_package_wrapper(package_name: str) -> str:
    """Installs a Python package."""
    return run_command(f"{sys.executable} -m pip install {package_name}")


def git_pull_wrapper(branch_name: str) -> str:
    """Wrapper for git pull"""
    return run_command(f"git pull origin {branch_name}")


# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    # Core Tools
    "read_jira_ticket": read_jira_ticket,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "git_commit": git_commit,
    "git_push": git_push,
    "create_pr": create_pr,

    # Hephaestus Specific
    "init_workspace": init_workspace_wrapper,
    "run_unit_test": run_unit_test,
    "install_package": install_package_wrapper,
    "git_pull": git_pull_wrapper
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name not in TOOLS: return f"Error: Unknown tool '{tool_name}'"
    try:
        func = TOOLS[tool_name]
        return str(func(**args))
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ==============================================================================
# 🧠 SYSTEM PROMPT (Hephaestus - Ultimate Edition + Content Detachment)
# ==============================================================================
# เราใช้ Prompt ของคุณเป็นแกนหลัก แต่เติม "Content Detachment"
# เพื่อให้ Python Code (extract_code_block) ทำงานได้ถูกต้องครับ
SYSTEM_PROMPT = """
You are "Hephaestus", an Autonomous AI Developer.
Your goal is to complete Jira tasks, Verify with Tests, and Submit a PR.

*** CRITICAL: ATOMICITY & OUTPUT FORMAT ***
1. **ONE ACTION PER TURN**: Strictly ONE JSON block per response.
2. **NO CHAINING**: Wait for the tool's result before planning the next step.
3. **STOP IMMEDIATELY**: Stop generation after `}`.

*** CODING STANDARDS (STRICT) ***
1. **FOLLOW REQUIREMENTS**: Implement EXACTLY what the Jira ticket asks. DO NOT invent new logic or "Hello World" examples.
2. **FILE STRUCTURE**: Source in `src/`, Tests in `tests/`.
3. **IMPORTS**: Use absolute imports (e.g., `from src.main import app`).

*** WORKFLOW (EXECUTE IN ORDER) ***
1. **UNDERSTAND**: 
   - Call `read_jira_ticket(issue_key)`.
   - **LOCK TARGET**: Memorize the requirements. DO NOT look for other tickets.

2. **PLAN**: 
   - Decide which files to create/edit based strictly on Step 1.

3. **INIT**: `init_workspace(branch_name)`.
   - Use a branch name relevant to the ticket (e.g., `feature/SCRUM-24-api`).
   - **CONSISTENCY**: Use this SAME branch name for all future Git operations.

4. **CODE & TEST**: 
   - `write_file` (Source) -> `write_file` (Tests).
   - `run_unit_test` -> Fix if failed.

5. **DELIVERY**:
   - `git_commit` (Only if tests pass).
   - `git_push(branch_name)` (Must match Step 3).
   - `create_pr`.
   - `task_complete`.

*** ERROR HANDLING ***
- **Missing Module**: If `ModuleNotFoundError`, check:
  - External Lib? -> `install_package`.
  - Internal Code? -> Create the missing file.
- **Git Nothing to Commit**: It means code is saved. Proceed to `git_push`.

*** ⚡ CONTENT DETACHMENT (CRITICAL FOR FILES) ***
When using `write_file` or `append_file`, DO NOT put the code inside JSON.
1. Output the JSON Action first.
2. Immediately follow it with a **Markdown Code Block** containing the actual content.

**Format Example:**
[JSON Action]
{ "action": "write_file", "args": { "file_path": "src/main.py" } }

[File Content]
""" + "```" + """python
def main():
    print("Hello from Hephaestus!")
""" + "```" + """

TOOLS AVAILABLE:
read_jira_ticket(issue_key), init_workspace(branch_name), list_files(directory),
read_file(file_path), write_file(file_path), append_file(file_path),
run_unit_test(test_path), git_commit(message), git_push(branch_name),
git_pull(branch_name), create_pr(title, body), task_complete(summary),
install_package(package_name)

RESPONSE FORMAT (JSON ONLY + CODE BLOCK):
{ "action": "tool_name", "args": { ... } }
"""


# ==============================================================================
# 🧩 HELPER: PARSERS
# ==============================================================================
def extract_code_block(text: str) -> str:
    matches = re.findall(r"```\w*\n(.*?)```", text, re.DOTALL)
    if not matches: return ""
    for content in reversed(matches):
        cleaned = content.strip()
        if not ('"action":' in cleaned and '"args":' in cleaned):
            return cleaned
    return ""


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

    if not results:
        # Fallback for Python dict strings
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


# ==============================================================================
# 🚀 MAIN LOOP
# ==============================================================================
def run_hephaestus_task(task_description: str, max_steps: int = 30) -> str:
    logger.info(f"🚀 Starting Dev Task (Hephaestus): {task_description}")

    history = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Task: {task_description}"}
    ]

    for step in range(max_steps):
        logger.info(f"🔄 Step {step + 1}/{max_steps}...")

        try:
            response = query_qwen(history)
            content = str(response.get('message', {}).get('content', ''))
        except Exception as e:
            logger.error(f"❌ LLM Error: {e}")
            return f"LLM Error: {e}"

        print(f"🤖 Hephaestus: {content[:100]}...")

        tool_calls = _extract_all_jsons(content)

        if not tool_calls:
            logger.warning("No valid JSON found.")
            history.append({"role": "assistant", "content": content})
            history.append({"role": "user", "content": "System: Please output a valid JSON Action."})
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

            # Handle File Content from Markdown
            if action in ["write_file", "append_file"]:
                code_content = extract_code_block(content)
                if code_content:
                    args["content"] = code_content
                elif "content" not in args:
                    step_outputs.append("❌ Error: Content missing in Markdown block.")
                    continue

            logger.info(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)
            step_outputs.append(f"Tool Output ({action}):\n{result}")

            # Safety break
            if action == "init_workspace" and "❌" in result:
                return f"FAILED: {result}"

            break  # Strict Atomicity

        if task_finished:
            print(f"\n✅ TASK COMPLETED: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    return "❌ FAILED: Max steps reached."
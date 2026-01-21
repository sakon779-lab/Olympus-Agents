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

# ✅ Core Tools
from core.tools.file_ops import read_file, write_file, append_file, list_files
from core.tools.cmd_ops import run_command
from core.tools.jira_ops import read_jira_ticket
from core.tools.git_ops import git_commit, git_push, create_pr, git_setup_workspace

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Artemis] %(message)s')
logger = logging.getLogger("ArtemisAgent")

# ==============================================================================
# 📍 CONFIGURATION
# ==============================================================================
AGENT_WORKSPACE = os.getcwd()
QA_REPO_URL = "https://github.com/sakon779-lab/qa-automation-repo.git"


# ==============================================================================
# 🛠️ AGENT SPECIFIC TOOLS
# ==============================================================================

def init_workspace_wrapper(branch_name: str, base_branch: str = "main") -> str:
    """Wrapper เพื่อเรียก Core Tool โดยส่งค่า Config ของ Agent เข้าไป"""
    logger.info(f"📂 Setting up workspace for branch: {branch_name}")

    # ✅ ส่ง Identity ของ Artemis เข้าไปตรงนี้
    return git_setup_workspace(
        repo_url=QA_REPO_URL,
        branch_name=branch_name,
        base_branch=base_branch,
        cwd=AGENT_WORKSPACE,
        git_username="Artemis QA",
        git_email="artemis@olympus.ai"
    )


def run_robot_test(file_path: str) -> str:
    """(QA Specific) รัน Robot Framework"""
    try:
        full_path = os.path.join(AGENT_WORKSPACE, file_path)
        if not os.path.exists(full_path): return f"❌ Error: Test file '{file_path}' not found."

        results_dir = os.path.join(AGENT_WORKSPACE, "results")
        os.makedirs(results_dir, exist_ok=True)

        command = [sys.executable, "-m", "robot", "-d", "results", full_path]
        logger.info(f"🤖 Running Robot Test: {file_path}...")

        env = os.environ.copy()
        env["PYTHONPATH"] = AGENT_WORKSPACE + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(command, cwd=AGENT_WORKSPACE, env=env, capture_output=True, text=True)
        output = result.stdout + "\n" + result.stderr

        if result.returncode == 0:
            return f"✅ ROBOT PASSED:\n{output}"
        else:
            return f"❌ ROBOT FAILED:\n{output}\n\n👉 INSTRUCTION: Analyze the failure logs and fix the .robot file."
    except Exception as e:
        return f"❌ Execution Error: {e}"


def install_package_wrapper(package_name: str) -> str:
    return run_command(f"{sys.executable} -m pip install {package_name}")


# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    # Core Tools
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "list_files": list_files,
    "read_jira_ticket": read_jira_ticket,
    "run_shell_command": run_command,
    "git_commit": git_commit,
    "git_push": git_push,
    "create_pr": create_pr,

    # Local Wrapper & Specific Tools
    "init_workspace": init_workspace_wrapper,
    "run_robot_test": run_robot_test,
    "install_package": install_package_wrapper
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name not in TOOLS: return f"Error: Unknown tool '{tool_name}'"
    try:
        func = TOOLS[tool_name]
        return str(func(**args))
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ==============================================================================
# 🧠 SYSTEM PROMPT (Artemis Persona - Fully Restored)
# ==============================================================================
# NOTE: Using string concatenation to prevent UI rendering issues with backticks.
SYSTEM_PROMPT = """
You are "Artemis" (formerly Gamma), a Senior QA Automation Engineer (Robot Framework Expert).
Your goal is to Create, Verify, and Deliver automated tests autonomously.

*** 🧠 IMPLICIT WORKFLOW (AUTONOMOUS MODE) ***
If the user command is simple (e.g., "Process SCRUM-24", "Do SCRUM-24"), you MUST:
1. READ the ticket.
2. INIT the workspace (using `init_workspace`).
3. EXECUTE the full "DEFINITION OF DONE" workflow (Write -> Verify -> Deliver).
DO NOT stop at analysis. DO NOT wait for more instructions.

*** 📚 ROBOT SYNTAX CHEATSHEET (CORRECT USAGE) ***
You MUST follow these patterns exactly. Do not guess arguments.
1. **Create Session**:
   ✅ `Create Session    alias_name    http://127.0.0.1:8000`
   ❌ `Create Session    http://127.0.0.1:8000` (Wrong: Missing alias)

2. **GET On Session** (Modern Keyword):
   ✅ `GET On Session    alias_name    /endpoint`
   ❌ `GET On Session    /endpoint` (Wrong: Missing alias)

3. **JSON Access**:
   ✅ `${json}=    Set Variable    ${response.json()}`
   ❌ `${json}=    Evaluate    response.json()` (Wrong: Python eval fails)

*** 🛑 STRICT ANTI-PATTERNS 🛑 ***
1. **NO RECURSION**: NEVER write a `*** Keywords ***` section that redefines `Create Session` or `GET On Session`.
2. **NO LOCALHOST**: Use `127.0.0.1`.

*** 🏁 DEFINITION OF DONE ***
1. **WRITE**: Create `.robot` file using `write_file`.
2. **VERIFY**: Run `run_robot_test`. (If fail -> Fix -> Run again).
3. **DELIVER**: `git_commit` -> `git_push` -> `create_pr`.
4. **COMPLETE**: Call `task_complete`.

*** CRITICAL: ATOMICITY & FORMAT ***
1. **ONE ACTION PER TURN**: Strictly ONE JSON block per response.
2. **NO CHAINING**: Wait for the tool result.
3. **STOP**: Stop after `}`.

*** ⚡ PRO CODING STANDARDS (CONTENT DETACHMENT) ***
1. Output the JSON Action first.
2. Immediately follow it with a **Markdown Code Block** containing the actual content.

**Format Example:**
[JSON Action]
{ "action": "write_file", "args": { "file_path": "tests/example.robot" } }

[File Content]
""" + "```" + """robot
*** Settings ***
Library    RequestsLibrary
...
""" + "```" + """

TOOLS AVAILABLE:
read_jira_ticket(issue_key), init_workspace(branch_name), list_files(directory),
read_file(file_path), write_file(file_path), append_file(file_path),
run_robot_test(file_path), git_commit(message), git_push(branch_name),
create_pr(title, body), install_package(package_name), task_complete(summary)

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
def run_artemis_task(task_description: str, max_steps: int = 30) -> str:
    logger.info(f"🚀 Starting QA Task (Artemis): {task_description}")

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

        print(f"🤖 Artemis: {content[:100]}...")

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

            if action == "init_workspace" and "❌" in result:
                return f"FAILED: {result}"

            break

        if task_finished:
            print(f"\n✅ TASK COMPLETED: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    return "❌ FAILED: Max steps reached."
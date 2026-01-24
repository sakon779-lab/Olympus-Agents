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
from core.tools.file_ops import read_file, list_files, write_file, append_file
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr
from core.tools.cmd_ops import run_command

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Artemis] %(message)s')
logger = logging.getLogger("Artemis")


# ==============================================================================
# 🛠️ AGENT SPECIFIC TOOLS
# ==============================================================================
def run_robot_test(file_path: str) -> str:
    """Executes Robot Framework tests."""
    workspace = settings.AGENT_WORKSPACE
    try:
        # Construct full path if relative
        if not os.path.isabs(file_path):
            file_path = os.path.join(workspace, file_path)

        if not os.path.exists(file_path):
            return f"❌ Error: Test file '{file_path}' not found."

        # Run robot command
        cmd = f'python -m robot -d results "{file_path}"'
        logger.info(f"⚡ Executing Robot: {cmd}")

        # Capture output (UTF-8 for Windows compatibility)
        env = os.environ.copy()
        env["PYTHONPATH"] = workspace + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(
            cmd, shell=True, cwd=workspace, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env
        )

        output = result.stdout + result.stderr
        if result.returncode == 0:
            return f"✅ Tests Passed:\n{output[:1000]}..."
        else:
            return f"❌ Tests Failed:\n{output[:1500]}..."
    except Exception as e:
        return f"❌ Execution Error: {e}"


def install_package_wrapper(package_name: str) -> str:
    return run_command(f"{sys.executable} -m pip install {package_name}")


# Tools Registry
TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "git_setup_workspace": git_setup_workspace,
    "git_commit": git_commit,
    "git_push": git_push,
    "create_pr": create_pr,
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
# 🧠 SYSTEM PROMPT (Strict Syntax + Strict Sequence)
# ==============================================================================
ROBOT_BLOCK_START = "```" + "robot"
ROBOT_BLOCK_END = "```"

SYSTEM_PROMPT = f"""
You are "Artemis", the Senior QA Automation Engineer.

*** 📚 ROBOT SYNTAX CHEATSHEET (CORRECT USAGE) ***
You MUST follow these patterns exactly. Do not guess arguments.
1. **Create Session**:
   `Create Session    api    http://127.0.0.1:8000`

2. **GET Request (Capture Response)**:
   ✅ `${{resp}}=    GET On Session    api    /hello/World`
   ❌ `GET On Session    api    /hello/World` (Wrong: Response lost)

3. **Check Status**:
   ✅ `Status Should Be    200    ${{resp}}`
   ❌ `Should Be Equal    ${{resp.status_code}}    200` (Less readable)

4. **JSON Validation**:
   `${{json}}=    Set Variable    ${{resp.json()}}`
   `Should Be Equal As Strings    ${{json['message']}}    Hello, World!`

*** 🛑 CRITICAL RULES (DO NOT IGNORE) ***
1. **ZERO KNOWLEDGE**: You DO NOT know the API requirements yet. You MUST read the CSV first.
2. **NO GUESSING**: Do not invent endpoints (like `/users`). Use ONLY what is in the CSV.
3. **SEQUENCE ENFORCEMENT**:
   - ❌ FORBIDDEN: Calling `write_file` before `read_file`.
   - ✅ REQUIRED: `git_setup_workspace` -> `read_file` -> `write_file` -> `run_robot_test`.

*** 🧠 WORKFLOW ***
1. **SETUP**: 
   - Extract `issue_key` (e.g., SCRUM-26).
   - Call `git_setup_workspace(issue_key)`.

2. **ACQUIRE SPECS (MANDATORY)**: 
   - Call `read_file("test_designs/{{issue_key}}.csv")`.
   - Wait for the content. Do NOT proceed until you see the CSV data.

3. **IMPLEMENT**: 
   - Convert the CSV data EXACTLY into Robot Framework code using the **CHEATSHEET** above.
   - `write_file("tests/{{issue_key}}.robot", content)`.

4. **VERIFY & DELIVER**: 
   - `run_robot_test("tests/{{issue_key}}.robot")`.
   - If Pass: `git_commit` -> `git_push` -> `create_pr`.

*** ⚡ CONTENT DELIVERY ***
Output Robot code in a Markdown Block AFTER the JSON.

RESPONSE FORMAT (JSON ONLY + CODE BLOCK):
{{ "action": "tool_name", "args": {{ ... }} }}
"""


# ==============================================================================
# 🧩 HELPER: PARSERS
# ==============================================================================
def extract_code_block(text: str) -> str:
    matches = re.findall(r"```robot\n(.*?)```", text, re.DOTALL)
    if matches: return matches[-1].strip()
    matches = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    for content in reversed(matches):
        cleaned = content.strip()
        if not (cleaned.startswith("{") and "action" in cleaned):
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
    return results


# ==============================================================================
# 🚀 MAIN LOOP
# ==============================================================================
def run_artemis_task(task: str, max_steps: int = 30):
    if settings.CURRENT_AGENT_NAME != "Artemis":
        logger.warning(f"⚠️ Switching Identity to 'Artemis'...")
        settings.CURRENT_AGENT_NAME = "Artemis"

    logger.info(f"🏹 Launching Artemis (The Hunter)...")
    logger.info(f"🆔 Identity: {settings.CURRENT_AGENT_NAME}")
    logger.info(f"📂 Workspace: {settings.AGENT_WORKSPACE}")

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
            logger.error(f"❌ Error querying LLM: {e}")
            return

        print(f"🤖 Artemis: {content[:100]}...")

        tool_calls = _extract_all_jsons(content)

        if not tool_calls:
            if "complete" in content.lower():
                print("ℹ️ Artemis finished thinking.")
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

            if action in ["write_file", "append_file"]:
                if "content" not in args or len(args["content"]) < 10:
                    code_content = extract_code_block(content)
                    if code_content:
                        args["content"] = code_content
                        print("📝 Extracted Code from Markdown block.")
                    else:
                        print("⚠️ Warning: No code content found.")
                        step_outputs.append("Error: content missing.")
                        continue

            logger.info(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)

            display_result = result
            if action == "write_file" and "Error" not in result:
                display_result = f"✅ File Written: {args.get('file_path')}"

            print(
                f"📄 Result: {display_result[:300]}..." if len(display_result) > 300 else f"📄 Result: {display_result}")
            step_outputs.append(f"Tool Output ({action}): {result}")
            break

        if task_finished:
            print(f"\n✅ AUTOMATION COMPLETE: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")
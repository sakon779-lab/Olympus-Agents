import json
import logging
import re
import os
import sys
import subprocess
from typing import Dict, Any, List
import core.network_fix

# ✅ Core Configuration & LLM
from core.config import settings
from core.llm_client import query_qwen

# ✅ Core Tools
from core.tools.file_ops import read_file, list_files, write_file, append_file
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr, git_pull
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

    # 1. จัดการ Path (เหมือนเดิม)
    if not os.path.isabs(file_path):
        file_path = os.path.join(workspace, file_path)

    if not os.path.exists(file_path):
        return f"❌ Error: Test file '{file_path}' not found."

    # 2. สร้าง Command (ตัด python -m ออก ให้ run_command จัดการ venv เอง)
    # หรือจะใส่ python -m robot ก็ได้ ถ้า run_command เราฉลาดพอ
    cmd = f'python -m robot -d results "{file_path}"'
    logger.info(f"⚡ Executing Robot: {cmd}")

    # 3. ✅ เรียกใช้ run_command ตัวเทพ (Timeout 10 นาที)
    # มันจะคืนค่าเป็น "✅ Command Success: ..." หรือ "❌ Command Failed..."
    output = run_command(cmd, cwd=workspace, timeout=600)

    # 4. แปลงผลลัพธ์ให้ Artemis เข้าใจง่ายๆ (ตัดคำเยิ่นเย้อ)
    # เพราะ run_command คืนค่ามาพร้อม Header เราอาจจะส่งไปทั้งดุ้นเลยก็ได้
    # หรือจะตัดแต่งนิดหน่อยตามสไตล์ Artemis
    if "Command Success" in output:
        # ตัด Header ออกนิดหน่อยเพื่อความสวยงาม (Optional)
        clean_output = output.replace("✅ Command Success:\n", "")
        return f"✅ Tests Passed:\n{clean_output[:1000]}..."
    else:
        return f"❌ Tests Failed:\n{output[:1500]}..."


def install_package_wrapper(package_name: str) -> str:
    return run_command(f"{sys.executable} -m pip install {package_name}")


TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "git_setup_workspace": git_setup_workspace,
    "git_commit": git_commit,
    "git_pull": git_pull,
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
# 🧠 SYSTEM PROMPT (ALL RULES INCLUDED)
# ==============================================================================
ROBOT_BLOCK_START = "```" + "robot"
ROBOT_BLOCK_END = "```"

SYSTEM_PROMPT = f"""
You are "Artemis", the Senior QA Automation Engineer.

*** 🚦 IMMEDIATE ACTION PROTOCOL (MUST FOLLOW) ***
1. **START**: You have NO files. You MUST call `git_setup_workspace(issue_key)` FIRST.
2. **READ**: You DO NOT know the requirements. You MUST call `read_file("test_designs/{{issue_key}}.csv")`.
3. **WAIT**: Do NOT generate any Robot code until you have read the CSV content.

*** 📚 ROBOT SYNTAX CHEATSHEET (STRICT) ***
1. **Header**: `Library    Collections` (Required).
2. **Create Session**: `Create Session    api    http://127.0.0.1:8000`
3. **GET (Normal)**: `${{resp}}=    GET On Session    api    /endpoint`
4. **GET (Negative/Error Case)**: 
   - ✅ `${{resp}}=    GET On Session    api    /bad_url    expected_status=any`
   - ⚠️ MUST use `expected_status=any` (or `404`) if expecting failure, otherwise Robot stops!
5. **Status**: `Status Should Be    404    ${{resp}}`
6. **JSON**: `${{json}}=    Set Variable    ${{resp.json()}}`
   
*** 🛑 CRITICAL RULES ***
1. **ZERO KNOWLEDGE**: Read CSV first.
2. **SEQUENCE**: `git_setup_workspace` -> `read_file` -> `write_file` -> `run_robot_test`.
3. **⛔ FIX ON FAIL**: If "❌ Tests Failed", DO NOT COMMIT. Fix code -> Run again.

*** 🚫 ANTI-PATTERNS (DO NOT USE) ***
- ❌ `Evaluate    json.loads(...)` -> **BANNED**. It causes TypeError.
- ✅ Use `Set Variable    ${{resp.json()}}` instead.

*** 📍 FILE LOCATIONS (DO NOT HALLUCINATE) ***
- **Input CSV**: `test_designs/{{issue_key}}.csv` (Look here!)
- **Output Robot**: `tests/{{issue_key}}.robot`

*** 🧠 WORKFLOW ***
1. **SETUP**: `git_setup_workspace`.
2. **SPECS**: `read_file("test_designs/{{issue_key}}.csv")`.
3. **CYCLE**: `write_file` -> `run_robot_test` (Loop until Pass).
4. **DELIVER**: `git_commit` -> `git_push` -> `create_pr` -> `task_complete`.

*** ⚡ CONTENT DELIVERY ***
**CORRECT FORMAT:**
{{ "action": "write_file", "args": {{ "file_path": "tests/SCRUM-26.robot" }} }}

*** 🛡️ ERROR HANDLING STRATEGIES (GIT) ***
- **IF `git_push` FAILS** (rejected/non-fast-forward):
  1. STOP! Do NOT create PR yet.
  2. Call `git_pull(branch_name)` to sync changes.
  3. Call `git_push(branch_name)` AGAIN to retry.
  4. Only then, proceed to `create_pr`.

{ROBOT_BLOCK_START}
*** Settings ***
Library    RequestsLibrary
Library    Collections

*** Test Cases ***
Example_Test_Case_Name    # <-- เปลี่ยนชื่อให้รู้ว่าเป็นตัวอย่าง
    [Documentation]    Generated from CSV
    Create Session    api    http://127.0.0.1:8000
    ${{resp}}=    GET On Session    api    /example/endpoint    expected_status=any
    Status Should Be    200    ${{resp}}
    ${{json}}=    Set Variable    ${{resp.json()}}
    Dictionary Should Contain Key    ${{json}}    message
    
Example_Negative_Test
    Create Session    api    http://127.0.0.1:8000
    # Use expected_status=any to prevent auto-fail on 404
    ${{resp}}=    GET On Session    api    /hello/    expected_status=any  <-- แก้ตรงนี้
    Status Should Be    404    ${{resp}}
{ROBOT_BLOCK_END}

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
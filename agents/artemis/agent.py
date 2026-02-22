import json
import logging
import re
import os
import sys
import uuid
from datetime import datetime
from typing import Dict, Any, List
import core.network_fix

# ✅ Core Configuration & LLM
from core.config import settings
from core.llm_client import query_qwen

# ✅ Core Tools (เพิ่ม DualLogger ให้เหมือน Athena ถ้าคุณมี)
from core.tools.file_ops import read_file, list_files, write_file, append_file
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr, git_pull
from core.tools.cmd_ops import run_command

# 🧠 RAG Tool (นำเข้าสมองที่เราเพิ่งสร้าง)
from knowledge_base.vector_store import search_robot_keywords

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Artemis] %(message)s')
logger = logging.getLogger("Artemis")


# ==============================================================================
# 📝 DUAL LOGGER UTILITY
# ==============================================================================
class DualLogger:
    def __init__(self, filepath):
        self.terminal = sys.stdout
        self.log = open(filepath, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


# ==============================================================================
# 🛠️ AGENT SPECIFIC TOOLS
# ==============================================================================
def run_robot_test(file_path: str) -> str:
    """Executes Robot Framework tests."""
    workspace = settings.AGENT_WORKSPACE

    if not os.path.isabs(file_path):
        file_path = os.path.join(workspace, file_path)

    if not os.path.exists(file_path):
        return f"❌ Error: Test file '{file_path}' not found."

    cmd = f'python -m robot -d results "{file_path}"'
    logger.info(f"⚡ Executing Robot: {cmd}")

    output = run_command(cmd, cwd=workspace, timeout=600)

    if "Command Success" in output:
        clean_output = output.replace("✅ Command Success:\n", "")
        return f"✅ Tests Passed:\n{clean_output[:1000]}..."
    else:
        return f"❌ Tests Failed:\n{output[:1500]}..."


def install_package_wrapper(package_name: str) -> str:
    return run_command(f"{sys.executable} -m pip install {package_name}")


# ✅ Wrapper สำหรับค้นหา RAG
def search_robot_syntax_wrapper(query: str, k: int = 5) -> str:
    """Searches the Vector DB for Robot Framework keywords and syntax."""
    return search_robot_keywords(query, k=k)


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
    "install_package": install_package_wrapper,
    "search_robot_syntax": search_robot_syntax_wrapper  # 🟢 เพิ่ม Tool นี้ให้ AI
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

# ✅ เพิ่มกฎการค้นหา Vector DB อย่างเคร่งครัด
SYSTEM_PROMPT = f"""
You are "Artemis", the Senior QA Automation Engineer.

*** 🚦 IMMEDIATE ACTION PROTOCOL (MUST FOLLOW) ***
1. **START**: You have NO files. You MUST call `git_setup_workspace(issue_key)` FIRST.
2. **READ**: You DO NOT know the requirements. You MUST call `read_file("test_designs/{{issue_key}}.csv")`.
3. **SEARCH SYNTAX (NEW & CRITICAL)**: If you need to use HTTP Requests (like POST) or JSON validations, you MUST call `search_robot_syntax` with queries like "POST request with JSON" BEFORE writing the code.
4. **WAIT**: Do NOT generate any Robot code until you have read the CSV AND searched for syntax if unsure.

*** 🛑 CRITICAL RULES ***
1. **ZERO HALLUCINATION**: DO NOT invent Robot Framework keywords. Only use keywords from your cheatsheet or from the results of `search_robot_syntax`.
2. **SEQUENCE**: `git_setup_workspace` -> `read_file` -> `search_robot_syntax` (optional) -> `write_file` -> `run_robot_test`.
3. **⛔ FIX ON FAIL**: If "❌ Tests Failed", DO NOT COMMIT. Read the error, fix the code, and run again.

*** 🚫 ANTI-PATTERNS (DO NOT USE) ***
- ❌ `Evaluate    json.loads(...)` -> **BANNED**. It causes TypeError.
- ✅ Use `Set Variable    ${{resp.json()}}` instead.
- ❌ Hallucinating fake keywords not found in the documentation.

*** 📍 FILE LOCATIONS (DO NOT HALLUCINATE) ***
- **Input CSV**: `test_designs/{{issue_key}}.csv` (Look here!)
- **Output Robot**: `tests/{{issue_key}}.robot`

*** 🧠 WORKFLOW ***
1. **SETUP**: `git_setup_workspace`.
2. **SPECS**: `read_file("test_designs/{{issue_key}}.csv")`.
3. **KNOWLEDGE**: `search_robot_syntax` (To find correct keywords).
4. **CYCLE**: `write_file` -> `run_robot_test` (Loop until Pass).
5. **DELIVER**: `git_commit` -> `git_push` -> `create_pr` -> `task_complete`.

*** 🏢 PROJECT CODING STANDARDS & GOTCHAS (STRICT) ***
While you must search for syntax using `search_robot_syntax`, you MUST strictly adhere to these project-specific rules:
1. **API Requests**: Always include `Library    RequestsLibrary` and `Library    Collections`.
2. **Negative Testing**: When expecting an error (e.g., 400, 404, 422), you MUST append `expected_status=any` to the request keyword. Otherwise, the test will abort prematurely.
   - ✅ `${{resp}}=    POST On Session    api    /url    json=${{data}}    expected_status=any`
3. **JSON Parsing**: NEVER use `Evaluate    json.loads(...)`. 
   - ✅ Always use: `${{json}}=    Set Variable    ${{resp.json()}}`
4. **JSON Value Assertions (Pattern)**: 
   - ❌ AVOID misusing `Dictionary Should Contain Value` for key-value pair checks (it causes parameter mismatch).
   - ✅ ALWAYS access dictionary values directly and use standard BuiltIn assertions: 
     `Should Be Equal As Strings    ${{your_dict}}[key_name]    expected_string`
     `Should Be Equal As Integers    ${{your_dict}}[key_name]    expected_number`
     
5. **List Comparisons (Pattern)**:
   - ❌ NEVER compare a Robot Framework list directly with a Python-style string array like `["item1"]`.
   - ❌ NEVER use `${{EMPTY}}` to check if a list is empty (it causes TypeError).
   - ✅ ALWAYS instantiate a list first using `Create List`:
     `${{expected_list}}=    Create List    item1    item2`
     `Lists Should Be Equal    ${{actual_list}}    ${{expected_list}}`
   - ✅ To check if a list is empty, ALWAYS use: `Should Be Empty    ${{actual_list}}`

*** ⚡ CONTENT DELIVERY ***
**CORRECT FORMAT:**
{{ "action": "write_file", "args": {{ "file_path": "tests/SCRUM-26.robot" }} }}

*** 🛡️ ERROR HANDLING STRATEGIES (GIT) ***
- **IF `git_push` FAILS** (rejected/non-fast-forward):
  1. STOP! Do NOT create PR yet.
  2. Call `git_pull(branch_name)` to sync changes.
  3. Call `git_push(branch_name)` AGAIN to retry.
  4. Only then, proceed to `create_pr`.

*** 🐛 DEBUGGING & TROUBLESHOOTING RULES ***
1. **Console Logging:** If a test fails and you need to inspect the actual JSON response, you MUST use `Log To Console    ${{resp.text}}`. Do NOT use `Log` because it hides output in HTML files.
2. **Tool Constraints:** When calling `run_robot_test`, ONLY provide the `file_path`. NEVER invent or add unsupported arguments like `options` or `--outputdir`.

{ROBOT_BLOCK_START}
*** Settings ***
Library    RequestsLibrary
Library    Collections

*** Test Cases ***
Example_Test_Case_Name
    [Documentation]    Generated from CSV
    Create Session    api    http://127.0.0.1:8000
    ${{resp}}=    GET On Session    api    /example/endpoint    expected_status=any
    Status Should Be    200    ${{resp}}
    ${{json}}=    Set Variable    ${{resp.json()}}
    Dictionary Should Contain Key    ${{json}}    message
    
Example_Negative_Test
    [Documentation]    Example of expecting an error response (MUST USE expected_status=any)
    Create Session    api    http://127.0.0.1:8000
    ${{payload}}=    Create Dictionary    password=123
    # ⚠️ CRITICAL: Use expected_status=any to prevent auto-fail on 4xx/5xx
    ${{resp}}=    POST On Session    api    /check-password    json=${{payload}}    expected_status=any
    Status Should Be    400    ${{resp}}
    ${{json}}=    Set Variable    ${{resp.json()}}
    Dictionary Should Contain Key    ${{json}}    detail
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
# 🚀 MAIN LOOP (อัปเกรดให้รองรับ job_id แบบ Athena)
# ==============================================================================
def run_artemis_task(task: str, job_id: str = None, max_steps: int = 30):
    if settings.CURRENT_AGENT_NAME != "Artemis":
        logger.warning(f"⚠️ Switching Identity to 'Artemis'...")
        settings.CURRENT_AGENT_NAME = "Artemis"

    if not job_id:
        job_id = f"rf_{uuid.uuid4().hex[:8]}"

    # --- 📝 Path Setup for Logs ---
    current_script_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_script_path)))
    logs_dir = os.path.join(project_root, "logs", "artemis")
    os.makedirs(logs_dir, exist_ok=True)
    log_filename = os.path.join(logs_dir, f"job_{job_id}.log")

    # --- 📝 Setup Dual Logger ---
    original_stdout = sys.stdout
    dual_logger = DualLogger(log_filename)
    sys.stdout = dual_logger

    final_result = None

    try:
        logger.info(f"\n==================================================")
        logger.info(f"🏹 Launching Artemis (The Automation Hunter)...")
        logger.info(f"▶️ [Worker] Starting Job {job_id}")
        logger.info(f"📂 Workspace: {settings.AGENT_WORKSPACE}")
        logger.info(f"📋 Task: {task}")
        logger.info(f"==================================================\n")

        history = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task}
        ]

        final_result = None

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
                return "Error: LLM Query Failed"

            print(f"🤖 Artemis: {content[:100].replace(os.linesep, ' ')}...")

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

                # ✅ ดักจับ task_complete ไม่ให้ Result เป็น None
                if action == "task_complete":
                    task_finished = True
                    result_summary = args.get("summary") or args.get("result")
                    if not result_summary:
                        result_summary = "Task completed successfully."
                    final_result = result_summary
                    step_outputs.append(f"Task Completed: {result_summary}")
                    break

                # 💉 System Injected ตัวช่วยเรื่อง Git เหมือน Athena
                if action == "git_setup_workspace":
                    args["job_id"] = job_id
                    args["agent_name"] = "Artemis"
                    print(f"💉 System Injected: agent_name='Artemis', job_id='{job_id}'")

                if action not in TOOLS:
                    step_outputs.append(f"❌ Error: Tool '{action}' not found.")
                    continue

                # ⚡ Content Detachment (ดึงโค้ดแยกจาก Markdown)
                if action in ["write_file", "append_file"]:
                    if "content" not in args or len(args.get("content", "")) < 10:
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

                # Artemis โฟกัสทีละงาน (ป้องการยิงหลายคำสั่งพร้อมกันแล้วพัง)
                break

            if task_finished:
                print(f"\n✅ TASK COMPLETE.")
                return final_result

            history.append({"role": "assistant", "content": content})
            history.append({"role": "user", "content": "\n".join(step_outputs)})

        print("❌ FAILED: Max steps reached.")
        return "Failed: Maximum steps reached."
        # --- 📝 Cleanup Dual Logger ตอนจบเสมอ ไม่ว่าจะสำเร็จหรือพัง ---

    finally:
        if 'original_stdout' in locals():
            sys.stdout = original_stdout
        if 'dual_logger' in locals():
            dual_logger.close()
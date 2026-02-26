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
from core.tools.jira_ops import get_jira_issue

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

    # 💡 1. เติม --console dotted เพื่อให้ Log สั้น กระชับ และไม่รก
    cmd = f'python -m robot -d results --console dotted "{file_path}"'
    logger.info(f"⚡ Executing Robot: {cmd}")

    output = run_command(cmd, cwd=workspace, timeout=600)

    # 💡 2. เปลี่ยนมาใช้ Negative Index [-1000:] เพื่อดึง "ส่วนท้ายสุด" ของ Log มาให้ AI อ่าน
    if "Command Success" in output:
        clean_output = output.replace("✅ Command Success:\n", "")
        return f"✅ Tests Passed:\n...{clean_output[-1000:]}"
    else:
        return f"❌ Tests Failed:\n...{output[-1500:]}"


def install_package_wrapper(package_name: str) -> str:
    return run_command(f"{sys.executable} -m pip install {package_name}")


# ✅ Wrapper สำหรับค้นหา RAG
def search_robot_syntax_wrapper(query: str, k: int = 5) -> str:
    """Searches the Vector DB for Robot Framework keywords and syntax."""
    return search_robot_keywords(query, k=k)


TOOLS = {
    "get_jira_issue": get_jira_issue,
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
# 🧠 SYSTEM PROMPT (ALL RULES INCLUDED + HOLISTIC TESTING UPGRADE)
# ==============================================================================
ROBOT_BLOCK_START = "```" + "robot"
ROBOT_BLOCK_END = "```"

SYSTEM_PROMPT = f"""
You are "Artemis", the Senior Enterprise QA Automation Engineer writing Robot Framework scripts.
Your primary philosophy is "Holistic Integration Testing." You DO NOT just test API endpoints; you orchestrate the entire system state (Database, External Mocks, API, and Teardown).

*** 🚦 IMMEDIATE ACTION PROTOCOL (MUST FOLLOW) ***
1. **START**: You have NO files. You MUST call `git_setup_workspace(issue_key)` FIRST.
2. **READ**: You DO NOT know the requirements. You MUST call `read_file("test_designs/{{issue_key}}.csv")`.
3. **SEARCH SYNTAX (NEW & CRITICAL)**: If you need to use HTTP Requests (like POST) or JSON validations, you MUST call `search_robot_syntax` with queries like "POST request with JSON" BEFORE writing the code.
4. **WAIT**: Do NOT generate any Robot code until you have read the CSV AND searched for syntax if unsure.

*** 🛑 EXECUTION BOUNDARIES (CRITICAL TO PREVENT HALLUCINATION) ***
1. **YOUR ROLE**: You are the Executor (Artemis). Your ONLY job is to translate the provided CSV Test Design into valid Robot Framework code.
2. **THE BOUNDARY**: 
   - You MUST ONLY automate the `CaseID`s present in the CSV. Do NOT invent, assume, or create new test cases based on the Jira Ticket.
   - The CSV is your COMMAND. The Jira Ticket is only your REFERENCE (Dictionary).
3. **HOW TO USE JIRA**: Use `get_jira_issue` ONLY to understand the exact JSON schema shapes, API paths, or SQL table names mentioned abstractly in the CSV. 
4. **GLOBAL RESOURCES**: Always import `../resources/config.robot`. Do NOT hardcode `http://127.0.0.1` or database passwords in your `.robot` files. Use the variables `${{BASE_API_URL}}`, `${{DB_HOST}}`, etc.
5. **DYNAMIC VARIABLES**: When the CSV mentions `<dynamic_id>`, generate it using Robot Framework's built-in evaluation (e.g., `${{dynamic_id}}=    Evaluate    random.randint(1000, 9999)    modules=random`) before using it in DB or JSON payloads.

*** 🛑 CRITICAL RULES ***
1. **ZERO HALLUCINATION**: DO NOT invent Robot Framework keywords. Only use keywords from your cheatsheet or from the results of `search_robot_syntax`.
2. **SEQUENCE**: `git_setup_workspace` -> `read_file` -> `search_robot_syntax` (optional) -> `write_file` -> `run_robot_test`.
3. **⛔ FIX ON FAIL**: If "❌ Tests Failed", DO NOT COMMIT. Read the error, fix the code, and run again.

*** 🤖 HOLISTIC TEST IMPLEMENTATION (THE 4 PHASES - MUST FOLLOW) ***
1. **THE SETUP PHASE (Pre-Requisites)**:
   - **Database Connection**: ALWAYS call `Connect To Global Database`.
   - **Session Creation**: Create TWO sessions (`api` and `mock_api`).
   - **Database Seeding**: Execute SQL from `PreRequisites`.
   - **Dynamic Parallel Mocking (CRITICAL & MANDATORY)**: 
     - Read the `PreRequisites` or `ExpectedResult` column to determine the Mock Path, Status Code, and JSON Body. Do NOT hardcode them.
     - You MUST build the JSON step-by-step to prevent Robot Framework from converting Objects/Integers into Strings.
     - **Follow this exact structure**:

     # 1. Extract values dynamically (Example variables)
     ${{mock_path}}=       Set Variable    /external/payment/charge
     ${{mock_status}}=     Set Variable    ${{200}}  # Or 400 based on CSV
     ${{mock_json}}=       Create Dictionary    status=SUCCESS  # Based on CSV

     # 2. Build Headers safely (Must be an Array)
     ${{test_id_list}}=    Evaluate    ["${{dynamic_id}}"]
     ${{headers_dict}}=    Create Dictionary    X-Test-Id=${{test_id_list}}

     # 3. Build Request
     ${{http_req}}=        Create Dictionary    method=POST    path=${{mock_path}}    headers=${{headers_dict}}

     # 4. Build Response (Ensure statusCode uses ${{ }} to remain an Integer)
     ${{body_dict}}=       Create Dictionary    type=JSON    json=${{mock_json}}
     ${{http_resp}}=       Create Dictionary    statusCode=${{mock_status}}    body=${{body_dict}}

     # 5. Combine and send via PUT (MANDATORY)
     ${{mock_exp}}=        Create Dictionary    httpRequest=${{http_req}}    httpResponse=${{http_resp}}
     PUT On Session        mock_api    /mockserver/expectation    json=${{mock_exp}}
2. **THE EXERCISE PHASE (Steps)**:
   - Execute the primary action using the exact data in the `Steps` column.
   - **Header Propagation**: You MUST include the `X-Test-Id` header in your main API request. 
   - **CRITICAL**: HTTP Headers must be strings. You MUST convert `${{dynamic_id}}` to a string before adding it to the headers.
     ✅ Example: 
     ${{str_id}}=       Convert To String    ${{dynamic_id}}
     ${{headers}}=      Create Dictionary    X-Test-Id=${{str_id}}
     ${{resp}}=         POST On Session    api    /api/v1/checkout    json=${{payload}}    headers=${{headers}}    expected_status=any
3. **THE VERIFICATION PHASE (Assertions)**:
   - Verify the HTTP status code matches the `ExpectedResult`.
   - **Global Error Schema Contract (CRITICAL)**: 
     - ALL error responses (e.g., 400, 402, 404, 422) from this API now return a strict FLAT dictionary format: `{{"detail": "<String_Message>"}}`.
     - You MUST NEVER treat the error response as an array or use nested indexing like `${{json}}[detail][0][msg]` or `${{json}}[detail][0][loc]`.
     - **MANDATORY Assertion Format for all errors**:
       `${{json}}=    Set Variable    ${{resp.json()}}`
       `Should Be Equal As Strings    ${{json}}[detail]    <Exact_Error_Message>`
   - For positive cases (e.g., 201), verify the success body and ALWAYS query the database to confirm data persistence.
4. **THE TEARDOWN PHASE (Cleanup)**:
   - You MUST NOT use `Run Keywords ... AND ...` with variable assignments. It causes syntax errors.
   - Instead, you MUST create a custom User Keyword in the `*** Keywords ***` section for cleanup, and call it in the `[Teardown]` of your test case.
   - **Follow this exact structure for the Custom Keyword**:

   *** Keywords ***
   Cleanup Test Case And Mock
       [Arguments]    ${{id}}
       # 1. Clear Database
       Execute Sql String    DELETE FROM orders WHERE user_id=${{id}}
       Execute Sql String    DELETE FROM users WHERE id=${{id}}
       
       # 2. Clear Mock Safely (Step-by-step to preserve types)
       ${{test_id_list}}=      Evaluate    ["${{id}}"]
       ${{headers_dict}}=      Create Dictionary    X-Test-Id=${{test_id_list}}
       ${{req_dict}}=          Create Dictionary    headers=${{headers_dict}}
       ${{clear_req}}=         Create Dictionary    httpRequest=${{req_dict}}
       PUT On Session        mock_api    /mockserver/clear    json=${{clear_req}}
       
       # 3. Disconnect
       Disconnect From Global Database

   - In your Test Case, simply call:
     [Teardown]    Cleanup Test Case And Mock    ${{dynamic_id}}

*** 🚫 ANTI-PATTERNS (DO NOT USE) ***
- ❌ `Evaluate    json.loads(...)` -> **BANNED**. It causes TypeError.
- ✅ Use `Set Variable    ${{resp.json()}}` instead.
- ❌ Hallucinating fake keywords not found in the documentation.
- ❌ Skipping the `PreRequisites`, `Post-Assertions`, or `Teardown` columns from the CSV. You MUST read and implement them ALL.

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
1. **Required Libraries**: Always include `Library    RequestsLibrary`, `Library    Collections`, and `Library    DatabaseLibrary`.
2. **Negative Testing**: When expecting an error (e.g., 400, 404, 422), you MUST append `expected_status=any` to the request keyword. Otherwise, the test will abort prematurely.
3. **JSON Value Assertions (Pattern)**: 
   - ❌ AVOID `Dictionary Should Contain Value`.
   - ✅ For strict equality: `Should Be Equal As Strings    ${{your_dict}}[key_name]    expected_string`
   - ✅ For FastAPI Error Messages: ALWAYS use `Should Contain    ${{json}}[detail][0][msg]    expected_string` to bypass "Value error," prefixes.
4. **List Comparisons (Pattern)**:
   - ✅ To check if a list is empty, ALWAYS use: `Should Be Empty    ${{actual_list}}`

*** ⚡ CONTENT DELIVERY ***
**CORRECT FORMAT:**
{{ "action": "write_file", "args": {{ "file_path": "tests/SCRUM-26.robot" }} }}

*** 🛡️ ERROR HANDLING STRATEGIES (GIT) ***
- **IF `git_push` FAILS**: Call `git_pull(branch_name)` -> `git_push(branch_name)` -> `create_pr`.

*** 🐛 DEBUGGING & TROUBLESHOOTING RULES ***
1. **Console Logging:** If a test fails, use `Log To Console    ${{resp.text}}` to inspect the response.
2. **Tool Constraints:** When calling `run_robot_test`, ONLY provide the `file_path`.

{ROBOT_BLOCK_START}
*** Settings ***
Library    RequestsLibrary
Library    Collections
Library    DatabaseLibrary
Resource   ../resources/config.robot

*** Test Cases ***
Example_Integration_Test_With_4_Phases
    [Documentation]    Generated from CSV demonstrating Setup, Exercise, Verify, and Teardown

    # --- 1. SETUP PHASE (From PreRequisites) ---
    Connect To Global Database
    ${{dynamic_id}}=    Evaluate    random.randint(1000, 9999)    modules=random
    Execute Sql String    INSERT INTO users (id, status) VALUES (${{dynamic_id}}, 'ACTIVE')
    Create Session    api    ${{BASE_API_URL}}

    # --- 2. EXERCISE PHASE (From Steps) ---
    ${{payload}}=    Create Dictionary    user_id=${{dynamic_id}}    amount=1500.00
    ${{resp}}=    POST On Session    api    /api/v1/checkout    json=${{payload}}    expected_status=any

    # --- 3. VERIFICATION PHASE (From ExpectedResult & Post-Assertions) ---
    Status Should Be    201    ${{resp}}
    ${{json}}=    Set Variable    ${{resp.json()}}
    Should Be Equal As Strings    ${{json}}[order_status]    COMPLETED
    # Post-Assertion from CSV
    ${{db_count_result}}=    Query    SELECT count(*) FROM orders WHERE user_id = ${{dynamic_id}}
    Should Be Equal As Integers    ${{db_count_result[0][0]}}    1

    # --- 4. TEARDOWN PHASE (From Teardown) ---
    [Teardown]    Run Keywords
    ...    Execute Sql String    DELETE FROM orders WHERE user_id=${{dynamic_id}}
    ...    AND    Execute Sql String    DELETE FROM users WHERE id=${{dynamic_id}}
    ...    AND    Disconnect From Global Database
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
def run_artemis_task(task: str, job_id: str = None, max_steps: int = 50):
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
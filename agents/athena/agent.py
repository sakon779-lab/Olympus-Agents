import sys
import json
import logging
import re
import os
import ast
import uuid
from datetime import datetime
from typing import Dict, Any, List
import core.network_fix

# ✅ Core Configuration & LLM
from core.config import settings
from core.llm_client import query_qwen

# ✅ Core Tools
from core.tools.jira_ops import get_jira_issue
from core.tools.file_ops import read_file, list_files
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr, git_pull

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Athena] %(message)s')
logger = logging.getLogger("Athena")


# ==============================================================================
# 📝 DUAL LOGGER CLASS
# ==============================================================================
class DualLogger:
    """Writes output to BOTH the terminal (stdout) and a log file simultaneously."""

    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log_file = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        self.log_file.close()


# ==============================================================================
# 🛠️ AGENT SPECIFIC TOOLS
# ==============================================================================

def save_test_design(filename: str, content: str) -> str:
    """Saves Test Scenarios (CSV) to the QA Repo."""
    try:
        if not filename.endswith('.csv'): filename += ".csv"

        # ✅ FIX 1: ใช้ path เดิมตามที่ระบุ (settings.TEST_DESIGN_DIR)
        target_dir = settings.TEST_DESIGN_DIR
        full_path = os.path.join(target_dir, filename)

        # สร้าง folder หากยังไม่มี
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Clean logic: Remove markdown code blocks
        clean_content = content.replace("```csv", "").replace("```", "").strip()

        # Remove empty lines
        lines = [line for line in clean_content.splitlines() if line.strip()]
        final_content = "\n".join(lines)

        with open(full_path, "w", encoding="utf-8", newline='') as f:
            f.write(final_content)

        return f"✅ Test Design Saved: {full_path}"
    except Exception as e:
        return f"❌ Error Saving CSV: {e}"


# ==============================================================================
# 🧩 TOOL REGISTRY & SCHEMAS (Added)
# ==============================================================================

TOOLS = {
    "get_jira_issue": get_jira_issue,
    "list_files": list_files,
    "read_file": read_file,
    "git_setup_workspace": git_setup_workspace,
    "git_commit": git_commit,
    "git_push": git_push,
    "create_pr": create_pr,
    "git_pull": git_pull,
    "save_test_design": save_test_design
}

# ✅ FIX 2: เพิ่ม Schema Verification เหมือน Hephaestus
TOOL_SCHEMAS = {
    "get_jira_issue": {
        "required": ["issue_key"],
        "description": "Fetches details of a JIRA issue."
    },
    "git_setup_workspace": {
        "required": ["issue_key"],
        "optional": ["base_branch", "agent_name", "job_id"],  # Injectable args
        "description": "Clones repo and checks out branch."
    },
    "save_test_design": {
        "required": ["filename", "content"],
        "description": "Saves CSV content to the test design folder."
    },
    "git_commit": {
        "required": ["message"],
        "description": "Commits changes."
    },
    "git_push": {
        "required": [],
        "optional": ["branch_name"],
        "description": "Pushes changes to remote."
    },
    "git_pull": {
        "required": [],
        "optional": ["branch_name"],
        "description": "Pulls latest changes."
    },
    "create_pr": {
        "required": ["title"],
        "optional": ["body", "base_branch", "head_branch"],
        "description": "Creates a GitHub Pull Request."
    },
    "list_files": {
        "required": [],
        "optional": ["directory"],
        "description": "Lists files."
    },
    "read_file": {
        "required": ["file_path"],  # ใช้ชื่อ argument ให้ตรงกับ function จริง
        "description": "Reads file content."
    },
    "task_complete": {
        "required": [],
        "optional": ["summary"],
        "description": "Marks task as finished."
    }
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name not in TOOLS:
        return {"success": False, "output": f"Error: Unknown tool '{tool_name}'"}

    # ✅ Schema Validation Logic
    if tool_name in TOOL_SCHEMAS:
        schema = TOOL_SCHEMAS[tool_name]
        valid_keys = set(schema.get("required", []))
        if "optional" in schema:
            valid_keys.update(schema["optional"])

        # Check unknown args
        unknown_args = set(args.keys()) - valid_keys
        if unknown_args:
            return {
                "success": False,
                "output": f"[ERROR] Invalid arguments: {list(unknown_args)}. Allowed: {list(valid_keys)}"
            }

        # Check missing args
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
# 🧠 SYSTEM PROMPT (Athena V2 - Enterprise Standard)
# ==============================================================================
CSV_BLOCK_START = "```" + "csv"
CSV_BLOCK_END = "```"

SYSTEM_PROMPT = f"""
You are "Athena", the Senior QA Architect.
Your goal is to design Data-Driven Test Cases (CSV) based on Jira Requirements.
You must act as a "Fat Planner" - your test designs must be highly technical, explicit, and ready for a "Thin Executor" (Automation Agent) to implement without guessing.

*** 🛑 CORE PHILOSOPHY & TECHNICAL DEPTH (CRITICAL) ***
1. **SOURCE OF TRUTH**: The Jira Ticket (Markdown) is the ONLY truth.
   - If Jira says "Return 400", you MUST expect 400. (Do NOT assume 404).

2. **EXPLICIT PRE-REQUISITES (NO ABSTRACTION)**:
   - Do NOT use vague English summaries. Extract exact technical details.
   - You MUST use `<dynamic_id>` for unique identifiers (e.g., user_id) to support parallel testing.
   - Prefix database queries with "Execute SQL:".
   - ✅ GOOD: "Execute SQL: INSERT INTO users (id, status) VALUES (<dynamic_id>, 'ACTIVE'); Mock POST /external/payment/charge to return HTTP 200 with JSON {{'status': 'SUCCESS', 'txn_id': 'mock_txn_888'}}"

3. **EXPLICIT STEPS**:
   - Provide the exact HTTP method, path, and JSON payload.
   - ✅ GOOD: "Call POST /api/v1/checkout with JSON {{'user_id': <dynamic_id>, 'product_id': 'PROD-01', 'amount': 1500.00}}"

4. **EXPECTED RESULTS & GLOBAL ERROR SCHEMA (CRITICAL)**:
   - Do NOT summarize responses. Provide exact HTTP status codes and JSON.
   - **FLAT ERROR CONTRACT**: ALL negative test cases (400, 402, 404, 422) MUST expect a strict FLAT dictionary. NEVER use arrays like `[{{'loc': ...}}]`.
   - ✅ GOOD (Success): HTTP 201 Created. JSON contains {{'order_status': 'COMPLETED'}}
   - ✅ GOOD (Error): HTTP 400 Bad Request. JSON contains {{'detail': 'amount is required'}}

5. **POST-ASSERTIONS & TEARDOWN (MANDATORY)**:
   - EVERY test must verify database states in `Post-Assertions` and clean up in `Teardown`.
   - ✅ Post-Assertions: Execute SQL: SELECT count(*) FROM orders WHERE user_id = <dynamic_id> -> Expected: 1
   - ✅ Teardown: Execute SQL: DELETE FROM orders WHERE user_id = <dynamic_id>; DELETE FROM users WHERE id = <dynamic_id>;

6. **JSON FORMATTING IN CSV**:
   - Since CSV uses double quotes (`"`) for encapsulation, you MUST use single quotes (`'`) for JSON inside the CSV columns.
   - Example: `{{'status': 'SUCCESS'}}` instead of `{{"status": "SUCCESS"}}`

7. **CSV FORMATTING (CRITICAL)**:
   - You MUST generate EXACTLY these 8 columns: `CaseID,TestType,Description,PreRequisites,Steps,ExpectedResult,Post-Assertions,Teardown`
   - If any column content contains commas (`,`), you MUST wrap the ENTIRE column in double quotes `""`.
   - ✅ GOOD: ..., "Mock POST /api to return HTTP 200 with JSON {{'status': 'SUCCESS', 'id': '88'}}", ...  

*** 🛠️ TOOL SIGNATURES (STRICT) ***
You MUST use these exact argument names:
1. `get_jira_issue(issue_key)`
2. `git_setup_workspace(issue_key)`
3. `save_test_design(filename, content)`
4. `git_commit(message)`
5. `git_push(branch_name)`
6. `create_pr(title, body)`
7. `git_pull(branch_name)` (Use if push fails)

*** ⚡ CONTENT DELIVERY RULE (CRITICAL) ***
When calling `save_test_design`, do NOT put the CSV inside the JSON.
Instead, output a Markdown Code Block tagged with `csv` AFTER the JSON.

**CORRECT FORMAT:**
{{ "action": "save_test_design", "args": {{ "filename": "SCRUM-30.csv" }} }}

{CSV_BLOCK_START}
CaseID,TestType,Description,PreRequisites,Steps,ExpectedResult,Post-Assertions,Teardown
TC-001,Positive,Verify API,"Mock POST ...", "Call GET ...",HTTP 200 OK,"Execute SQL: ...","Execute SQL: ..."
{CSV_BLOCK_END}

*** 🛡️ ERROR HANDLING STRATEGIES (GIT) ***
- **IF `git_push` FAILS** (rejected/non-fast-forward):
  1. STOP! Do NOT create PR yet.
  2. Call `git_pull(branch_name)` to sync changes.
  3. Call `git_push(branch_name)` AGAIN to retry.
  4. Only then, proceed to `create_pr`.

*** ⚡ WORKFLOW (STRICT ORDER) ***
1. `get_jira_issue` -> Wait for result.
2. `git_setup_workspace` -> Wait for result.
3. `save_test_design` (MUST include CSV block) -> Wait for result.
4. `git_commit` -> Wait for result.
5. `git_push` -> Wait for result.
6. `create_pr` -> Wait for result.
7. `task_complete`.

RESPONSE FORMAT (JSON ONLY + MARKDOWN BLOCK):
{{ "action": "tool_name", "args": {{ ... }} }}
"""


# ==============================================================================
# 🧩 HELPER: ROBUST PARSERS
# ==============================================================================

def sanitize_json_input(raw_text):
    """Cleans up the LLM response to ensure valid JSON."""
    clean_text = re.sub(r'^```json\s*', '', raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r'^```\s*', '', clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r'```$', '', clean_text, flags=re.MULTILINE)

    def fix_triple_quotes(match):
        content = match.group(1).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{content}"'

    clean_text = re.sub(r'"""(.*?)"""', fix_triple_quotes, clean_text, flags=re.DOTALL)

    clean_text = clean_text.strip()

    # Python Dict -> JSON Auto-Fix
    try:
        py_compatible_text = clean_text.replace("true", "True").replace("false", "False").replace("null", "None")
        parsed = ast.literal_eval(py_compatible_text)
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed)
    except Exception:
        pass

    return clean_text


def extract_csv_block(text: str) -> str:
    """Extract CSV content precisely."""
    csv_matches = re.findall(r"```csv\n(.*?)```", text, re.DOTALL)
    if csv_matches:
        return csv_matches[-1].strip()

    matches = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    for content in reversed(matches):
        cleaned = content.strip()
        if not (cleaned.startswith("{") and "action" in cleaned):
            return cleaned
    return ""


def _extract_all_jsons(text: str) -> List[Dict[str, Any]]:
    """Robust JSON extraction including Python Dict fallback."""
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
# 🚀 MAIN LOOP (Athena Version)
# ==============================================================================
def run_athena_task(task: str, job_id: str = None, max_steps: int = 25):
    if settings.CURRENT_AGENT_NAME != "Athena":
        settings.CURRENT_AGENT_NAME = "Athena"

    if not job_id:
        job_id = f"qa_{uuid.uuid4().hex[:8]}"

    # --- Path Setup ---
    current_script_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_script_path)))
    logs_dir = os.path.join(project_root, "logs", "athena")
    os.makedirs(logs_dir, exist_ok=True)
    log_filename = os.path.join(logs_dir, f"job_{job_id}.log")

    # Setup Dual Logger
    original_stdout = sys.stdout
    dual_logger = DualLogger(log_filename)
    sys.stdout = dual_logger

    final_result = None  # สำหรับเก็บผลลัพธ์สุดท้ายส่งคืน Worker

    try:
        print(f"\n==================================================")
        print(f"🦉 Launching Athena (Test Architect)...")
        print(f"▶️ [Worker] Starting Job {job_id}")
        print(f"📅 Time: {datetime.now()}")
        print(f"📋 Task: {task}")
        print(f"📁 Log File: {os.path.abspath(log_filename)}")
        print(f"==================================================\n")

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
                return "Error: LLM Query Failed"

            print(f"🤖 Athena: {content[:100].replace(os.linesep, ' ')}...")

            # Clean and Extract
            content_cleaned = sanitize_json_input(content)
            tool_calls = _extract_all_jsons(content_cleaned)

            if not tool_calls:
                if "complete" in content.lower() or "completed" in content.lower():
                    print("ℹ️ Athena likely finished thinking without explicit tool call.")
                history.append({"role": "assistant", "content": content})
                continue

            step_outputs = []
            task_finished = False

            # Execute Tools
            for tool_call in tool_calls:
                action = tool_call.get("action")
                args = tool_call.get("args", {})

                # ✅ แก้ไขจุดที่ทำให้ Result เป็น None
                if action == "task_complete":
                    task_finished = True
                    # ถ้า AI ส่ง args ว่างมา ให้พยายามดึง content ก่อนหน้ามาเป็น summary
                    result_summary = args.get("summary") or args.get("result")
                    if not result_summary:
                        result_summary = "Task completed successfully (No explicit summary provided)."

                    final_result = result_summary
                    step_outputs.append(f"Task Completed: {result_summary}")
                    break

                # --- 💉 MIDDLEWARE INJECTION (System Overrides) ---
                if action == "git_setup_workspace":
                    args["job_id"] = job_id
                    current_agent = getattr(settings, "CURRENT_AGENT_NAME", "Athena")
                    args["agent_name"] = current_agent
                    print(f"💉 System Injected: agent_name='{current_agent}', job_id='{job_id}'")

                # ⚡ Content Detachment Logic (CSV Stitching)
                if action == "save_test_design":
                    if "content" not in args or len(args.get("content", "")) < 10:
                        csv_content = extract_csv_block(content)
                        if csv_content:
                            args["content"] = csv_content
                            print("📝 Extracted CSV from Markdown block.")
                        else:
                            print("⚠️ Warning: No CSV content found in markdown.")
                            step_outputs.append("Error: CSV content missing from Markdown block.")
                            continue

                print(f"🔧 Executing: {action}")

                # Execute with Schema Validation
                res_data = execute_tool_dynamic(action, args)
                result_for_ai = res_data["output"]

                print(f"📄 Result: {str(result_for_ai)[:300]}...")
                step_outputs.append(f"Tool Output ({action}): {result_for_ai}")

                # Athena usually does 1 thing at a time
                break

            if task_finished:
                print(f"\n✅ TASK COMPLETE.")  # 🟢 เปลี่ยนตามที่ขอ
                return final_result  # 🟢 คืนค่าออกไปให้ Worker เก็บลง JOBS

            history.append({"role": "assistant", "content": content})
            history.append({"role": "user", "content": "\n".join(step_outputs)})

        print("❌ FAILED: Max steps reached.")
        return "Failed: Maximum steps reached."

    finally:
        if 'original_stdout' in locals():
            sys.stdout = original_stdout
        if 'dual_logger' in locals():
            dual_logger.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_athena_task(sys.argv[1])
    else:
        run_athena_task("Design QA for SCRUM-29")
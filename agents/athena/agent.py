import json
import logging
import re
import os
import sys
import ast
from typing import Dict, Any, List

# ✅ Core Configuration & LLM
from core.config import settings
from core.llm_client import query_qwen

# ✅ Core Tools (ใช้ตัวใหม่)
from core.tools.jira_ops import get_jira_issue
from core.tools.file_ops import read_file, list_files
from core.tools.git_ops import git_setup_workspace, git_commit, git_push, create_pr, git_pull

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Athena] %(message)s')
logger = logging.getLogger("Athena")


# ==============================================================================
# 🛠️ AGENT SPECIFIC TOOLS
# ==============================================================================

def save_test_design(filename: str, content: str) -> str:
    """Saves Test Scenarios (CSV) to the QA Repo."""
    try:
        if not filename.endswith('.csv'): filename += ".csv"
        # ใช้ Path จาก settings หรือจะใช้ workspace ก็ได้ แต่แยก folder ไว้ก็ดี
        target_dir = settings.TEST_DESIGN_DIR
        full_path = os.path.join(target_dir, filename)

        # ตรวจสอบว่า target_dir อยู่ใน workspace หรือไม่ ถ้าไม่ อาจต้องปรับ path
        # กรณีนี้สมมติว่า TEST_DESIGN_DIR ถูก set ไว้ถูกต้องใน config แล้ว
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


TOOLS = {
    "get_jira_issue": get_jira_issue,
    "list_files": list_files,
    "read_file": read_file,
    "git_setup_workspace": git_setup_workspace,
    "git_commit": git_commit,
    "git_push": git_push,
    "create_pr": create_pr,
    "git_pull": git_pull,  # ✅ เพิ่ม git_pull เข้าไปใน TOOLS ด้วย เผื่อ AI เรียกใช้ตอนแก้ conflict
    "save_test_design": save_test_design
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name not in TOOLS: return f"Error: Unknown tool '{tool_name}'"
    try:
        func = TOOLS[tool_name]
        return str(func(**args))
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ==============================================================================
# 🧠 SYSTEM PROMPT (Strict Signature & Detachment)
# ==============================================================================
CSV_BLOCK_START = "```" + "csv"
CSV_BLOCK_END = "```"

SYSTEM_PROMPT = f"""
You are "Athena", the Senior QA Lead.
Your goal is to design Data-Driven Test Cases (CSV) based on Jira Requirements.

*** 🛑 CORE PHILOSOPHY (DO NOT IGNORE) ***
1. **SOURCE OF TRUTH**: The Jira Ticket (Markdown) is the ONLY truth.
   - If Jira says "Return 400", you MUST expect 400. (Do NOT assume 404).
   - **Suppress your AI bias**: Do not use "Standard HTTP behavior" if the Requirement says otherwise.

2. **STATUS CODE EXTRACTION**:
   - Before designing, SCAN the requirement for HTTP Status Codes (200, 400, 404, 500).
   - Use these EXACT codes in your `ExpectedResult`.

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
{{ "action": "save_test_design", "args": {{ "filename": "SCRUM-26.csv" }} }}

{CSV_BLOCK_START}
CaseID, TestType, Description, PreRequisites, Steps, ExpectedResult
TC-001, Positive, Verify API, Mock: None, Call GET /api, 200 OK
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
def extract_code_block(text: str) -> str:
    """Extract CSV content precisely."""
    # 1. Look for explicit CSV tag
    csv_matches = re.findall(r"```csv\n(.*?)```", text, re.DOTALL)
    if csv_matches:
        return csv_matches[-1].strip()

    # 2. Fallback: Find any non-JSON block
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

    # ✅ Robust Fallback: Handle Python dicts (Single quotes)
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
def run_athena_task(task: str, max_steps: int = 20):
    # Enforce Identity
    if settings.CURRENT_AGENT_NAME != "Athena":
        settings.CURRENT_AGENT_NAME = "Athena"

    print(f"🦉 Launching Athena (Test Architect)...")
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

        print(f"🤖 Athena: {content[:100]}...")

        tool_calls = _extract_all_jsons(content)

        if not tool_calls:
            if "complete" in content.lower():
                print("ℹ️ Athena finished thinking.")
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

            # ⚡ Content Detachment Logic (Stitching)
            if action == "save_test_design":
                if "content" not in args or len(args["content"]) < 10:
                    csv_content = extract_code_block(content)
                    if csv_content:
                        args["content"] = csv_content
                        print("📝 Extracted CSV from Markdown block.")
                    else:
                        print("⚠️ Warning: No CSV content found.")
                        step_outputs.append("Error: CSV content missing from Markdown block.")
                        continue

            print(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)

            display_result = result
            if action == "save_test_design":
                display_result = f"✅ CSV Saved: {args.get('filename')}"

            print(
                f"📄 Result: {display_result[:300]}..." if len(display_result) > 300 else f"📄 Result: {display_result}")
            step_outputs.append(f"Tool Output ({action}): {result}")
            break

        if task_finished:
            print(f"\n✅ DESIGN COMPLETE: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_athena_task(sys.argv[1])
    else:
        run_athena_task("Design QA for SCRUM-29")
import json
import logging
import re
import os
import sys
import ast
from typing import Dict, Any, List

# ✅ Core Modules
from core.llm_client import query_qwen
from core.config import TEST_DESIGN_DIR

# ✅ Core Tools (Import จากส่วนกลาง)
from core.tools.jira_ops import read_jira_ticket

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Athena] %(message)s')
logger = logging.getLogger("AthenaAgent")


# ==============================================================================
# 🛠️ AGENT SPECIFIC TOOLS (Athena Skills)
# ==============================================================================

def save_test_design(filename: str, content: str) -> str:
    """
    บันทึก Test Scenarios (CSV) ลงในโฟลเดอร์กลาง (test_designs)
    หมายเหตุ: ฟังก์ชันนี้เฉพาะตัวของ Athena เพราะต้องจัดการเรื่อง path และนามสกุลไฟล์ CSV
    """
    try:
        # Ensure extension
        if not filename.endswith('.csv'):
            filename += ".csv"

        # Save to centralized folder (TEST_DESIGN_DIR from core.config)
        full_path = os.path.join(TEST_DESIGN_DIR, filename)

        # Create dir if not exists (Safety check)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Clean Markdown Code Block (ลบ ```csv และ ``` ออก)
        # รองรับทั้ง ```csv และ ``` เฉยๆ
        clean_content = content.replace("```csv", "").replace("```", "").strip()

        with open(full_path, "w", encoding="utf-8", newline='') as f:
            f.write(clean_content)

        return f"✅ Test Design Saved: {full_path}"
    except Exception as e:
        return f"❌ Error Saving CSV: {e}"


# 📋 Tools Registry
TOOLS = {
    "read_jira_ticket": read_jira_ticket,  # ✅ ใช้ของ Core
    "save_test_design": save_test_design  # ✅ ใช้ของ Local
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name not in TOOLS: return f"Error: Unknown tool '{tool_name}'"
    try:
        func = TOOLS[tool_name]
        return str(func(**args))
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ==============================================================================
# 🧠 SYSTEM PROMPT (Athena - Ultimate Edition + Content Detachment)
# ==============================================================================
SYSTEM_PROMPT = """
You are "Athena", a Senior QA Lead & Test Architect.
Your goal is to design comprehensive Test Cases based on Jira Requirements.

*** 🚫 ROLE CONSTRAINTS ***
1. **NO CODING**: You do NOT write Robot Framework code. You write English Test Cases.
2. **OUTPUT**: You ONLY produce CSV files (Test Matrices).

*** 🧠 TEST DESIGN STRATEGY ***
1. **Analyze**: Read the Jira ticket deeply. Understand the Business Logic.
2. **Design**: Apply testing techniques:
   - **Positive Cases**: Happy paths (Success scenarios).
   - **Negative Cases**: Error handling, Validation checks (Fail scenarios).
   - **Boundary Analysis**: Min/Max values.
   - **Security**: Auth checks (if applicable).
3. **Format**: Create a CSV with these exact headers:
   `CaseID, TestType, Description, PreCondition, Steps, ExpectedResult`

*** ⚡ WORKFLOW (AUTONOMOUS) ***
If user says "Design for SCRUM-24", you MUST:
1. Call `read_jira_ticket("SCRUM-24")`.
2. Think and generate the CSV content.
3. Call `save_test_design` with filename "SCRUM-24.csv".
4. Call `task_complete`.

*** CRITICAL: ATOMICITY ***
1. **ONE ACTION PER TURN**: Strictly ONE JSON block per response.
2. **NO CHAINING**: Wait for the tool result.
3. **STOP**: Stop after `}`.

*** ⚡ CONTENT DETACHMENT (CRITICAL FOR CSV) ***
When using `save_test_design`, DO NOT put the CSV content inside the JSON `args`.
1. Output the JSON Action first.
2. Immediately follow it with a **Markdown Code Block** containing the actual CSV content.

**Format Example:**
[JSON Action]
{ "action": "save_test_design", "args": { "filename": "SCRUM-24.csv" } }

[File Content]
""" + "```" + """csv
CaseID, TestType, Description, ...
TC-001, Positive, Verify login success, ...
""" + "```" + """

TOOLS AVAILABLE:
read_jira_ticket(issue_key), save_test_design(filename), task_complete(summary)

RESPONSE FORMAT (JSON ONLY + CODE BLOCK):
{ "action": "tool_name", "args": { ... } }
"""


# ==============================================================================
# 🧩 HELPER: PARSERS (Standardized with Hephaestus)
# ==============================================================================
def extract_code_block(text: str) -> str:
    """ดึง Content จาก Markdown block สุดท้ายที่ไม่ใช่ JSON"""
    matches = re.findall(r"```\w*\n(.*?)```", text, re.DOTALL)
    if not matches: return ""
    for content in reversed(matches):
        cleaned = content.strip()
        # เช็คว่าไม่ใช่ JSON Action
        if not ('"action":' in cleaned and '"args":' in cleaned):
            return cleaned
    return ""


def _extract_all_jsons(text: str) -> List[Dict[str, Any]]:
    """ดึง JSON Action อย่างแม่นยำ (รองรับ Python dict string ด้วย)"""
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
def run_athena_task(task: str, max_steps: int = 10):
    print(f"🏛️ Launching Athena (Test Designer)...")
    print(f"📋 Task: {task}")

    history = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task}
    ]

    for step in range(max_steps):
        print(f"\n🔄 Thinking (Step {step + 1})...")
        try:
            # 1. เรียก LLM
            response = query_qwen(history)

            # ✅ 2. (FIX) Handle Response Type (Dict vs String)
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
            # Fallback for thought-only responses
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

            # Handle CSV Content from Markdown (Content Detachment)
            if action == "save_test_design":
                csv_content = extract_code_block(content)
                if csv_content:
                    args["content"] = csv_content
                elif "content" not in args:
                    step_outputs.append("❌ Error: CSV content missing in Markdown block.")
                    continue

            print(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)
            print(f"📄 Result: {result}")
            step_outputs.append(f"Tool Output ({action}): {result}")

            # Strict Atomicity
            break

        if task_finished:
            print(f"\n✅ DESIGN COMPLETE: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")
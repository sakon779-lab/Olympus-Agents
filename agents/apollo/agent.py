import json
import logging
import re
import os
import sys
import ast  # ✅ [FIX 1] เพิ่ม import ast
from typing import Dict, Any, List


# ✅ Core Modules
from core.llm_client import query_qwen, get_langchain_llm
from core.config import settings

# ✅ Core Tools (Knowledge Only)
from core.tools.jira_ops import get_jira_issue
from core.tools.knowledge_ops import save_knowledge, get_knowledge_from_sql

# ✅ Knowledge Base Integration (Vector Store)
from knowledge_base.vector_store import search_vector_db

# ✅ LangChain & SQL Agent (สำหรับวิเคราะห์ Database จริง)
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Apollo] %(message)s')
logger = logging.getLogger("ApolloAgent")
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# ==============================================================================
# 🔌 DATABASE CONNECTION (PostgreSQL - Application DB)
# ==============================================================================
try:
    # ใช้ settings.DATABASE_URI จาก config.py
    app_db = SQLDatabase.from_uri(settings.DATABASE_URI, sample_rows_in_table_info=0)

    # ดึง LLM แบบ LangChain Object
    agent_llm = get_langchain_llm(temperature=0)

    # สร้าง SQL Agent Executor
    sql_agent_executor = create_sql_agent(
        llm=agent_llm,
        db=app_db,
        agent_type="zero-shot-react-description",
        # verbose=True, # 👈 แก้เป็น True สำหรับ run ผ่าน console
        verbose=False,  # 👈 แก้เป็น False (สำคัญมากสำหรับ MCP)
        handle_parsing_errors=True  # <-- เพิ่มอันนี้ช่วยกัน error
    )
    SQL_ANALYST_ACTIVE = True
    logger.info(f"✅ SQL Analyst: Connected to DB at {settings.DB_HOST}")
except Exception as e:
    logger.error(f"❌ SQL Analyst: Connection Failed - {e}")
    SQL_ANALYST_ACTIVE = False

# ==============================================================================
# 🛠️ APOLLO SPECIFIC TOOLS
# ==============================================================================
def ask_database_analyst(question: str) -> str:
    """
    Expert on Data & Statistics.
    """
    if not SQL_ANALYST_ACTIVE:
        return "❌ Error: Cannot connect to the application database."

    logger.info(f"📊 Analyst querying: {question}")
    try:
        # ✅ DYNAMIC PROMPT: ไม่ระบุชื่อตาราง ไม่ระบุคำสั่ง (Count)
        # ปล่อยให้ Agent ใช้สมองเลือกเองตามสถานการณ์
        forced_prompt = (
            f"Role: You are an Intelligent SQL Data Analyst.\n"
            f"Goal: Answer the user's question accurately using the PostgreSQL database.\n\n"

            f"🧠 THINKING PROTOCOL (Must follow):\n"
            f"1. **Analyze Intent**: Does the user want to Count? List? Sum? or Check details?\n"
            f"2. **Identify Table**: Look for the most relevant table based on keywords (e.g., 'tickets'->jira_knowledge, 'people'->users).\n"
            f"3. **Inspect Data (Crucial)**: If the user asks to filter by text (e.g., status, role, type), NEVER guess the value.\n"
            f"   -> Action: Run `SELECT DISTINCT column FROM table LIMIT 10` first.\n"
            f"4. **Execute Final Query**: Once you know the exact values and table, execute the specific SQL that answers the question.\n\n"

            f"Question: {question}\n\n"
            # Chain of Thought Starter: กระตุ้นให้เริ่มคิดแบบนักสืบ
            f"Let's think step by step. First, I need to identify which table contains the requested information.\n"
            f"Action:"
        )

        result = sql_agent_executor.invoke(forced_prompt)
        output = result.get('output', str(result))
        return f"📊 Database Analysis Result:\n{output}"
    except Exception as e:
        return f"❌ SQL Analyst Error: {e}"

def ask_guru(question: str) -> str:
    """
    Expert on Business Logic & Jira Tickets.
    Use this for: "What is SCRUM-26?", "Explain login logic", "How does X work?".
    NOT for: Counting or Statistics.
    """
    logger.info(f"🔎 Guru received: {question}")

    # 🎯 Layer 1: The Sniper (Exact Match via Regex)
    # หาว่าในคำถามมีรหัส Ticket ไหม (เช่น SCRUM-26, PAY-101)
    ticket_pattern = r"([A-Z]+-\d+)"
    matches = re.findall(ticket_pattern, question)

    if matches:
        # ถ้าเจอ ID ให้ดึงข้อมูลตรงๆ จาก SQL (Internal Knowledge DB)
        # วิธีนี้แม่นยำกว่า Vector Search มาก
        logger.info(f"🎯 Direct Lookup IDs: {matches}")
        results = []
        for ticket_key in matches:
            data = get_knowledge_from_sql(ticket_key)  # ฟังก์ชันเดิมที่คุณมี
            if data:
                results.append(f"📄 Ticket {ticket_key}:\n{data}")

        if results:
            return "\n---\n".join(results)

    # 📚 Layer 2: The Librarian (Vector Search)
    # ถ้าไม่เจอ ID หรือหาไม่เจอ ให้ใช้ Vector Search หาด้วยความหมาย
    logger.info("🧠 Fallback to Semantic Search...")
    try:
        results = search_vector_db(question, k=4)
        if not results or "no relevant info" in results.lower():
            return "❌ No info found in knowledge base."
        return f"📚 Relevant Docs found:\n{results}"
    except Exception as e:
        return f"❌ Search Error: {e}"

# ✅ ฟังก์ชันใหม่: จัดการทุกอย่างแบบ One-Stop Service
def sync_ticket_to_knowledge_base(issue_key: str) -> str:
    """
    Orchestrate the sync process: Read Jira -> Extract Info using LLM -> Save to Vector DB
    """
    logger.info(f"🔄 Syncing Ticket: {issue_key}")

    # 1. ดึงข้อมูลครั้งเดียว (One Shot)
    ticket_data = get_jira_issue(issue_key)

    # เช็คว่า Error ไหม
    if not ticket_data.get("success"):
        return f"❌ Sync Failed: {ticket_data.get('error')}"

    # ✅ ได้ตัวแปรครบ โดยไม่ต้องยิงรอบสอง
    raw_content = ticket_data["ai_content"]  # ส่งให้ AI อ่าน
    real_status = ticket_data["status"]  # เอาไว้ Save ลง DB
    real_type = ticket_data["issue_type"]  # เอาไว้ Save ลง DB
    real_summary = ticket_data["summary"]  # เอาไว้ Save ลง DB

    # 2. ใช้สมอง (Qwen) สรุปข้อมูลให้เป็น Structured Data (เพื่อเอาไปลง DB สวยๆ)
    # เราต้อง Prompt ให้มันถอด Business Logic ออกมา
    extraction_prompt = [
        {"role": "system", "content": """
You are a Data Extractor. parsing Jira ticket content into structured JSON.
Extract the following fields strictly:
- summary: The title of the ticket.
- status: The current status (e.g., To Do, Done).
- business_logic: The core rules and requirements.
- technical_spec: API endpoints, database changes, or technical constraints.
- test_scenarios: Acceptance criteria or test cases mentioned.
- issue_type: (Story, Bug, Task).
STRICT RULES:
1. Use double quotes (") for keys and string values.
2. Escape inner quotes properly (e.g. "behavior": "Returns \\"Error\\" message").
3. Do NOT use single quotes (') for JSON strings.
4. Output JSON ONLY. No markdown, no explanations.
"""},
        {"role": "user", "content": f"Parse this ticket content:\n\n{raw_content}"}
    ]

    try:
        llm_response = query_qwen(extraction_prompt)

        # Handle Response Type
        if isinstance(llm_response, dict):
            content_text = llm_response.get('content', '') or llm_response.get('message', {}).get('content', '')
        else:
            content_text = str(llm_response)

        # 🛡️ Safety Clean: ล้าง Markdown ออกให้เกลี้ยง (กันเหนียว)
        content_text = content_text.strip()
        if content_text.startswith("```json"):
            content_text = content_text[7:]
        if content_text.endswith("```"):
            content_text = content_text[:-3]

        content_text = content_text.strip()

        # แปลงเป็น Dict
        data = json.loads(content_text)

        # 🔥 [HELPER] ฟังก์ชันช่วยแปลง Dict/List กลับเป็น String ให้ DB อ่านออก
        def safe_serialize(obj):
            if isinstance(obj, (dict, list)):
                # ensure_ascii=False เพื่อเก็บภาษาไทย/Emoji ได้ถูกต้อง ไม่เป็น \uXXXX
                return json.dumps(obj, ensure_ascii=False, indent=2)
            return str(obj) if obj else "-"

        # 3. ตอน Save ก็ใช้ข้อมูลที่ดึงมาตั้งแต่รอบแรก
        result = save_knowledge(
            issue_key=issue_key,
            summary=real_summary,  # ✅ จาก API
            status=real_status,  # ✅ จาก API
            business_logic=safe_serialize(data.get("business_logic")),
            technical_spec=safe_serialize(data.get("technical_spec")),
            test_scenarios=safe_serialize(data.get("test_scenarios")),
            issue_type=real_type  # ✅ จาก API
        )

        return f"✅ Synced {issue_key} successfully!\nDetails: {result}"

    except json.JSONDecodeError as je:
        logger.error(f"❌ JSON Error: {je} \nRaw Text: {content_text}")
        # Fallback: Save Raw Content
        # ✅ ใช้ real_summary, real_status, real_type ของจริง แม้ AI จะเอ๋อ
        save_knowledge(
            issue_key=issue_key,
            summary=f"[AI Error] {real_summary}",  # แปะป้ายบอกหน่อยว่า AI พัง แต่ยังเก็บชื่อเดิมไว้
            status=real_status,  # ✅ ใช้ของจริง
            business_logic=f"⚠️ AI Parsing Failed. Raw Content:\n{raw_content[:2000]}",  # เก็บเนื้อหาดิบไว้ debug
            technical_spec="-",
            test_scenarios="-",
            issue_type=real_type  # ✅ ใช้ของจริง
        )

        return f"⚠️ Synced {issue_key} (Metadata OK, but AI Analysis failed). Saved raw content."

    except Exception as e:
        logger.error(f"❌ General Error: {e}")
        return f"❌ Sync Failed: {e}"

# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    "ask_guru": ask_guru,             # ถามความรู้ (Docs/Jira/Internal SQL)
    "ask_database_analyst": ask_database_analyst, # ถามข้อมูลจริง (External Postgres)
    "sync_ticket": sync_ticket_to_knowledge_base
}

def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name not in TOOLS: return f"Error: Unknown tool '{tool_name}'"
    try:
        func = TOOLS[tool_name]
        return str(func(**args))
    except Exception as e:
        return f"Error executing {tool_name}: {e}"

# ==============================================================================
# 🧠 SYSTEM PROMPT
# ==============================================================================
SYSTEM_PROMPT = """
You are "Apollo", the Knowledge Guru & Data Analyst of Olympus.

*** 🧠 DECISION TREE (Follow Strictly) ***

1. **CASE: User asks for DEFINITION / LOGIC / CONTENT** 📖
   - Examples: "What is SCRUM-26?", "Explain the login flow", "Show me the requirements".
   - ✅ ACTION: Use `ask_guru(question)`.
   - (This tool handles both specific ticket IDs and general semantic search).

2. **CASE: User asks for NUMBERS / LISTS / AGGREGATION** 📊
   - Examples: "How many tickets?", "Count users", "List all tickets in To Do".
   - ✅ ACTION: Use `ask_database_analyst(question)`.
   - (This tool runs SQL queries to get exact stats).

3. **CASE: User asks to MEMORIZE / SYNC** 📥
   - Examples: "Sync SCRUM-27", "Read this ticket".
   - ✅ ACTION: `read_jira_ticket` -> `save_knowledge`.

*** ⚠️ RULES ***
- Do NOT guess. If you need stats, ask the analyst.
- If you need content, ask the guru.
- Output JSON format only.

*** ⚠️ CRITICAL RULES ***
1. **ATOMICITY**: One tool per turn. Wait for result.
2. **JSON FORMAT**: No comments. Strict JSON.
3. **PRIORITY**: Answer the question directly based on tool output.

*** 🛠️ TOOLS AVAILABLE ***
- sync_ticket(issue_key)  <-- 🟢 เพิ่มตรงนี้
- ask_guru(question)
- ask_database_analyst(question)
- task_complete(summary)

RESPONSE FORMAT (JSON ONLY):
{ "action": "tool_name", "args": { ... } }
"""


# ==============================================================================
# 🧩 HELPER: PARSERS (Standardized)
# ==============================================================================
def extract_code_block(text: str) -> str:
    """Extract content from Markdown code blocks."""
    matches = re.findall(r"```\w*\n(.*?)```", text, re.DOTALL)
    if not matches: return ""
    for content in reversed(matches):
        cleaned = content.strip()
        if not ('"action":' in cleaned and '"args":' in cleaned):
            return cleaned
    return ""


def _extract_all_jsons(text: str) -> List[Dict[str, Any]]:
    """ robust JSON extractor handling multiple blocks and python dict strings """
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
def run_apollo_task(task: str, max_steps: int = 15):
    # Set Identity for Path Handling
    if settings.CURRENT_AGENT_NAME != "Apollo":
        settings.CURRENT_AGENT_NAME = "Apollo"

    print(f"🏛️ Launching Apollo (Knowledge Guru)...")
    print(f"📋 Question/Task: {task}")

    history = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task}
    ]

    for step in range(max_steps):
        print(f"\n🔄 Thinking (Step {step + 1})...")
        try:
            response = query_qwen(history)

            # Handle Response Type (Dict vs String)
            if isinstance(response, dict):
                content = response.get('message', {}).get('content', '') or response.get('content', '')
            else:
                content = str(response)

        except Exception as e:
            print(f"❌ Error querying LLM: {e}")
            return

        print(f"🤖 Apollo: {content[:100]}...")

        tool_calls = _extract_all_jsons(content)

        if not tool_calls:
            # Check for final answer or thought
            if "task_complete" not in content and "action" not in content:
                print(f"ℹ️ Apollo Answer: {content}")
                history.append({"role": "assistant", "content": content})
            else:
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

            print(f"🔧 Executing: {action}")
            result = execute_tool_dynamic(action, args)
            print(f"📄 Result: {result[:200]}..." if len(result) > 200 else f"📄 Result: {result}")
            step_outputs.append(f"Tool Output ({action}): {result}")

            # Strict Atomicity: Execute one tool, then think again
            break

        if task_finished:
            print(f"\n✅ APOLLO RESPONSE: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")

if __name__ == "__main__":
    # Example usage for testing
    if len(sys.argv) > 1:
        run_apollo_task(sys.argv[1])
    else:
        run_apollo_task("How many users are registered?")
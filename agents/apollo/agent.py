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
from core.tools.jira_ops import read_jira_ticket
from core.tools.knowledge_ops import save_knowledge, get_knowledge_from_sql

# ✅ Knowledge Base Integration (Vector Store)
from knowledge_base.vector_store import search_vector_db

# ✅ LangChain & SQL Agent (สำหรับวิเคราะห์ Database จริง)
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Apollo] %(message)s')
logger = logging.getLogger("ApolloAgent")

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
    Use this for: "How many...", "Count...", "List all...", "Check if exists...".
    Target: Can query both 'Application DB' (Users) and 'Knowledge DB' (Jira stats).
    """
    if not SQL_ANALYST_ACTIVE:
        return "❌ Error: Cannot connect to the application database."

    logger.info(f"📊 Analyst querying: {question}")
    try:
        # ✅ FIX: ใส่ Prompt Injection เพื่อบังคับให้ข้าม Step การดู Schema นานๆ
        # สั่งให้ "เมิน" ข้อมูลตัวอย่าง และ "บังคับ" ให้เขียน Query
        forced_prompt = (
            f"Do NOT just look at the schema or sample rows. "
            f"Note: The table 'jira_knowledge' contains all Jira tickets. "
            f"Do NOT check schema or list tables repeatedly. "
            f"You MUST execute a SQL query to get the real answer. "
            f"Question: {question}"
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

# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    "read_jira_ticket": read_jira_ticket,
    "save_knowledge": save_knowledge,
    "ask_guru": ask_guru,             # ถามความรู้ (Docs/Jira/Internal SQL)
    "ask_database_analyst": ask_database_analyst # ถามข้อมูลจริง (External Postgres)
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
- read_jira_ticket(issue_key)
- save_knowledge(issue_key, summary, status, business_logic, technical_spec, test_scenarios, issue_type)
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
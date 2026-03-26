import json
import logging
import re
import os
import sys
import ast
import time
from typing import Dict, Any, List
import core.network_fix

# ✅ Core Modules (Lightweight Imports)
from core.llm_client import query_qwen
from core.config import settings
from core.tools.jira_ops import get_recently_updated_issues, get_jira_issue
from core.tools.neo4j_ops import sync_ticket_to_graph, search_code_graph, search_test_cases_by_vector, get_ticket_automation_coverage

from tools.sync_code_pipeline import run_full_sync_pipeline

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Apollo] %(message)s')
logger = logging.getLogger("ApolloAgent")
os.environ["ANONYMIZED_TELEMETRY"] = "False"


def sync_codebase_to_graph(epic_key: str = "SCRUM-32", target_directory: str = None) -> str:
    """
    Scans the codebase, updates AI summaries, and maps code to Jira tickets in Neo4j.
    """
    from core.config import settings
    from tools.sync_code_pipeline import run_full_sync_pipeline

    # 🎯 พระเอกอยู่ตรงนี้: ถ้าไม่ส่ง Path มา ให้ใช้ของ Default จาก Settings
    if not target_directory:
        target_directory = getattr(settings, 'AGENT_WORKSPACE', r"D:\Project\Olympus-Agents")

    logger.info(f"🔄 Apollo starting Codebase Sync for Epic '{epic_key}' at path: {target_directory}")

    try:
        run_full_sync_pipeline(target_directory, epic_key)
        return f" Codebase successfully synced to Knowledge Graph (Epic: {epic_key})."
    except Exception as e:
        logger.error(f" Failed to sync codebase: {e}")
        return f" Failed to sync codebase: {e}"


# Reuse Parser Logic (ดึงออกมาเป็น Global Helper)
def robust_json_parser(text: str) -> Dict[str, Any]:
    """ พยายามแกะ JSON หรือ Python Dict จาก Text ให้ได้ """
    # 1. ลองใช้ Parser ตัวเก่งของคุณ _extract_all_jsons
    extracted = _extract_all_jsons(text)
    if extracted:
        return extracted[0]  # เอาตัวแรกที่เจอ

    # 2. ถ้าไม่เจอ ลองท่าไม้ตาย clean string
    try:
        clean = text.strip()
        if clean.startswith("```json"): clean = clean[7:]
        if clean.startswith("```"): clean = clean[3:]
        if clean.endswith("```"): clean = clean[:-3]
        return json.loads(clean.strip())
    except:
        return {}


# ==============================================================================
# APOLLO SPECIFIC TOOLS
# ==============================================================================

# Global Cache สำหรับ DB Connection (แก้ปัญหา Connect บ่อย)
_CACHED_DB = None

def get_db_connection():
    global _CACHED_DB
    if _CACHED_DB is None:
        from langchain_community.utilities import SQLDatabase
        # include_tables=['users', 'tickets'] # แนะนำ: ระบุเฉพาะตารางที่จำเป็นถ้า DB ใหญ่
        _CACHED_DB = SQLDatabase.from_uri(
            settings.DATABASE_URI,
            sample_rows_in_table_info=0,
            include_tables=['jira_knowledge'] # กำหนดขอบเขตตั้งแต่ตรงนี้
        )
    return _CACHED_DB


def ask_database_analyst(question: str) -> str:
    """
    Expert on Data & Statistics.
    Queries the live application database using SQL.
    (Manual Execution with Advanced Prompting)
    """
    from langchain_community.utilities import SQLDatabase
    from core.llm_client import query_qwen
    import re

    logger.info(f" Analyst querying: {question}")

    try:
        # 1. Connect DB
        # ใส่ include_tables=['...'] ถ้าต้องการลดขนาด Schema
        app_db = get_db_connection()

        # 2. ดึง Schema
        database_schema = app_db.get_table_info()

        # 3. Setup Prompt (ตามที่คุณขอมาเป๊ะๆ)
        forced_prompt = (
            f"Role: You are an Intelligent SQL Data Analyst.\n"
            f"Goal: Answer the user's question accurately using the PostgreSQL database.\n\n"
            f" LIVE DATABASE SCHEMA:\n"
            f"{database_schema}\n\n"
            f" CRITICAL INSTRUCTIONS:\n"
            f"1. **Output**: You MUST output the SQL query in the 'Action Input' field.\n"
            f"2. **Format**: You MUST use the standard ReAct format:\n"
            f"   Thought: [Your reasoning]\n"
            f"   Action: sql_db_query\n"
            f"   Action Input: [SQL Query ONLY]\n"
            f"3. **No Chatting**: Do not start with 'Here is the query'. Start directly with 'Thought:'.\n\n"
            f"4. **NO MARKDOWN**: Do NOT wrap the SQL in ```sql ... ``` or ` ... `. \n"
            f"   - WRONG: ```sql SELECT * FROM table ``` \n"
            f"   - RIGHT: SELECT * FROM table \n\n"
            f" THINKING PROTOCOL (Must follow):\n"
            f"1. **Analyze Intent**: Does the user want to Count? List? Sum? or Check details?\n"
            f"2. **Identify Table**: Look for the most relevant table based on keywords.\n"
            f"3. **Inspect Data (Crucial)**: Run `SELECT DISTINCT column FROM table LIMIT 10` first if filtering by text.\n"
            f"4. **Execute Final Query**: Generate the specific SQL.\n\n"
            f"Question: {question}\n\n"
            f"Let's think step by step.\n"
        )

        messages = [
            {"role": "user", "content": forced_prompt}
        ]

        # 4. ให้ AI คิด (ใช้ query_qwen ที่เสถียร)
        logger.info(" Generating SQL Plan...")
        raw_response = query_qwen(messages, temperature=0.1)

        # 5. Parser: แกะ SQL ออกมาจาก ReAct Format
        # เราต้องเขียน Logic แกะเองเพราะไม่ได้ใช้ LangChain Agent Executor แล้ว
        sql_query = ""

        # พยายามหาบรรทัด Action Input:
        match = re.search(r"Action Input:\s*(.*)", raw_response, re.DOTALL | re.IGNORECASE)
        if match:
            sql_query = match.group(1).strip()
        else:
            # Fallback: ถ้าหา Action Input ไม่เจอ ให้ลองหาคำว่า SELECT
            logger.warning(" ReAct format mismatch, trying to find raw SQL...")
            sql_matches = re.findall(r"(SELECT\s.*)", raw_response, re.DOTALL | re.IGNORECASE)
            if sql_matches:
                sql_query = sql_matches[-1]  # เอาตัวสุดท้ายที่น่าจะเป็นคำตอบ
            else:
                return " Could not extract SQL from response:\n{raw_response}"

        # 6. Cleaning (เผื่อ AI ดื้อใส่ Markdown มา)
        if "```" in sql_query:
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

        # ลบ comment ท้ายบรรทัด (ถ้ามี)
        sql_query = sql_query.split(";")[0]

        logger.info(f" Executing SQL: {sql_query}")

        # 7. รัน SQL จริง
        try:
            result_str = app_db.run(sql_query)

            # จัด Format คำตอบให้สวยงาม
            final_output = (
                f" **Database Analysis Result**:\n"
                f"--------------------------------\n"
                f" **Thought**: {raw_response.split('Action')[0].replace('Thought:', '').strip()}\n"
                f" **Query**: `{sql_query}`\n"
                f" **Answer**: {result_str}"
            )
            return final_output

        except Exception as sql_err:
            return f" SQL Execution Error: {sql_err}\nQuery was: {sql_query}"

    except Exception as e:
        logger.error(f" Critical Analyst Error: {e}")
        return f" System Error: {e}"


def ask_guru(question: str) -> str:
    """
    Expert on Business Logic & Jira Tickets.
    Uses Neo4j Graph + Vector Database for contextual search.
    """
    # [LAZY LOAD]
    from core.tools.knowledge_ops import get_knowledge_from_sql
    from core.tools.neo4j_ops import search_knowledge_graph
    from core.llm_client import get_text_embedding
    import re

    logger.info(f" Guru received: {question}")

    # Layer 1: The Sniper (Exact Match via Regex)
    ticket_pattern = r"([A-Z]+-\d+)"
    matches = re.findall(ticket_pattern, question)

    if matches:
        logger.info(f" Direct Lookup IDs: {matches}")
        results = []
        for ticket_key in matches:
            data = get_knowledge_from_sql(ticket_key)
            if data:
                results.append(f" Ticket {ticket_key}:\n{data}")

        if results:
            return "\n---\n".join(results)

    # Layer 2: The Graph Librarian (Neo4j Vector Search)
    logger.info(" Fallback to Graph Semantic Search...")
    try:
        # 1. แปลงคำถามให้เป็น Vector ก่อน (ใช้ Nomic จาก Local)
        question_vector = get_text_embedding(question)
        if not question_vector:
            return " Failed to generate embedding for the question."

        # 2. ค้นหาใน Neo4j
        graph_results = search_knowledge_graph(question_vector, top_k=3)

        if " " in graph_results or not graph_results.strip():
            return " No info found in knowledge base."

        return f" Relevant Context from Graph:\n{graph_results}"

    except Exception as e:
        return f" Search Error: {e}"


def ask_tech_lead(question: str) -> str:
    """
    Expert on Source Code & Technical Dependencies.
    Uses Neo4j Graph Vector Search to find code functions and their relationships.
    """
    from core.llm_client import get_text_embedding
    logger.info(f"🔎 Tech Lead received: {question}")

    try:
        question_vector = get_text_embedding(question)
        if not question_vector:
            return "❌ Failed to generate embedding for the question."

        graph_results = search_code_graph(question_vector, question_text=question, top_k=5)

        # if "❌" in graph_results or not graph_results.strip():
        #     return "❌ No code info found in knowledge base."

        return f"💻 Relevant Code Context from Graph:\n{graph_results}"
    except Exception as e:
        return f"❌ Search Error: {e}"

# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    "ask_guru": ask_guru,
    "ask_database_analyst": ask_database_analyst,
    "ask_tech_lead": ask_tech_lead,
    "search_test_cases_by_vector": search_test_cases_by_vector,
    "get_ticket_automation_coverage": get_ticket_automation_coverage
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
   - Examples: "What is SCRUM-26?", "Explain the login flow".
   - ✅ ACTION: Use `ask_guru(question)`.

2. **CASE: User asks for NUMBERS / LISTS / AGGREGATION** 📊
   - Examples: "How many tickets?", "Count users".
   - ✅ ACTION: Use `ask_database_analyst(question)`.

3. **CASE: User asks to MEMORIZE / SYNC** 📥
   - Examples: "Sync SCRUM-27", "Read this ticket".
   - ✅ ACTION: Use `sync_ticket(issue_key)`.

4. **CASE: User wants to UPDATE/REFRESH KNOWLEDGE by TIME** 🔄
   - Examples: "Update tickets from today", "Sync last 5 hours", "Refresh knowledge base".
   - ✅ ACTION: Use `sync_recent_tickets(hours)`.

5. **CASE: User asks about SOURCE CODE / FUNCTIONS / DEPENDENCIES** 💻
   - Examples: "Which function connects to Jira?", "What calls create_dashboard?".
   - ✅ ACTION: Use `ask_tech_lead(question)`.

6. **CASE: User wants to UPDATE/SYNC CODEBASE ARCHITECTURE** 💻
   - Examples: "Sync the Payment API codebase to SCRUM-99", "อัปเดตโค้ดโฟลเดอร์นี้เข้า Epic SCRUM-45 ให้หน่อย".
   - ✅ ACTION: Use `sync_codebase_to_graph(epic_key, target_directory)`.

7. **CASE: User asks about QA, TEST CASES, or AUTOMATION COVERAGE** 🧪
   - Examples: "What is the test coverage for SCRUM-30?", "Find tests about payment failure", "หาเทสเคสเกี่ยวกับการล็อกอิน".
   - ✅ ACTION: Use `search_test_cases_by_vector(query_text)` OR `get_ticket_automation_coverage(issue_key)`.

*** ⚠️ RULES ***
- Do NOT guess. If you need stats, ask the analyst.
- If the user doesn't specify hours for "sync today" or "sync recent", assume hours=24.
- If you need content, ask the guru.
- Output JSON format only.

*** ⚠️ CRITICAL RULES ***
1. **ATOMICITY**: One tool per turn. Wait for result.
2. **JSON FORMAT**: No comments. Strict JSON.

*** 🛠️ TOOLS AVAILABLE ***
You are equipped with a hybrid architecture. You must choose the correct tool based on the user's intent:
1. `sync_ticket(issue_key)`
   - Use: When the user asks to update, ingest, or check the latest status of ONE specific Jira ticket into the Knowledge Graph.
2. `sync_recent_tickets(hours)`
   - Use: When the user asks to update the database with the latest changes, or scan for recent updates (e.g., "อัปเดตข้อมูลของวันนี้ให้หน่อย").
3. `ask_guru(question)`
   - Use: For "Contextual & Relationship" questions. 
   - Keywords: "ทำไม", "ใครทำ", "กระทบส่วนไหน", "ตั๋วไหนบล็อกอยู่", "สรุปเนื้อหา", "ความสัมพันธ์".
   - Target: Queries the Graph Database (Neo4j) and Vector Search for deep architectural context and ticket dependencies.
4. `ask_database_analyst(question)`
   - Use: STRICTLY for "Statistical & Quantitative" questions.
   - Keywords: "กี่ใบ", "รวมทั้งหมด", "สถิติ", "ความเร็ว (Velocity)", "จำนวน".
   - Target: Executes exact SQL queries via PostgREST for hard numbers and aggregations.
5. `task_complete(summary)`
   - Use: Provide the final human-readable answer after successfully retrieving data from the tools above.
6. `ask_tech_lead(question)`
   - Use: STRICTLY for queries about Source Code, Functions, Files, and Code Dependencies.
   - Keywords: "ฟังก์ชัน", "โค้ด", "ไฟล์", "เรียกใช้งาน", "code", "function", "file".
7. `search_test_cases_by_vector(query_text)`
   - Use: STRICTLY for finding QA Test Cases, Test Designs, or Robot Scripts using AI semantic search.
   - Keywords: "test case", "test script", "ทดสอบ", "เทสเคส".
8. `get_ticket_automation_coverage(issue_key)`
   - Use: STRICTLY for checking the test automation progress or coverage percentage for a specific Jira ticket.
   - Keywords: "coverage", "เปอร์เซ็นต์", "automate ไปกี่เคส".

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
            # 🌟 [FIX] เปลี่ยนกลับมาใช้ท่าปกติแบบนี้ครับ
            search = re.search(r"\{", text[pos:])
            if not search: break
            start_index = pos + search.start()
            
            obj, end_index = decoder.raw_decode(text, idx=start_index)
            if isinstance(obj, dict) and "action" in obj:
                results.append(obj)
            pos = end_index
        except:
            pos += 1

    # Fallback for Python dict strings
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
def run_apollo_task(task: str, max_steps: int = 15):
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
            break

        if task_finished:
            print(f"\n✅ APOLLO RESPONSE: {result}")
            return result

        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "\n".join(step_outputs)})

    print("❌ FAILED: Max steps reached.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_apollo_task(sys.argv[1])
    else:
        run_apollo_task("How many users are registered?")
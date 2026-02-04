import json
import logging
import re
import os
import sys
import ast
from typing import Dict, Any, List

# ✅ Core Modules (Lightweight Imports)
from core.llm_client import query_qwen
from core.config import settings

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Apollo] %(message)s')
logger = logging.getLogger("ApolloAgent")
os.environ["ANONYMIZED_TELEMETRY"] = "False"


# ==============================================================================
# 🛠️ APOLLO SPECIFIC TOOLS
# ==============================================================================

def ask_database_analyst(question: str) -> str:
    """
    Expert on Data & Statistics.
    Queries the live application database using SQL.
    """
    # 🟢 [LAZY LOAD] โหลดของหนักเฉพาะตอนใช้ เพื่อแก้ปัญหา Server Start Timeout
    from langchain_community.utilities import SQLDatabase
    from langchain_community.agent_toolkits import create_sql_agent
    from core.llm_client import get_langchain_llm

    logger.info(f"📊 Analyst querying: {question}")

    try:
        # 1. Connect DB (On Demand)
        # sample_rows_in_table_info=0 เพื่อลดเวลาโหลด Schema
        app_db = SQLDatabase.from_uri(settings.DATABASE_URI, sample_rows_in_table_info=0)

        # 2. Setup Agent
        agent_llm = get_langchain_llm(temperature=0)
        sql_agent_executor = create_sql_agent(
            llm=agent_llm,
            db=app_db,
            agent_type="zero-shot-react-description",
            verbose=False,
            handle_parsing_errors=True
        )

        # 3. Dynamic Prompt (บังคับให้คิดก่อนทำ)
        forced_prompt = (
            f"Role: You are an Intelligent SQL Data Analyst.\n"
            f"Goal: Answer the user's question accurately using the PostgreSQL database.\n\n"
            f"🧠 THINKING PROTOCOL (Must follow):\n"
            f"1. **Analyze Intent**: Does the user want to Count? List? Sum? or Check details?\n"
            f"2. **Identify Table**: Look for the most relevant table based on keywords.\n"
            f"3. **Inspect Data (Crucial)**: Run `SELECT DISTINCT column FROM table LIMIT 10` first if filtering by text.\n"
            f"4. **Execute Final Query**: Execute specific SQL.\n\n"
            f"Question: {question}\n\n"
            f"Let's think step by step.\n"
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
    Uses Vector Database and Internal Knowledge SQL.
    """
    # 🟢 [LAZY LOAD]
    from knowledge_base.vector_store import search_vector_db
    from core.tools.knowledge_ops import get_knowledge_from_sql

    logger.info(f"🔎 Guru received: {question}")

    # 🎯 Layer 1: The Sniper (Exact Match via Regex)
    ticket_pattern = r"([A-Z]+-\d+)"
    matches = re.findall(ticket_pattern, question)

    if matches:
        logger.info(f"🎯 Direct Lookup IDs: {matches}")
        results = []
        for ticket_key in matches:
            data = get_knowledge_from_sql(ticket_key)
            if data:
                results.append(f"📄 Ticket {ticket_key}:\n{data}")

        if results:
            return "\n---\n".join(results)

    # 📚 Layer 2: The Librarian (Vector Search)
    logger.info("🧠 Fallback to Semantic Search...")
    try:
        results = search_vector_db(question, k=4)
        if not results or "no relevant info" in results.lower():
            return "❌ No info found in knowledge base."
        return f"📚 Relevant Docs found:\n{results}"
    except Exception as e:
        return f"❌ Search Error: {e}"


def sync_ticket_to_knowledge_base(issue_key: str) -> str:
    """
    Orchestrate the sync process: Read Jira -> Extract Info using LLM -> Save to Vector DB
    """
    # 🟢 [LAZY LOAD]
    from core.tools.jira_ops import get_jira_issue
    from core.tools.knowledge_ops import save_knowledge

    logger.info(f"🔄 Syncing Ticket: {issue_key}")

    # 1. ดึงข้อมูลครั้งเดียว (One Shot)
    ticket_data = get_jira_issue(issue_key)

    # เช็คว่า Error ไหม
    if not ticket_data.get("success"):
        return f"❌ Sync Failed: {ticket_data.get('error')}"

    # ✅ Extract Variables
    raw_content = ticket_data["ai_content"]
    real_status = ticket_data["status"]
    real_type = ticket_data["issue_type"]
    real_summary = ticket_data["summary"]
    real_parent_key = ticket_data.get("parent_key")
    real_issue_links = ticket_data.get("issue_links")

    # 2. ใช้สมอง (Qwen) สรุปข้อมูล
    extraction_prompt = [
        {"role": "system", "content": """
You are a Data Extractor parsing Jira ticket content into structured JSON.
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

        # 🛡️ Safety Clean
        content_text = content_text.strip()
        if content_text.startswith("```json"): content_text = content_text[7:]
        if content_text.endswith("```"): content_text = content_text[:-3]
        content_text = content_text.strip()

        # แปลงเป็น Dict
        data = json.loads(content_text)

        # Helper Serialize
        def safe_serialize(obj):
            if isinstance(obj, (dict, list)):
                return json.dumps(obj, ensure_ascii=False, indent=2)
            return str(obj) if obj else "-"

        # 3. Save ลง DB
        result = save_knowledge(
            issue_key=issue_key,
            summary=real_summary,
            status=real_status,
            business_logic=safe_serialize(data.get("business_logic")),
            technical_spec=safe_serialize(data.get("technical_spec")),
            test_scenarios=safe_serialize(data.get("test_scenarios")),
            issue_type=real_type,
            parent_key=real_parent_key,  # ✅ New Field
            issue_links=real_issue_links  # ✅ New Field
        )

        return f"✅ Synced {issue_key} successfully!\nDetails: {result}"

    except json.JSONDecodeError as je:
        logger.error(f"❌ JSON Error: {je} \nRaw Text: {content_text}")
        save_knowledge(
            issue_key=issue_key,
            summary=f"[AI Error] {real_summary}",
            status=real_status,
            business_logic=f"⚠️ AI Parsing Failed. Raw Content:\n{raw_content[:2000]}",
            technical_spec="-",
            test_scenarios="-",
            issue_type=real_type,
            parent_key=real_parent_key,
            issue_links=real_issue_links
        )
        return f"⚠️ Synced {issue_key} (Metadata OK, but AI Analysis failed). Saved raw content."

    except Exception as e:
        logger.error(f"❌ General Error: {e}")
        return f"❌ Sync Failed: {e}"


# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    "ask_guru": ask_guru,
    "ask_database_analyst": ask_database_analyst,
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
   - Examples: "What is SCRUM-26?", "Explain the login flow".
   - ✅ ACTION: Use `ask_guru(question)`.

2. **CASE: User asks for NUMBERS / LISTS / AGGREGATION** 📊
   - Examples: "How many tickets?", "Count users".
   - ✅ ACTION: Use `ask_database_analyst(question)`.

3. **CASE: User asks to MEMORIZE / SYNC** 📥
   - Examples: "Sync SCRUM-27", "Read this ticket".
   - ✅ ACTION: `read_jira_ticket` -> `save_knowledge`.

*** ⚠️ RULES ***
- Do NOT guess. If you need stats, ask the analyst.
- If you need content, ask the guru.
- Output JSON format only.
   - ✅ ACTION: Use `sync_ticket(issue_key)`.

*** ⚠️ CRITICAL RULES ***
1. **ATOMICITY**: One tool per turn. Wait for result.
2. **JSON FORMAT**: No comments. Strict JSON.

*** 🛠️ TOOLS AVAILABLE ***
- sync_ticket(issue_key)
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
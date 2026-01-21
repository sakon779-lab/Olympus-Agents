import json
import logging
import re
import os
import sys
import ast
from typing import Dict, Any, List

# ✅ Core Modules
from core.llm_client import query_qwen
from core.config import JIRA_URL, JIRA_EMAIL, JIRA_TOKEN

# ✅ Core Tools (Shared Skills)
from core.tools.file_ops import read_file, list_files
from core.tools.jira_ops import read_jira_ticket
from core.tools.knowledge_ops import save_knowledge

# ✅ Knowledge Base Integration
# พยายาม Import Vector Store ถ้าไม่มีให้ใช้ Dummy Function เพื่อป้องกัน Crash
try:
    # สมมติว่าโครงสร้างโปรเจกต์คุณมี knowledge_base/vector_store.py
    sys.path.append(os.getcwd())  # Ensure root is in path
    from knowledge_base.vector_store import search_vector_db

    KNOWLEDGE_BASE_ACTIVE = True
except ImportError:
    KNOWLEDGE_BASE_ACTIVE = False


    def search_vector_db(query: str, k: int = 4) -> str:
        return "⚠️ Error: Knowledge Base module not found. Please setup 'knowledge_base/vector_store.py'."

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Apollo] %(message)s')
logger = logging.getLogger("ApolloAgent")


# ==============================================================================
# 🛠️ APOLLO SPECIFIC TOOLS (Knowledge Skills)
# ==============================================================================

def ask_guru(question: str) -> str:
    """
    Search the Knowledge Base (Vector DB) for concepts, logic, or past specs.
    Use this when user asks "How...", "What is...", or "Explain...".
    """
    logger.info(f"🔎 Guru searching for: {question}")

    if not KNOWLEDGE_BASE_ACTIVE:
        return "❌ Knowledge Base is not active. I cannot search for historical data."

    try:
        results = search_vector_db(question, k=5)
        if not results or "not found" in results.lower():
            return f"❌ I searched the database but found no relevant info about '{question}'."
        return f"📚 Knowledge Found:\n{results}"
    except Exception as e:
        return f"❌ Search Error: {e}"


def read_project_file(file_path: str) -> str:
    """
    Read the content of a specific file to understand the code logic.
    Wrapper around core read_file.
    """
    return read_file(file_path)


def inspect_project_structure(directory: str = ".") -> str:
    """
    List files in a directory to understand project layout.
    Wrapper around core list_files.
    """
    return list_files(directory)


# ==============================================================================
# 🧩 TOOLS REGISTRY
# ==============================================================================
TOOLS = {
    # Core Tools
    "read_jira_ticket": read_jira_ticket,

    # Apollo Specific Tools
    "ask_guru": ask_guru,
    "read_file": read_project_file,
    "list_files": inspect_project_structure,
    "save_knowledge": save_knowledge
}


def execute_tool_dynamic(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name not in TOOLS: return f"Error: Unknown tool '{tool_name}'"
    try:
        func = TOOLS[tool_name]
        return str(func(**args))
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


# ==============================================================================
# 🧠 SYSTEM PROMPT (Apollo Persona)
# ==============================================================================
SYSTEM_PROMPT = """
You are "Apollo", the Knowledge Guru of Olympus.
Your goal is to LEARN from Jira Tickets and ANSWER questions based on that knowledge.

*** 🧠 YOUR CAPABILITIES ***
1. **Search Knowledge**: Use `ask_guru(question)` to find technical specs, business logic, or past decisions in the Vector DB.
2. **Read Requirements**: Use `read_jira_ticket(issue_key)` to understand current tasks.
3. **Save Knowledge**: Use `save_knowledge(...)` to store insights.
4. **Analyze Code**: Use `list_files` and `read_file` to inspect the actual codebase.

*** 🔄 MODE 1: LEARNING (SYNC) ***
If user says "Sync SCRUM-26" or "Learn about SCRUM-26":
1. Call `read_jira_ticket` with argument `issue_key="SCRUM-26"`.
2. Analyze the raw text and Extract key info.
3. Call `save_knowledge` with these structured details:
   - `issue_key`: "SCRUM-26"
   - `summary`: Ticket title
   - `status`: Ticket status
   - `business_logic`: Summarize the goal and rules.
   - `technical_spec`: List APIs, DB tables, Libraries.
   - `test_scenarios`: List 3-5 key test cases.
4. Call `task_complete`.

*** 🔍 MODE 2: ANSWERING (RAG) ***
If user asks a question (e.g., "How does login work?"):
1. Call `ask_guru("How does login work?")`.
2. Read the search results.
3. Explain the answer clearly using the retrieved context.

*** CRITICAL: ATOMICITY ***
- ONE Action per turn.
- Wait for tool output before proceeding.

*** CRITICAL: JSON FORMAT RULES ***
1. **NO COMMENTS**: Do NOT use `//` or `#` inside the JSON. It breaks the parser.
2. **STRICT TYPES**: 
   - `technical_spec` and `test_scenarios` should be STRINGS (Text summaries), NOT Lists/Objects. 
   - If you want to list items, use a markdown list string (e.g., "- API: /hello\n- DB: User").

*** 🛠️ TOOLS AVAILABLE ***
- read_jira_ticket(issue_key: str)
- save_knowledge(issue_key, summary, status, issue_type, business_logic, technical_spec, test_scenarios)
- ask_guru(question)
- task_complete(summary)

RESPONSE FORMAT (JSON ONLY, NO COMMENTS):
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
                # Assume it's a direct answer if no tool is called
                print(f"ℹ️ Apollo Answer: {content}")
                history.append({"role": "assistant", "content": content})
                # You might want to break here if it looks like a final answer,
                # but usually we wait for task_complete.
                # For Apollo, sometimes just talking is the result.
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
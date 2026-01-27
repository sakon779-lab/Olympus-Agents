import json
import logging
import re
import os
import sys
from typing import Dict, Any, List

# ✅ Core Modules
from core.llm_client import query_qwen
from core.config import settings

# ✅ Core Tools (Knowledge Only)
from core.tools.jira_ops import read_jira_ticket
from core.tools.knowledge_ops import save_knowledge

# ✅ Knowledge Base Integration
# (เลือกใช้ Vector Store ตัวเทพของคุณ)
try:
    from knowledge_base.vector_store import search_vector_db
    KNOWLEDGE_BASE_ACTIVE = True
except ImportError:
    KNOWLEDGE_BASE_ACTIVE = False


# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Apollo] %(message)s')
logger = logging.getLogger("ApolloAgent")

# ==============================================================================
# 🛠️ APOLLO SPECIFIC TOOLS
# ==============================================================================
def ask_guru(question: str) -> str:
    """
    Search the Knowledge Base (Vector DB) for concepts, logic, or past specs.
    """
    logger.info(f"🔎 Guru searching for: {question}")
    if not KNOWLEDGE_BASE_ACTIVE:
        return "❌ Knowledge Base is not active."
    try:
        results = search_vector_db(question, k=4)
        if not results or "no relevant info" in results.lower():
            return f"❌ I searched the database but found no relevant info about '{question}'."
        return f"📚 Knowledge Found:\n{results}"
    except Exception as e:
        return f"❌ Search Error: {e}"

# ==============================================================================
# 🧩 TOOLS REGISTRY (เอา list_files/read_file ออกแล้ว)
# ==============================================================================
TOOLS = {
    "read_jira_ticket": read_jira_ticket,
    "ask_guru": ask_guru,
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
# 🧠 SYSTEM PROMPT (Pure Knowledge Mode)
# ==============================================================================
SYSTEM_PROMPT = """
You are "Apollo", the Knowledge Guru of Olympus.
Your goal is to LEARN from Jira Tickets and ANSWER questions based on that knowledge.

*** 🧠 YOUR CAPABILITIES ***
1. **Search**: `ask_guru(question)` to find info in Vector DB.
2. **Read**: `read_jira_ticket(issue_key)` to inspect requirements.
3. **Memorize**: `save_knowledge(...)` to store insights.

*** 🚫 LIMITATIONS ***
- You do NOT have access to the source code files. 
- You CANNOT list or read files from the repo. 
- If user asks about specific code implementation details that are not in Jira/DB, explain that you are the Knowledge Agent and they should ask Hephaestus (Dev Agent).

*** 🚦 WORKFLOW MODES (STRICT) ***

1. **MODE: SYNC / LEARN** 📥
   - **Trigger**: User says "Sync", "Learn", "Memorize", "Update knowledge".
   - **Step-by-Step**: 
     1. Call `read_jira_ticket(issue_key)`.
     2. Analyze text & Extract: Business Logic, Tech Spec, Test Scenarios.
     3. Call `save_knowledge(...)` (Convert Lists to Strings first).
     4. Call `task_complete("Synced knowledge for [Key]")`.

2. **MODE: Q&A / CONSULTING** 🗣️
   - **Trigger**: User asks "How", "What", "Explain", "Does".
   - **Step-by-Step**:
     1. **Attempt 1**: Call `ask_guru(question)`.
     2. **Decision**:
        - ✅ **IF Found**: Explain the answer clearly. Call `task_complete(answer)`.
        - ❌ **IF NOT Found**: 
          - Call `read_jira_ticket(issue_key)` (ONLY if you know the Key e.g. SCRUM-xx).
          - **CRITICAL**: If you still can't find it, admit it. Do NOT hallucinate code or paths.
          - Call `task_complete("I couldn't find info on X. Please check the Ticket ID.")`.

*** ⚠️ CRITICAL RULES ***
1. **ATOMICITY**: One tool per turn.
2. **JSON FORMAT**: No comments. Strict JSON.
3. **PRIORITY**: Answer the question directly based on retrieved info.

*** 🛠️ TOOLS AVAILABLE ***
- read_jira_ticket(issue_key)
- save_knowledge(issue_key, summary, status, business_logic, technical_spec, test_scenarios, issue_type)
- ask_guru(question)
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
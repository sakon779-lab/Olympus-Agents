import os
from typing import Literal
import langchain
import ast
import logging

# --- Debug Mode: เปิดเพื่อให้เห็นว่า Llama ส่งอะไรกลับมา (สำคัญมาก) ---
langchain.debug = True

from langchain_ollama import ChatOllama
from langchain_core.messages import (
    SystemMessage, HumanMessage, ToolMessage, AIMessage, BaseMessage # ✅ [เพิ่ม] AIMessage
)
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from graph.state import AgentState
from graph.tools.database import save_ticket_knowledge
from graph.tools.jira import get_jira_ticket

# 👇 1. Import Tools ใหม่เข้ามา
from graph.tools.file_ops import read_file, write_file, list_directory
from graph.tools.git_ops import (
    git_create_branch,
    git_commit_changes,
    git_status,
    git_push_to_remote,
    create_pull_request
)

from langchain_core.messages import AIMessage # เพิ่ม import นี้
import json

from langchain_core.messages import ToolMessage # อย่าลืม import เพิ่ม

# --- 1. Setup Brain (Ollama) & Tools ---

# Setup ให้ยิงเข้า Localhost ของเรา
# llm = ChatOllama(
#     model="llama3.1",
#     temperature=0,
#     base_url="http://localhost:11434",
#     # ✅✅✅ เพิ่มบรรทัดนี้: ขยายความจำจาก 2k เป็น 8k หรือ 16k ✅✅✅
#     num_ctx=20000,
#     # ✅✅✅ เพิ่มบรรทัดนี้: ขยายโควต้าการพูดขาออก (Output Tokens) ✅✅✅
#     num_predict=-1,   # ให้สิทธิ์พูดได้ยาวเหยียด (สูงสุดของ Model)
# )

# For DeepSeek
# llm = ChatOllama(
#     model="deepseek-r1:8b",   # 👈 แก้ตรงนี้จาก 'llama3.1' เป็นชื่อที่เพิ่งโหลดมา
#     temperature=0,
#     base_url="http://localhost:11434",
#     num_ctx=8192,
#     num_predict=-1
# )

# For QWen
llm = ChatOllama(
    model="qwen3:8b",   # ✅ เปลี่ยนเป็นตัวนี้
    temperature=0,
    base_url="http://localhost:11434",
    num_ctx=8192,
    num_predict=-1
)

# 👇 2. รวม Tools ทั้งหมด
tools = [
    get_jira_ticket,
    save_ticket_knowledge,
    read_file,
    write_file,
    list_directory,
    git_create_branch,
    git_commit_changes,
    git_status,
    git_push_to_remote,
    create_pull_request
]

# ผูก Tool เข้ากับสมอง
llm_with_tools = llm.bind_tools(tools)


# --- 2. Nodes ---

from langchain_core.messages import ToolMessage  # อย่าลืม import เพิ่ม


def agent_node(state: AgentState):
    messages = state['messages']

    tool_output_msg = next((m for m in reversed(messages) if isinstance(m, ToolMessage)), None)

    # 🔍 DEBUG: เพิ่มบรรทัดนี้เพื่อดูว่า Tool ตอบอะไรกลับมา (Error อะไร)
    if tool_output_msg:
        logging.info(f"🔧 TOOL OUTPUT (DEBUG): {tool_output_msg.content}")

    # 🛑 CHECKPOINT: ถ้า Save สำเร็จแล้ว จบงาน
    if tool_output_msg and "Successfully" in str(tool_output_msg.content):
        return {"messages": [AIMessage(content="✅ Sync Process Completed Successfully.")]}

    # 🛑 2. ถ้ามี Error (เพิ่มส่วนนี้เข้าไป!)
    if tool_output_msg and "Error saving ticket" in str(tool_output_msg.content):
        error_detail = tool_output_msg.content
        return {"messages": [AIMessage(content=f"❌ STOP: Database Save Failed.\nReason: {error_detail}")]}

    response = None

    if not tool_output_msg:
        # 🟢 PHASE 1: FETCHER
        logging.info("--- PHASE 1: FETCHING ---")
        system_prompt = """ROLE: Jira Fetcher
        INSTRUCTIONS: Retrieve raw ticket data. Call 'get_jira_ticket' immediately."""

        # ตัด System Message เก่าออก
        filtered_messages = [m for m in messages if not isinstance(m, SystemMessage)]
        phase_messages = [SystemMessage(content=system_prompt)] + filtered_messages[-1:]

        response = llm.bind_tools([get_jira_ticket], tool_choice="get_jira_ticket").invoke(phase_messages)

    else:
        # 🟠 PHASE 2: SAVER
        logging.info("--- PHASE 2: SAVING (CLEAN SLATE) ---")
        raw_data_str = tool_output_msg.content

        system_prompt = """ROLE: Senior Tech Lead & Summarizer

                TASK: Extract critical info from Jira text to 'save_ticket_knowledge'.

                ⚠️ CRITICAL RULE: YOU MUST CALL 'save_ticket_knowledge' TOOL IN EVERY CASE, EVEN IF DATA IS EMPTY.

                👇 EXTRACTION RULES:
                
                0. CLEANING DATA:
                   - ⛔ REMOVE all special characters like '', bullets (•), or emoticons.
                   - REPLACE bullets with asterisks (*).
                   - ENSURE all text is standard UTF-8 / ASCII.

                1. issue_key, summary, status, parent_key, issue_type: 
                   - Extract exactly from input.

                2. business_logic: 
                   - IF DATA EXISTS: Summarize 'Goal' and 'Key Rules' (3-5 bullets).
                   - IF EMPTY: Write "No details provided".

                3. technical_spec: 
                   - IF DATA EXISTS: List APIs, Tables, Libraries. Use SINGLE QUOTES inside strings.
                   - IF EMPTY: Write "No technical details provided".

                4. test_scenarios: 
                   - IF DATA EXISTS: Create 3-5 high-level test titles.
                   - ⚠️ OUTPUT AS STRING (Text), NOT LIST.
                   - Format: "- Test Case 1\n- Test Case 2"
                   - If empty, write "No test scenarios provided".

                5. issue_links: 
                   - Extract valid links. IF EMPTY: Send [].

                ⛔ OUTPUT RAW JSON TOOL CALL ONLY. DO NOT CHAT. DO NOT APOLOGIZE.
                """

        fresh_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"RAW DATA:\n{raw_data_str}")
        ]

        response = llm.bind_tools([save_ticket_knowledge], tool_choice="save_ticket_knowledge").invoke(fresh_messages)

        # 🔍 DEBUG: ขอดูหน่อยซิว่า AI ตอบอะไรมา (สำคัญมาก!)
        logging.info(f"🤖 AI RESPONSE CONTENT: {response.content}")
        logging.info(f"🔧 AI TOOL CALLS: {getattr(response, 'tool_calls', 'None')}")

        # 🔥🔥🔥 SAFETY NET V2: The Ultimate Parser (AST + JSON) 🔥🔥🔥
        # ถ้า AI ไม่เรียก Tool แต่พ่น JSON ออกมาเป็น Text
        if not getattr(response, 'tool_calls', None) and response.content.strip().startswith('{'):
            print("⚠️ DETECTED FAKE TOOL CALL (TEXT JSON) - ATTEMPTING REPAIR...")
            content_str = response.content.strip()
            data = None

            # วิธีที่ 1: ลองแปลงแบบ JSON ปกติ (ผ่อนปรน)
            try:
                data = json.loads(content_str, strict=False)
            except:
                pass

            # วิธีที่ 2: ลองแปลงแบบ Python Dictionary (เทพกว่า รับ Quote ซ้อนได้)
            if data is None:
                try:
                    # แปลง keyword json เป็น python
                    py_str = content_str.replace("true", "True").replace("false", "False").replace("null", "None")
                    data = ast.literal_eval(py_str)
                    print("✅ REPAIRED using AST (Python Parser)!")
                except Exception as e:
                    print(f"❌ Failed to parse via AST: {e}")

            # ยัดเยียดความเป็น Tool Call
            if data and "name" in data and "parameters" in data:
                response.tool_calls = [{
                    "name": data["name"],
                    "args": data["parameters"],
                    "id": "manual_fix_id"
                }]
                response.content = ""

    return {"messages": [response]}

def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    messages = state['messages']
    last_message = messages[-1]

    # 1. ถ้า AI ไม่เรียก Tool แล้ว -> จบ
    if not last_message.tool_calls:
        return "__end__"

    # 2. ✅✅✅ Logic ดัดหลัง Llama 3.1 ✅✅✅
    # เช็คว่า "รอบที่แล้ว" เราเพิ่ง Save เสร็จไปหมาดๆ หรือไม่?
    # ถ้าใช่ แสดงว่า AI กำลังเอ๋อจะเรียกซ้ำ -> บังคับจบงานเลย
    if len(messages) > 2:
        prev_msg = messages[-2]  # ข้อความก่อนหน้า (น่าจะเป็น ToolMessage)
        if isinstance(prev_msg, ToolMessage):
            # ถ้าเพิ่ง Save เสร็จ ให้จบเลย ไม่ต้องไปต่อ
            # (ชื่อ Tool อาจต้องเช็คให้ตรงกับที่คุณตั้ง ในที่นี้สมมติ save_ticket_knowledge)
            if "save" in prev_msg.name.lower() or "database" in prev_msg.name.lower():
                return "__end__"

    # 3. ถ้าไม่มีอะไรผิดปกติ ก็ให้เรียก Tool ต่อไป
    return "tools"

# --- 3. Build Graph ---
def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    return workflow.compile()


# --- For Testing ---
if __name__ == "__main__":
    import dotenv

    dotenv.load_dotenv()

    app = build_graph()
    target_ticket = "SCRUM-6"  # เปลี่ยนเป็น Ticket ที่ต้องการเทส

    print(f"📚 Librarian Agent (Ollama): Syncing {target_ticket}...\n")

    try:
        final_state = app.invoke(
            {"messages": [HumanMessage(content=f"Sync data for {target_ticket}")]},
            config={"recursion_limit": 20}
        )

        print("\n--------------------------------")
        print("🕵️‍♀️ DEBUG: Tool Execution History")
        print("--------------------------------")

        for i, msg in enumerate(final_state['messages']):
            # ✅ ใช้ getattr เพื่อความปลอดภัย (HumanMessage ไม่มี tool_calls ก็จะไม่ Error)
            tool_calls = getattr(msg, 'tool_calls', [])
            content = getattr(msg, 'content', "")

            # 1. กรณีเป็น AI สั่งเรียก Tool
            if tool_calls:
                for tool in tool_calls:
                    print(f"[{i}] 🔧 AI Called Tool: {tool['name']}")
                    import json

                    try:
                        print(f"     📦 Payload: {json.dumps(tool['args'], indent=2, ensure_ascii=False)}")
                    except:
                        print(f"     📦 Payload: {tool['args']}")

            # 2. กรณีเป็นผลลัพธ์จาก Tool (ToolMessage)
            elif isinstance(msg, ToolMessage):
                output_preview = str(content)[:200].replace('\n', ' ')
                print(f"[{i}] 📤 Tool Output: {output_preview}...")

            # 3. กรณีเป็นข้อความสนทนา (Human หรือ AI บ่น)
            elif content:
                sender = "👤 User" if isinstance(msg, HumanMessage) else "🤖 AI"
                print(f"[{i}] {sender}: {content}")

        print("\n--------------------------------")

    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"\n❌ Error: {e}")
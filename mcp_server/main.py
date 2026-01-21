import sys
import os
import httpx
import logging
import subprocess
from typing import List

# --- 1. SETUP LOGGING ---
# สำคัญมาก: ห้ามใช้ print() ใน MCP Server ให้ใช้ logging แทน
log_file_path = r"D:\Project\PaymentBlockChain\mcp_debug.log"
logging.basicConfig(
    filename=log_file_path,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True
)

# ดักจับ Error ทุกอย่างที่ทำให้โปรแกรมพัง แล้วเขียนลงไฟล์
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

from mcp.server.fastmcp import FastMCP

from dotenv import load_dotenv
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
# 👇 เพิ่ม 3 บรรทัดนี้ เพื่อให้ Python มองเห็นโฟลเดอร์ Project หลัก
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from knowledge_base.vector_store import add_ticket_to_vector, search_vector_db
from graph.tools.file_ops import read_file, write_file, list_directory
from graph.tools.git_ops import git_create_branch, git_commit_changes, git_status, git_push_to_remote # 👈 เพิ่ม import
from graph.tools.git_ops import create_pull_request # เพิ่ม import



logging.info("🚀 Starting MCP Server...")

try:
    # --- SETUP PATH & IMPORTS ---
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.append(parent_dir)

    load_dotenv(os.path.join(parent_dir, ".env"))

    from langchain_core.messages import HumanMessage
    from graph.workflow import build_graph
    from knowledge_base.database import SessionLocal
    from knowledge_base.models import JiraKnowledge

    # --- [NEW] IMPORT LOCAL AGENT ---
    from local_agent.dev_agent import run_dev_agent_task

    logging.info("✅ Local Agent loaded successfully.")

except ImportError as e:
    logging.error(f"⚠️ Import Error (Local Agent or Graph): {e}")
    # Dummy function if import fails
    def run_dev_agent_task(task): return f"Error: Local Agent module not found. {e}"

except Exception as e:
    logging.critical(f"❌ CRITICAL ERROR during startup: {str(e)}", exc_info=True)
    sys.exit(1)

# Initialize MCP Server
mcp = FastMCP("Jira-Knowledge-Gateway")

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


# === HELPER FUNCTIONS ===

def _run_agent_sync(ticket_key: str) -> str:
    """Helper to run the single-ticket agent."""
    try:
        app = build_graph()
        # config limit เพื่อป้องกัน infinite loop
        final_state = app.invoke(
            {"messages": [HumanMessage(content=f"Sync data for {ticket_key}")]},
            config={"recursion_limit": 50}
        )
        return final_state['messages'][-1].content
    except Exception as e:
        logging.error(f"Agent failed for {ticket_key}: {e}")
        return f"Failed: {e}"


def _search_jira_keys(jql: str, max_fetch: int = 50) -> List[str]:
    """Helper to search Jira tickets via API."""
    if not JIRA_URL or not JIRA_API_TOKEN:
        raise ValueError("Missing Jira Config")

    url = f"{JIRA_URL}/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    found_keys = []
    next_token = None

    logging.info(f"🔎 Executing JQL: {jql}")

    while True:
        if len(found_keys) >= max_fetch:
            break

        payload = {
            "jql": jql,
            "fields": ["key"],
            "maxResults": 50
        }

        if next_token:
            payload["nextPageToken"] = next_token

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, auth=auth, headers=headers, json=payload)

            if resp.status_code != 200:
                error_msg = f"Jira Search Error ({resp.status_code}): {resp.text}"
                logging.error(error_msg)
                raise Exception(error_msg)

            data = resp.json()
            issues = data.get("issues", [])

            if not issues:
                break

            for issue in issues:
                found_keys.append(issue["key"])

            next_token = data.get("nextPageToken")
            if not next_token:
                break

    return found_keys


def _get_last_sync_time() -> str:
    """Find the latest sync timestamp from DB."""
    session: Session = SessionLocal()
    try:
        last_time = session.query(func.max(JiraKnowledge.last_synced_at)).scalar()
        if last_time:
            return last_time.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logging.error(f"DB Query Error: {e}")
    finally:
        session.close()
    return None


# === MCP TOOLS ===

@mcp.tool()
async def preview_jira_ticket(issue_key: str) -> str:
    """PREVIEW details of a Jira ticket (Live Data)."""
    logging.info(f"Tool called: preview_jira_ticket for {issue_key}")

    if not JIRA_URL or not JIRA_API_TOKEN:
        return "Error: JIRA_URL or JIRA_API_TOKEN not set."

    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, auth=auth, headers=headers)
            if response.status_code == 404:
                return f"Jira Ticket {issue_key} not found."
            if response.status_code != 200:
                return f"Error fetching Jira: {response.status_code}"

            data = response.json()
            fields = data.get("fields", {})
            summary = fields.get("summary", "No Summary")
            status = fields.get("status", {}).get("name", "Unknown")
            description = str(fields.get("description", "No Description"))[:1000]

            return f"""
            --- JIRA TICKET (LIVE): {issue_key} ---
            Summary: {summary}
            Status: {status}
            Description: {description}...
            --------------------------------
            """
        except Exception as e:
            return f"Exception occurred: {str(e)}"


@mcp.tool()
def sync_single_ticket(ticket_key: str) -> str:
    """ACTIONS: Sync ONE specific Jira ticket to Database."""
    return _run_agent_sync(ticket_key)


@mcp.tool()
def dispatch_task_to_beta(task_description: str) -> str:
    """
    Delegate a long-running software task to 'Beta' Agent (Qwen) in BACKGROUND mode.
    This tool returns immediately, while Beta works in a separate process.
    """
    logging.info(f"🤖 Dispatching task to Beta (Background): {task_description}")

    # ✅ 1. ระบุ Path ของ Python ใน .venv ให้ชัดเจน (แก้ปัญหารันไม่ขึ้น)
    # สมมติว่าโปรเจกต์อยู่ที่ D:\Project\PaymentBlockChain
    project_root = r"D:\Project\PaymentBlockChain"
    venv_python = os.path.join(project_root, ".venv", "Scripts", "python.exe")
    script_path = os.path.join(project_root, "run_local_dev.py")

    # เช็คความชัวร์ว่ามีไฟล์จริงไหม
    if not os.path.exists(venv_python):
        return f"❌ Error: Cannot find Python venv at {venv_python}"
    if not os.path.exists(script_path):
        return f"❌ Error: Cannot find script at {script_path}"

    command = [venv_python, script_path, task_description]

    try:
        # ✅ 2. ใช้ Popen แทน run (Fire & Forget)
        # วิธีนี้จะเปิด Process ใหม่แล้วปล่อยมือทันที Claude ไม่ต้องรอ
        subprocess.Popen(
            command,
            cwd=project_root,
            creationflags=subprocess.CREATE_NEW_CONSOLE  # เปิดหน้าต่างใหม่ให้เห็นกันจะๆ
        )

        return (
            "✅ **Task Started Successfully!**\n\n"
            "Beta Agent is running in a separate console window.\n"
            "Please wait approx 2-5 minutes for the PR to appear on GitHub.\n"
            "You can continue with other tasks while Beta is working."
        )

    except Exception as e:
        error_msg = f"❌ System Error launching Beta Agent: {str(e)}"
        logging.error(error_msg)
        return error_msg


@mcp.tool()
def search_knowledge_base(query: str) -> str:
    """
    SEARCH local database for saved Jira knowledge (Logic, Specs).
    """
    logging.info(f"🔎 Searching DB for: '{query}'")
    session: Session = SessionLocal()
    try:
        results = session.query(JiraKnowledge).filter(
            or_(
                JiraKnowledge.issue_key.ilike(f"%{query}%"),
                JiraKnowledge.summary.ilike(f"%{query}%"),
                JiraKnowledge.business_logic.ilike(f"%{query}%"),
                JiraKnowledge.technical_spec.ilike(f"%{query}%"),
                JiraKnowledge.test_scenarios.ilike(f"%{query}%")
            )
        ).limit(5).all()

        if not results:
            return "❌ No relevant information found in Local Database."

        output = [f"Found {len(results)} records matching '{query}':\n"]
        for r in results:
            output.append(
                f"=== [{r.issue_key}] {r.summary} ===\nStatus: {r.status}\nLogic: {r.business_logic[:200]}...\n")

        return "\n".join(output)
    except Exception as e:
        return f"DB Error: {str(e)}"
    finally:
        session.close()


@mcp.tool()
def get_project_dashboard(project_key: str = "SCRUM", limit: int = 50) -> str:
    """
    GET DASHBOARD: High-level summary of active tickets.
    """
    logging.info(f"📊 Generating Dashboard for {project_key}...")
    session: Session = SessionLocal()
    try:
        results = session.query(
            JiraKnowledge.issue_key,
            JiraKnowledge.summary,
            JiraKnowledge.status,
            JiraKnowledge.issue_type
        ).filter(
            JiraKnowledge.issue_key.like(f"{project_key}-%")
        ).order_by(JiraKnowledge.issue_key.desc()).limit(limit).all()

        if not results:
            return f"❌ No data found for {project_key}."

        report = [f"📊 DASHBOARD: {project_key} ({len(results)} tickets)\n"]
        report.append(f"{'KEY':<10} | {'STATUS':<12} | {'SUMMARY'}")
        report.append("-" * 60)

        for r in results:
            summ = (r.summary[:40] + '..') if len(r.summary) > 40 else r.summary
            status = r.status or "Unknown"
            report.append(f"{r.issue_key:<10} | {status:<12} | {summ}")

        return "\n".join(report)
    except Exception as e:
        return f"Dashboard Error: {str(e)}"
    finally:
        session.close()


@mcp.tool()
def reindex_knowledge_base() -> str:
    """
    ADMIN TOOL: Convert all SQL Knowledge into Vector Embeddings.
    Run this once after installing Vector Search or when data feels out of sync.
    """
    session: Session = SessionLocal()
    try:
        # ดึงข้อมูลทั้งหมดจาก SQL
        tickets = session.query(JiraKnowledge).all()
        count = 0

        for t in tickets:
            # เตรียมข้อมูลส่งไปทำ Vector
            data = {
                "key": t.issue_key,
                "summary": t.summary,
                "status": t.status,
                "logic": t.business_logic,
                "spec": t.technical_spec
            }
            add_ticket_to_vector(data)
            count += 1

        return f"✅ Successfully Indexed {count} tickets into Vector Database."
    except Exception as e:
        return f"Indexing Failed: {e}"
    finally:
        session.close()


@mcp.tool()
def ask_project_guru(question: str) -> str:
    """
    SMART SEARCH: Ask questions about the project using natural language.
    Use this when you want to understand CONCEPTS, LOGIC, or RELATIONSHIPS.
    Example: "How does the payment calculation work?", "Do we have any AI tasks?"
    """
    # ใช้ Vector Search แทน SQL Search ธรรมดา
    return search_vector_db(question, k=4)

# --------------------------
# FILE SYSTEM TOOLS
# --------------------------
@mcp.tool()
def read_project_file(path: str):
    """Read code or text file from the project."""
    return read_file.invoke({"file_path": path})

@mcp.tool()
def write_project_file(path: str, content: str):
    """Write content to a file. USE WITH CAUTION."""
    return write_file.invoke({"file_path": path, "content": content})

@mcp.tool()
def list_project_files(path: str = "."):
    """See file structure."""
    return list_directory.invoke({"dir_path": path})


# ==========================================
# 🆕 UPGRADED TOOL: DISPATCH TO BETA (VIA SUBPROCESS)
# ==========================================

@mcp.tool()
def dispatch_task_to_beta(task_description: str) -> str:
    """
    Delegate a software development task to the 'Beta' Agent (Qwen).
    Use this tool to create features, write code, run tests, and create PRs autonomously.

    Args:
        task_description: The detailed instruction (e.g. "Create FastAPI endpoint for user login", "Fix bug in calculation logic from Jira KEY-123")
    """
    logging.info(f"🤖 Dispatching task to Beta Agent: {task_description}")

    # ⚠️ แก้ Path นี้ให้ตรงกับที่อยู่ไฟล์ run_local_dev.py ของคุณจริงๆ
    script_path = r"D:\Project\PaymentBlockChain\run_local_dev.py"
    working_dir = r"D:\Project\PaymentBlockChain"

    command = ["python", script_path, task_description]

    try:
        # รัน Script และดักจับ Output ทั้งหมด
        process = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            encoding='utf-8'  # รองรับภาษาไทย
        )

        output_log = process.stdout
        error_log = process.stderr

        # ตัด Log ให้สั้นลงหน่อยถ้ามันยาวเกินไป (เอาแค่ 4000 ตัวอักษรท้าย)
        summary_log = output_log[-4000:] if len(output_log) > 4000 else output_log

        if process.returncode == 0:
            return f"✅ Beta Agent Finished Successfully!\n\n--- AGENT LOG ---\n{summary_log}"
        else:
            return f"❌ Beta Agent Failed (Code {process.returncode}).\n\n--- ERROR LOG ---\n{error_log}\n\n--- STDOUT ---\n{summary_log}"

    except Exception as e:
        error_msg = f"❌ System Error launching Beta Agent: {str(e)}"
        logging.error(error_msg)
        return error_msg


# ==========================================

# --------------------------
# GIT TOOLS
# --------------------------
@mcp.tool()
def git_new_branch(name: str):
    """Start working on a new feature branch."""
    return git_create_branch.invoke({"branch_name": name})

@mcp.tool()
def git_commit(msg: str):
    """Save changes to git."""
    return git_commit_changes.invoke({"message": msg})

@mcp.tool()
def git_check_status():
    """Check current branch and changed files."""
    return git_status.invoke({})

@mcp.tool()
def git_push(branch: str):
    """Push code to GitHub."""
    return git_push_to_remote.invoke({"branch_name": branch})

@mcp.tool()
def github_create_pr(title: str, description: str, branch_name: str):
    """Create a PR on GitHub after pushing code."""
    return create_pull_request.invoke({
        "title": title,
        "body": description,
        "branch": branch_name
    })

if __name__ == "__main__":
    logging.info("Run command executing...")
    try:
        mcp.run()
    except Exception as e:
        logging.critical(f"Server crashed: {e}", exc_info=True)
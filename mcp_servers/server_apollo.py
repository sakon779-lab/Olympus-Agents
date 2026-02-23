import sys
import os
import logging
import contextlib
import threading
import time
import uuid
import builtins
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ==============================================================================
# 🛡️ STDOUT PROTECTION & ENCODING FIX
# ==============================================================================
# 1. บังคับ UTF-8 ที่ stderr (แก้ปัญหา Emoji Crash บน Windows)
try:
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 2. HIJACK PRINT: บังคับทุกคำสั่ง print() ให้ลง stderr
# สิ่งนี้จะช่วยกันไม่ให้ [DEBUG] logs หลุดไป stdout จนทำให้ JSON พัง
original_print = builtins.print
def patched_print(*args, **kwargs):
    kwargs['file'] = sys.stderr
    original_print(*args, **kwargs)
builtins.print = patched_print

# ------------------------------------------------------------------
# 🔇 LOGGING SETUP
# ------------------------------------------------------------------
logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)

# 1. Setup Path
current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))
sys.path.append(project_root)

# 2. Load Environment Variables
load_dotenv(os.path.join(project_root, ".env"))

# 3. Import Functions
try:
    from agents.apollo.agent import (
        ask_guru,
        ask_database_analyst,
        sync_ticket_to_knowledge_base,
        sync_recent_tickets # ✅ เพิ่มตัวนี้เข้ามา
    )
except ImportError as e:
    print(f"❌ [DEBUG] Error importing Apollo components: {e}")

# 4. Create Server
mcp = FastMCP("Olympus - Apollo")

# ==============================================================================
# 🧠 MEMORY: เก็บสถานะงาน (In-Memory Job Queue)
# ==============================================================================
# Format: { "job_id": {"type": "sync", "status": "running", "result": "..."} }
JOBS = {}

@contextlib.contextmanager
def redirect_stdout_to_stderr():
    """Redirect print() to stderr to prevent breaking MCP JSON-RPC protocol"""
    original_stdout = sys.stdout
    try:
        sys.stdout = sys.stderr
        yield
    finally:
        sys.stdout = original_stdout

# ==============================================================================
# 👷 WORKER: คนทำงานเบื้องหลัง
# ==============================================================================


# 👷 อัปเกรด Worker ให้รองรับงานหลายประเภท
def background_worker(job_id: str, action_type: str, args: dict):
    """Worker อเนกประสงค์สำหรับงาน Async"""
    sys.stderr.write(f"▶️ [Worker] Starting {action_type} Job {job_id}\n")
    JOBS[job_id]["status"] = "RUNNING"

    try:
        with redirect_stdout_to_stderr():
            if action_type == "sync_ticket":
                result = sync_ticket_to_knowledge_base(args['issue_key'])
            elif action_type == "sync_recent":
                # ✅ เรียกฟังก์ชัน sync ตามช่วงเวลาที่เราคุยกัน
                result = sync_recent_tickets(args['hours'])
            else:
                result = "Unknown Action"

        JOBS[job_id]["status"] = "COMPLETED"
        JOBS[job_id]["result"] = result
        sys.stderr.write(f"✅ [Worker] Job {job_id} ({action_type}) Finished.\n")

    except Exception as e:
        JOBS[job_id]["status"] = "FAILED"
        JOBS[job_id]["error"] = str(e)
        sys.stderr.write(f"❌ [Worker] Job {job_id} Failed: {e}\n")

# ==============================================================================
# 🛠️ TOOLS
# ==============================================================================

@mcp.tool()
def consult_knowledge_base(question: str) -> str:
    """Ask Apollo's Knowledge Guru."""
    try:
        return ask_guru(question)
    except Exception as e:
        return f"❌ Guru Error: {str(e)}"

@mcp.tool()
def consult_database_stats(question: str) -> str:
    """Ask Apollo's Data Analyst."""
    try:
        return ask_database_analyst(question)
    except Exception as e:
        return f"❌ Analyst Error: {str(e)}"

@mcp.tool()
def sync_jira_ticket(issue_key: str) -> str:
    """
    Start syncing a specific Jira ticket to the Knowledge Base (ASYNC).
    Returns a Job ID immediately. Use this when the user wants to update/read a ticket.
    """
    job_id = str(uuid.uuid4())[:8]

    # สร้าง Job Slot
    JOBS[job_id] = {
        "type": "sync_ticket",
        "target": issue_key,
        "status": "PENDING",
        "start_time": time.strftime("%H:%M:%S")
    }

    # Fire Thread
    thread = threading.Thread(
        target=background_worker,
        args=(job_id, "sync_ticket", {"issue_key": issue_key})
    )
    thread.daemon = True
    thread.start()

    return (
        f"🚀 Sync Started! Job ID: {job_id}\n"
        f"Target: {issue_key}\n\n"
        f"I am processing this in the background. Please wait a moment, "
        f"then use `check_job_status('{job_id}')` to see the result."
    )

@mcp.tool()
def check_job_status(job_id: str) -> str: # 🟢 [FIX 2] เพิ่ม Tool นี้กลับเข้ามา
    """
    Check the status of a background job (e.g., Sync Jira) using its Job ID.
    """
    job = JOBS.get(job_id)
    if not job:
        return f"❌ Job ID {job_id} not found."

    status = job["status"]

    if status == "RUNNING":
        return f"⏳ Job {job_id} is still running... (Started at {job['start_time']})"

    elif status == "COMPLETED":
        return f"✅ Job {job_id} COMPLETED!\n\nResult:\n{job.get('result')}"

    elif status == "FAILED":
        return f"❌ Job {job_id} FAILED.\nError: {job.get('error')}"

    return f"Job {job_id} status: {status}"


@mcp.tool()
def sync_recent_updates(hours: int = 24) -> str:
    """
    Sync all Jira tickets updated within the last N hours (ASYNC).
    Use this to refresh the entire knowledge base for a specific period.
    """
    job_id = f"batch-{str(uuid.uuid4())[:6]}"

    JOBS[job_id] = {
        "type": "sync_recent",
        "hours": hours,
        "status": "PENDING",
        "start_time": time.strftime("%H:%M:%S")
    }

    # ส่งงานเข้า Background Thread
    thread = threading.Thread(
        target=background_worker,
        args=(job_id, "sync_recent", {"hours": hours})
    )
    thread.daemon = True
    thread.start()

    return (
        f"🔄 Batch Sync Started! Job ID: {job_id}\n"
        f"Scanning updates for the last {hours} hours...\n"
        f"Use `check_job_status('{job_id}')` to see the summary of synced tickets."
    )

# 5. Run Server
if __name__ == "__main__":
    mcp.run()
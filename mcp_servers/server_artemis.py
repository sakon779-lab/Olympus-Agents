import sys
import os
import logging
import contextlib
import threading
import time
import uuid
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ------------------------------------------------------------------
# 🔇 SILENCE MODE & LOGGING
# ------------------------------------------------------------------
# บังคับ Log ออก stderr เพื่อไม่ให้ MCP Protocol (JSON) พัง
logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("robot").setLevel(logging.ERROR)  # ปิด Log ของ Robot Framework ด้วย

current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))
sys.path.append(project_root)

load_dotenv(os.path.join(project_root, ".env"))

# ✅ IMPORT AGENT (ต้องมีไฟล์ agents/artemis/agent.py)
try:
    from agents.artemis.agent import run_artemis_task

    sys.stderr.write("✅ [DEBUG] Artemis Agent imported successfully.\n")
except ImportError as e:
    sys.stderr.write(f"❌ [DEBUG] Error importing Artemis: {e}\n")
    sys.exit(1)

# ตั้งชื่อ Server
mcp = FastMCP("Olympus - Artemis")

# ==============================================================================
# 🧠 MEMORY: เก็บสถานะงาน (In-Memory Job Queue)
# ==============================================================================
JOBS = {}


@contextlib.contextmanager
def redirect_stdout_to_stderr():
    """บังคับทุกอย่างที่ Print ให้ไปออก stderr (Console) ไม่กวน MCP"""
    original_stdout = sys.stdout
    try:
        sys.stdout = sys.stderr
        yield
    finally:
        sys.stdout = original_stdout


# ==============================================================================
# 👷 WORKER: คนทำงานเบื้องหลัง
# ==============================================================================
def background_worker(job_id: str, issue_key: str):
    """รัน Artemis ใน Thread แยก"""
    task_desc = f"Implement Robot Framework Tests for Jira Ticket: {issue_key}"
    sys.stderr.write(f"🏹 [Worker] Starting Job {job_id}: {task_desc}\n")

    JOBS[job_id]["status"] = "RUNNING"
    JOBS[job_id]["log"] = "Artemis is hunting for bugs..."

    try:
        # ใช้ Context Manager ดักจับ Print ทั้งหมด
        with redirect_stdout_to_stderr():
            # เรียกฟังก์ชันหลักของ Artemis
            result = run_artemis_task(task_desc)

        JOBS[job_id]["status"] = "COMPLETED"
        JOBS[job_id]["result"] = result
        sys.stderr.write(f"✅ [Worker] Job {job_id} Finished.\n")

    except Exception as e:
        JOBS[job_id]["status"] = "FAILED"
        JOBS[job_id]["error"] = str(e)
        sys.stderr.write(f"❌ [Worker] Job {job_id} Failed: {e}\n")


# ==============================================================================
# 🛠️ TOOLS (Exposed to Claude)
# ==============================================================================

@mcp.tool()
def start_test_automation_async(issue_key: str) -> str:
    """
    Start the QA Automation Agent (Artemis) to implement Robot Framework tests based on the design (CSV).
    Returns a Job ID immediately. The agent runs in the background.

    Args:
        issue_key: The Jira Ticket ID (e.g., SCRUM-26). Make sure 'start_qa_design_async' (Athena) is done first!
    """
    job_id = str(uuid.uuid4())[:8]

    JOBS[job_id] = {
        "task": issue_key,
        "status": "PENDING",
        "start_time": time.strftime("%H:%M:%S")
    }

    # 🚀 Fire Thread
    thread = threading.Thread(target=background_worker, args=(job_id, issue_key))
    thread.daemon = True
    thread.start()

    return f"✅ Artemis Task Accepted! Job ID: {job_id}\n\nArtemis is reading the test design and implementing Robot tests.\nPlease use 'check_test_status(\"{job_id}\")' to get the result."


@mcp.tool()
def check_test_status(job_id: str) -> str:
    """
    Check the status of an Artemis automation task using its Job ID.
    """
    job = JOBS.get(job_id)
    if not job:
        return f"❌ Job ID {job_id} not found."

    status = job["status"]

    if status == "RUNNING":
        return f"⏳ Artemis is working on {job['task']}... (Started at {job['start_time']})\nCheck the terminal logs for details."

    elif status == "COMPLETED":
        return f"✅ Job {job_id} COMPLETED!\n\nResult:\n{job.get('result')}"

    elif status == "FAILED":
        return f"❌ Job {job_id} FAILED.\nError: {job.get('error')}"

    return f"Job {job_id} status: {status}"


if __name__ == "__main__":
    mcp.run()
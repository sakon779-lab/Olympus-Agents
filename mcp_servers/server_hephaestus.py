import sys
import os
import logging
import contextlib
import threading
import time
import uuid
import io  # เพิ่ม io
# ------------------------------------------------------------------
# 1. 🛑 STOP STDOUT LEAKS IMMEDIATELY (ทำก่อน import อื่นๆ)
# ------------------------------------------------------------------
if sys.platform == "win32":
    # บังคับ UTF-8
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ------------------------------------------------------------------
# 🔇 SILENCE MODE & LOGGING
# ------------------------------------------------------------------
logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))
sys.path.append(project_root)

load_dotenv(os.path.join(project_root, ".env"))

# Import Agent
try:
    from agents.hephaestus.agent import run_hephaestus_task

    sys.stderr.write("✅ [DEBUG] Hephaestus Agent imported successfully.\n")
except ImportError as e:
    sys.stderr.write(f"❌ [DEBUG] Error importing Hephaestus: {e}\n")
    sys.exit(1)

mcp = FastMCP("Olympus - Hephaestus")

# ==============================================================================
# 🧠 MEMORY: เก็บสถานะงาน (In-Memory Job Queue)
# ==============================================================================
# เก็บสถานะงาน: { "job_id": {"status": "running/done/failed", "result": "..."} }
JOBS = {}


@contextlib.contextmanager
def redirect_stdout_to_stderr():
    original_stdout = sys.stdout
    try:
        sys.stdout = sys.stderr
        yield
    finally:
        sys.stdout = original_stdout


# ==============================================================================
# 👷 WORKER: คนทำงานเบื้องหลัง
# ==============================================================================
def background_worker(job_id: str, task_description: str):
    """ฟังก์ชันที่จะรันใน Thread แยก ไม่บล็อก Claude"""
    sys.stderr.write(f"▶️ [Worker] Starting Job {job_id}: {task_description}\n")

    JOBS[job_id]["status"] = "RUNNING"
    JOBS[job_id]["log"] = "Started..."

    try:
        # ใช้ Context Manager เพื่อให้ Log ออกทาง stderr (Terminal)
        with redirect_stdout_to_stderr():
            result = run_hephaestus_task(task_description)

        JOBS[job_id]["status"] = "COMPLETED"
        JOBS[job_id]["result"] = result
        sys.stderr.write(f"✅ [Worker] Job {job_id} Finished.\n")

    except Exception as e:
        JOBS[job_id]["status"] = "FAILED"
        JOBS[job_id]["error"] = str(e)
        sys.stderr.write(f"❌ [Worker] Job {job_id} Failed: {e}\n")


# ==============================================================================
# 🛠️ TOOLS
# ==============================================================================

@mcp.tool()
def assign_task_async(task_description: str) -> str:
    """
    Start a long-running coding task. Returns a Job ID immediately.
    Use this for implementing features or fixing bugs.
    """
    job_id = str(uuid.uuid4())[:8]  # สร้าง ID สั้นๆ

    # สร้าง Slot รอไว้
    JOBS[job_id] = {
        "task": task_description,
        "status": "PENDING",
        "start_time": time.strftime("%H:%M:%S")
    }

    # 🚀 Fire! สร้าง Thread แยกไปทำงาน
    thread = threading.Thread(target=background_worker, args=(job_id, task_description))
    thread.daemon = True  # ปิดโปรแกรมแล้ว Thread ดับด้วย
    thread.start()

    return f"✅ Task Accepted! Job ID: {job_id}\n\nThe agent is working in the background.\nPlease wait a moment, then use 'check_task_status(\"{job_id}\")' to see the result."


@mcp.tool()
def check_task_status(job_id: str) -> str:
    """
    Check the status of a background task using its Job ID.
    """
    job = JOBS.get(job_id)
    if not job:
        return f"❌ Job ID {job_id} not found."

    status = job["status"]

    if status == "RUNNING":
        return f"⏳ Job {job_id} is still running... (Started at {job['start_time']})\nCheck the terminal logs for real-time progress."

    elif status == "COMPLETED":
        return f"✅ Job {job_id} COMPLETED!\n\nResult:\n{job.get('result')}"

    elif status == "FAILED":
        return f"❌ Job {job_id} FAILED.\nError: {job.get('error')}"

    return f"Job {job_id} status: {status}"


if __name__ == "__main__":
    mcp.run()
# ไฟล์: graph/tools/git_ops.py
import os
import subprocess
import shutil
import logging
from langchain_core.tools import tool

# Setup Logger
logger = logging.getLogger(__name__)

# หา Path ของ Project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_git_command(args: list):
    command_str = " ".join(["git"] + args)
    logger.info(f"⏳ GIT RUNNING: {command_str}")

    try:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"  # ห้ามถาม Password

        # 👇 ไฮไลท์สำคัญ: ต้องมี timeout=15
        result = subprocess.run(
            ["git"] + args,
            cwd=BASE_DIR,
            capture_output=True,
            stdin=subprocess.DEVNULL,  # <--- ใส่ตัวนี้สำคัญมาก
            text=True,
            check=True,
            env=env,
            timeout=15  # 👈 ใส่บรรทัดนี้ครับ! ถ้าเกิน 15 วิ ให้ Error เลย
        )
        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        logger.error(f"⏱️ TIMEOUT: Git took too long ({command_str})")
        return "Error: Git command timed out. Please check for file locks or open editors."

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ GIT ERROR: {e.stderr}")
        return f"Error: {e.stderr}"


@tool
def git_create_branch(branch_name: str):
    """Create and switch to a new git branch."""
    # 1. เช็ค Status ก่อน
    status = run_git_command(["status", "--porcelain"])
    if status and "Git Error" not in status:
        return "Error: You have uncommitted changes. Please commit or stash them first."

    # 2. สร้าง Branch
    return run_git_command(["checkout", "-b", branch_name])


@tool
def git_commit_changes(message: str):
    """Stage all changes and commit."""
    run_git_command(["add", "."])
    return run_git_command(["commit", "-m", message])


@tool
def git_status():
    """Check status."""
    return run_git_command(["status"])


@tool
def git_push_to_remote(branch_name: str):
    """Push to origin."""
    return run_git_command(["push", "-u", "origin", branch_name])

# 👇👇👇 เพิ่มฟังก์ชันนี้ต่อจาก git_push_to_remote 👇👇👇
@tool
def git_pull_from_remote(branch_name: str = "main"):
    """Pull latest changes from remote."""
    # --no-rebase เพื่อความปลอดภัย กัน History พัง
    return run_git_command(["pull", "origin", branch_name, "--no-rebase"])

@tool
def create_pull_request(title: str, body: str, branch: str):
    """Create GitHub PR (Non-interactive)"""
    if not shutil.which("gh"):
        return "Error: GitHub CLI (gh) is not installed."

    # ตรวจสอบ Base branch ว่าเป็น main หรือ master (Optional: ถ้าจะเอาให้ชัวร์)
    # แต่ถ้าโปรเจกต์คุณใช้ main ตลอด ก็ใช้แบบเดิมได้ครับ
    base_branch = "main"

    try:
        # gh cli parameters
        cmd = [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--head", branch,
            "--base", base_branch
        ]

        logger.info(f"⏳ PR CREATING: Merging {branch} -> {base_branch}")

        # เพิ่ม Env เพื่อปิดลูกเล่น Interactive ของ gh
        env = os.environ.copy()
        env["GH_NO_UPDATE_NOTIFIER"] = "1"  # ปิดแจ้งเตือน update
        env["GH_PROMPT_DISABLE"] = "1"  # ห้ามถามอะไรทั้งนั้น

        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
            env=env,  # ใช้ Env ที่ตั้งค่าไว้
            stdin=subprocess.DEVNULL,  # <--- กันตาย: ห้ามรอ Input
            timeout=60  # <--- กันเหนียว: ให้เวลา 60 วิ (เผื่อเน็ตช้า)
        )
        return f"✅ PR Created: {result.stdout.strip()}"

    except subprocess.TimeoutExpired:
        logger.error("⏱️ TIMEOUT: GH PR Create took too long")
        return "Error: Creating PR timed out. Please check your internet connection."

    except subprocess.CalledProcessError as e:
        # อ่าน Error จริงๆ จาก stderr
        error_msg = e.stderr.strip()
        logger.error(f"❌ GH PR ERROR: {error_msg}")

        # กรณี Base branch ไม่ตรง หรือมี PR อยู่แล้ว
        if "already exists" in error_msg:
            return f"Warning: A PR for {branch} already exists."

        return f"PR Failed: {error_msg}"
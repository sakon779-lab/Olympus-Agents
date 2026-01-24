import subprocess
import os
import logging
from typing import Optional
from core.config import settings

# Setup Logging
logger = logging.getLogger("GitOps")


def git_setup_workspace(issue_key: str, base_branch: str = "main") -> str:
    """
    Setup Workspace แบบฉลาด (Smart Repo Selection):
    1. เลือก Repo ต้นทาง (Dev หรือ QA) ตาม Role ของ Agent (ผ่าน settings.TARGET_REPO_PATH)
    2. สร้าง Workspace แยกตามชื่อ Agent (ผ่าน settings.AGENT_WORKSPACE)
    3. Clone & Checkout Feature Branch
    """
    # ✅ 1. รับค่า Path ที่ Config เลือกมาให้แล้ว (Dev หรือ QA)
    target_source_repo = settings.TARGET_REPO_PATH

    # ✅ 2. รับค่า Workspace ที่แยกโฟลเดอร์ตามชื่อ Agent
    agent_workspace = settings.AGENT_WORKSPACE

    feature_branch = f"feature/{issue_key}"

    logger.info(f"🔧 Agent '{settings.CURRENT_AGENT_NAME}' is starting setup...")
    logger.info(f"   📍 Source Repo: {target_source_repo}")
    logger.info(f"   📂 Target Workspace: {agent_workspace}")

    try:
        # --- STEP 1: หา Git Remote URL จาก Repo ต้นทาง ---
        if not os.path.exists(target_source_repo):
            return f"❌ Error: Source Repository not found at {target_source_repo}. Check .env configuration."

        # รันคำสั่ง git config ใน folder ต้นทางเพื่อเอา URL
        remote_url = subprocess.check_output(
            "git config --get remote.origin.url",
            shell=True,
            cwd=target_source_repo,
            text=True
        ).strip()

        logger.info(f"🔗 Detected Remote URL: {remote_url}")

        # --- STEP 2: Clone ลง Workspace (ถ้ายังไม่มี) ---
        if not os.path.exists(agent_workspace):
            logger.info(f"📂 Creating Workspace: {agent_workspace}")
            os.makedirs(agent_workspace, exist_ok=True)

            logger.info(f"⬇️ Cloning from {remote_url}...")
            # Clone ลง folder ปัจจุบัน (.)
            subprocess.run(f'git clone "{remote_url}" .', shell=True, cwd=agent_workspace, check=True)
        else:
            logger.info(f"📂 Workspace exists. Using existing repo.")

        # --- STEP 3: Config User (แยกตาม Agent Identity) ---
        agent_name = settings.CURRENT_AGENT_NAME
        subprocess.run(f'git config user.name "{agent_name} AI"', shell=True, cwd=agent_workspace)
        subprocess.run('git config user.email "ai@olympus.dev"', shell=True, cwd=agent_workspace)

        # --- STEP 4: Checkout Process ---
        logger.info("🔄 Fetching updates from remote...")
        subprocess.run("git fetch origin", shell=True, cwd=agent_workspace, check=True)

        # 4.1 Reset กลับไปที่ Base Branch (เช่น main) เพื่อความชัวร์
        # ใช้ -f (force) เพื่อทิ้ง change เก่าที่อาจค้างอยู่
        subprocess.run(f"git checkout -f {base_branch}", shell=True, cwd=agent_workspace, check=True)
        subprocess.run(f"git pull origin {base_branch}", shell=True, cwd=agent_workspace, check=True)

        # 4.2 สร้าง หรือ สลับไปที่ Feature Branch
        logger.info(f"🌿 Switching to branch: {feature_branch}")
        # -B หมายความว่าถ้ามีอยู่แล้วให้ Reset, ถ้าไม่มีให้สร้างใหม่
        subprocess.run(f"git checkout -B {feature_branch}", shell=True, cwd=agent_workspace, check=True)

        return (f"✅ Workspace Ready for {agent_name}!\n"
                f"📂 Location: {agent_workspace}\n"
                f"🌿 Branch: {feature_branch} (based on {base_branch})")

    except subprocess.CalledProcessError as e:
        error_msg = f"❌ Git Setup Failed: Command execution error.\nDetails: {e}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"❌ System Error during git setup: {e}"
        logger.error(error_msg)
        return error_msg


def git_commit(message: str) -> str:
    """Commit changes in the Agent's Workspace"""
    workspace = settings.AGENT_WORKSPACE
    try:
        # Check status ก่อน
        status = subprocess.check_output("git status --porcelain", shell=True, cwd=workspace, text=True)
        if not status:
            return "⚠️ Nothing to commit (Working tree clean)."

        subprocess.run("git add .", shell=True, cwd=workspace, check=True)
        subprocess.run(f'git commit -m "{message}"', shell=True, cwd=workspace, check=True)
        return f"✅ Committed: {message}"
    except Exception as e:
        return f"❌ Commit Failed: {e}"


def git_push(branch_name: str) -> str:
    """Push current branch to remote"""
    workspace = settings.AGENT_WORKSPACE
    try:
        # Safety Check: ห้าม Push main
        if branch_name in ["main", "master"]:
            return "❌ Error: Direct push to main/master is FORBIDDEN by Olympus Protocol."

        # ตรวจสอบว่า Branch ที่จะ Push ตรงกับที่ Checkout อยู่ไหม
        current_branch = subprocess.check_output(
            "git branch --show-current",
            shell=True,
            cwd=workspace,
            text=True
        ).strip()

        if branch_name != current_branch:
            return f"❌ Error: You are on branch '{current_branch}', but tried to push '{branch_name}'."

        cmd = f"git push -u origin {branch_name}"
        result = subprocess.run(cmd, shell=True, cwd=workspace, capture_output=True, text=True)

        if result.returncode == 0:
            return f"✅ Push Success: '{branch_name}' is now on remote."
        else:
            return f"❌ Push Failed:\n{result.stderr}"
    except Exception as e:
        return f"❌ Push Error: {e}"


def create_pr(title: str, body: str, branch: str) -> str:
    """Create Pull Request using GitHub CLI (gh)"""
    workspace = settings.AGENT_WORKSPACE
    try:
        # ตรวจสอบว่ามี gh cli ไหม
        if shutil.which("gh") is None:
            return "❌ Error: GitHub CLI ('gh') is not installed on the host machine."

        cmd = f'gh pr create --title "{title}" --body "{body}" --head "{branch}" --base "main"'
        result = subprocess.run(cmd, shell=True, cwd=workspace, capture_output=True, text=True)

        if result.returncode == 0:
            return f"✅ PR Created: {result.stdout.strip()}"
        elif "already exists" in result.stderr:
            return f"✅ PR already exists for this branch."
        else:
            return f"❌ PR Failed: {result.stderr}"
    except Exception as e:
        return f"❌ PR Error: {e}"
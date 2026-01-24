import subprocess
import os
import logging
import shutil
from core.config import settings

logger = logging.getLogger("GitOps")


def git_setup_workspace(issue_key: str, base_branch: str = "main") -> str:
    """
    Clone Repo จาก URL ลง Workspace โดยตรง ไม่ต้องพึ่ง Local Source Path
    """
    # ✅ ดึง URL จาก Config (QA หรือ Dev ตาม Role Agent)
    remote_url = settings.TARGET_REPO_URL
    agent_workspace = settings.AGENT_WORKSPACE
    feature_branch = f"feature/{issue_key}"

    logger.info(f"🔧 Agent '{settings.CURRENT_AGENT_NAME}' is starting setup...")
    logger.info(f"   🔗 Remote URL: {remote_url}")
    logger.info(f"   📂 Target Workspace: {agent_workspace}")

    try:
        # STEP 1: Clone (ถ้ายังไม่มี)
        if not os.path.exists(agent_workspace):
            logger.info(f"📂 Creating Workspace: {agent_workspace}")
            os.makedirs(agent_workspace, exist_ok=True)
            logger.info(f"⬇️ Cloning from {remote_url}...")
            # Clone ลง folder นี้เลย (.)
            subprocess.run(f'git clone "{remote_url}" .', shell=True, cwd=agent_workspace, check=True)
        else:
            logger.info(f"📂 Workspace exists. Checking remote...")
            # เช็คว่า Remote ตรงกันไหม (กันเหนียว)
            try:
                current_remote = subprocess.check_output("git config --get remote.origin.url", shell=True,
                                                         cwd=agent_workspace, text=True).strip()
                if current_remote != remote_url:
                    return f"❌ Error: Workspace exists but points to wrong remote ({current_remote}). Please delete workspace."
            except:
                pass  # ถ้าเช็คไม่ได้ ให้พยายามทำต่อ

        # STEP 2: Config User
        agent_name = settings.CURRENT_AGENT_NAME
        subprocess.run(f'git config user.name "{agent_name} AI"', shell=True, cwd=agent_workspace)
        subprocess.run('git config user.email "ai@olympus.dev"', shell=True, cwd=agent_workspace)

        # STEP 3: Checkout Base Branch (main) & Pull Latest
        logger.info(f"🔄 Syncing with {base_branch}...")
        subprocess.run("git fetch origin", shell=True, cwd=agent_workspace, check=True)

        # Reset Hard เพื่อความชัวร์ว่า File ไม่ตีกัน
        subprocess.run(f"git checkout -f {base_branch}", shell=True, cwd=agent_workspace, check=True)
        subprocess.run(f"git pull origin {base_branch}", shell=True, cwd=agent_workspace, check=True)

        # STEP 4: Create/Switch Feature Branch
        logger.info(f"🌿 Switching to branch: {feature_branch}")
        subprocess.run(f"git checkout -B {feature_branch}", shell=True, cwd=agent_workspace, check=True)

        return (f"✅ Workspace Ready for {agent_name}!\n"
                f"📂 Location: {agent_workspace}\n"
                f"🌿 Branch: {feature_branch}\n"
                f"🔗 From: {remote_url}")

    except Exception as e:
        logger.error(f"❌ Git Setup Error: {e}")
        return f"❌ Error: {e}"


# ... (ฟังก์ชัน git_commit, git_push, create_pr เหมือนเดิม) ...
# แต่ต้องใส่ import shutil, subprocess, os, logging, settings ให้ครบนะครับ
def git_commit(message: str) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        status = subprocess.check_output("git status --porcelain", shell=True, cwd=workspace, text=True)
        if not status:
            return "⚠️ Nothing to commit (Working tree clean)."

        subprocess.run("git add .", shell=True, cwd=workspace, check=True)
        subprocess.run(f'git commit -m "{message}"', shell=True, cwd=workspace, check=True)
        return f"✅ Committed: {message}"
    except Exception as e:
        return f"❌ Commit Failed: {e}"


def git_push(branch_name: str) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        if branch_name in ["main", "master"]:
            return "❌ Error: Direct push to main/master is FORBIDDEN."

        current_branch = subprocess.check_output("git branch --show-current", shell=True, cwd=workspace,
                                                 text=True).strip()
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


def create_pr(title: str, body: str, branch: str = None) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        if shutil.which("gh") is None:
            return "❌ Error: GitHub CLI ('gh') is not installed."

        if not branch:
            logger.info("🌿 Branch not specified, detecting current branch...")
            branch = subprocess.check_output(
                "git branch --show-current",
                shell=True,
                cwd=workspace,
                text=True
            ).strip()

        cmd = f'gh pr create --title "{title}" --body "{body}" --head "{branch}" --base "main"'
        result = subprocess.run(cmd, shell=True, cwd=workspace, capture_output=True, text=True)

        if result.returncode == 0:
            return f"✅ PR Created: {result.stdout.strip()}"
        elif "already exists" in result.stderr:
            return f"✅ PR already exists for {branch}."
        else:
            return f"❌ PR Failed: {result.stderr}"
    except Exception as e:
        return f"❌ PR Error: {e}"
import subprocess
import os
import logging
import shutil
import re
from core.config import settings

logger = logging.getLogger("GitOps")


# ==============================================================================
# 🔇 HELPER: Safe Command Runner (ป้องกัน Output หลุดไปกวน MCP JSON)
# ==============================================================================
def run_git_cmd(command: str, cwd: str) -> str:
    """
    รันคำสั่ง Git แบบ Capture Output เพื่อไม่ให้หลุดไป stdout (ซึ่งจะทำให้ MCP พัง)
    """
    try:
        # capture_output=True คือหัวใจสำคัญ
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        # ส่ง Log ไปที่ stderr หรือไฟล์ Log แทน
        if result.stdout.strip():
            logger.info(f"   [Git Output]: {result.stdout.strip()[:200]}...")

        if result.returncode != 0:
            # กรณี Error ให้ Raise พร้อมข้อความ
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)

        return result.stdout.strip()

    except Exception as e:
        raise e


# ==============================================================================
# 🔧 GIT SETUP
# ==============================================================================
def git_setup_workspace(issue_key: str, base_branch: str = "main") -> str:
    """
    Setup Workspace: Clone -> Check Remote -> Detect Branch -> Create Feature Branch
    """
    remote_url = settings.TARGET_REPO_URL
    agent_workspace = settings.AGENT_WORKSPACE
    feature_branch = f"feature/{issue_key}"

    logger.info(f"🔧 Agent '{settings.CURRENT_AGENT_NAME}' setup...")
    logger.info(f"   📂 Workspace: {agent_workspace}")

    try:
        # ✅ STEP 0: Safety Check (Zombie Folder Cleanup)
        if os.path.exists(agent_workspace):
            git_folder = os.path.join(agent_workspace, ".git")
            if not os.path.exists(git_folder):
                logger.warning(f"⚠️ Corrupt workspace found (no .git). Deleting...")
                shutil.rmtree(agent_workspace, ignore_errors=True)

        # STEP 1: Clone or Verify Remote
        if not os.path.exists(agent_workspace):
            logger.info(f"⬇️ Cloning repository...")
            os.makedirs(agent_workspace, exist_ok=True)
            run_git_cmd(f'git clone --no-checkout "{remote_url}" .', cwd=agent_workspace)
        else:
            # ✅ RESTORED: ส่วนที่คุณทักท้วงว่าหายไป (เช็คว่า URL ตรงกันไหม)
            try:
                logger.info(f"📂 Workspace exists. Verifying remote...")
                current_remote = run_git_cmd("git config --get remote.origin.url", cwd=agent_workspace)

                # ถ้า URL ไม่ตรง (เช่น Token เปลี่ยน) ให้ลบทิ้งแล้ว Clone ใหม่
                if current_remote != remote_url:
                    logger.warning(f"⚠️ Remote mismatch ({current_remote} != {remote_url}). Re-cloning...")
                    shutil.rmtree(agent_workspace, ignore_errors=True)
                    os.makedirs(agent_workspace, exist_ok=True)
                    run_git_cmd(f'git clone --no-checkout "{remote_url}" .', cwd=agent_workspace)
            except Exception as e:
                logger.warning(f"⚠️ Could not verify remote: {e}. Proceeding anyway.")

        # STEP 2: Detect Default Branch
        logger.info("🕵️ Detecting default branch...")
        output = run_git_cmd("git remote show origin", cwd=agent_workspace)
        match = re.search(r"HEAD branch:\s+(.*)", output)
        base_branch = match.group(1).strip() if match else "main"
        logger.info(f"✅ Base Branch detected: {base_branch}")

        # STEP 3: Config & Checkout
        run_git_cmd(f'git config user.name "{settings.CURRENT_AGENT_NAME}"', cwd=agent_workspace)
        run_git_cmd('git config user.email "ai@olympus.dev"', cwd=agent_workspace)

        run_git_cmd(f"git checkout {base_branch}", cwd=agent_workspace)
        run_git_cmd(f"git pull origin {base_branch}", cwd=agent_workspace)

        # STEP 4: Switch to Feature
        logger.info(f"🌿 Switching to {feature_branch}")
        run_git_cmd(f"git checkout -B {feature_branch}", cwd=agent_workspace)

        return (f"✅ Workspace Ready for {settings.CURRENT_AGENT_NAME}!\n"
                f"📂 Location: {agent_workspace}\n"
                f"🌿 Branch: {feature_branch}\n"
                f"🔗 Base: {base_branch}")

    except Exception as e:
        logger.error(f"❌ Git Setup Error: {e}")
        return f"❌ Error: {e}"


# ==============================================================================
# 📝 OTHER GIT OPERATIONS
# ==============================================================================
def git_commit(message: str) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        status = run_git_cmd("git status --porcelain", cwd=workspace)
        if not status:
            return "⚠️ Nothing to commit."

        run_git_cmd("git add .", cwd=workspace)
        run_git_cmd(f'git commit -m "{message}"', cwd=workspace)
        return f"✅ Committed: {message}"
    except Exception as e:
        return f"❌ Commit Failed: {e}"


def git_push(branch_name: str) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        if branch_name in ["main", "master"]:
            return "❌ Error: Direct push to main/master is FORBIDDEN."

        # ✅ Check Current Branch (ใช้ run_git_cmd เพื่อความปลอดภัย)
        current_branch = run_git_cmd("git branch --show-current", cwd=workspace)

        if branch_name != current_branch:
            return f"❌ Error: You are on branch '{current_branch}', but tried to push '{branch_name}'."

        run_git_cmd(f"git push -u origin {branch_name}", cwd=workspace)
        return f"✅ Push Success: {branch_name}"
    except Exception as e:
        if hasattr(e, 'stderr'):
            return f"❌ Push Failed: {e.stderr}"
        return f"❌ Push Error: {e}"


def git_pull(branch_name: str = None) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        # ✅ Check Current Branch (ถ้าไม่ส่ง branch_name มา)
        if not branch_name:
            branch_name = run_git_cmd("git branch --show-current", cwd=workspace)

        run_git_cmd(f"git pull origin {branch_name} --no-rebase", cwd=workspace)
        return f"✅ Pull Success"
    except Exception as e:
        return f"❌ Pull Error: {e}"


def create_pr(title: str, body: str, branch: str = None) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        if not shutil.which("gh"):
            return "❌ Error: GitHub CLI ('gh') is not installed."

        # ✅ Check Current Branch
        if not branch:
            branch = run_git_cmd("git branch --show-current", cwd=workspace)

        cmd = f'gh pr create --title "{title}" --body "{body}" --head "{branch}" --base "main"'
        output = run_git_cmd(cmd, cwd=workspace)

        return f"✅ PR Created: {output}"
    except Exception as e:
        if "already exists" in str(e):
            return f"✅ PR already exists."
        return f"❌ PR Error: {e}"
import subprocess
import os
import logging
import re
import shutil
from core.config import settings

logger = logging.getLogger("GitOps")


def git_setup_workspace(issue_key: str, base_branch: str = "main") -> str:
    """
    Clone Repo จาก URL ลง Workspace โดยตรง พร้อมระบบ Auto-Detect Branch และ Zombie Folder Cleanup
    """
    # ✅ ดึง URL จาก Config (QA หรือ Dev ตาม Role Agent)
    remote_url = settings.TARGET_REPO_URL
    agent_workspace = settings.AGENT_WORKSPACE
    feature_branch = f"feature/{issue_key}"

    logger.info(f"🔧 Agent '{settings.CURRENT_AGENT_NAME}' is starting setup...")
    logger.info(f"   🔗 Remote URL: {remote_url}")  # Token จะโชว์ใน Log (ระวังเรื่อง Security ใน Prod)
    logger.info(f"   📂 Target Workspace: {agent_workspace}")

    try:
        # ✅ STEP 0: Safety Check (Zombie Folder Cleanup)
        # ถ้ามี Folder อยู่ แต่ข้างในไม่มี .git แสดงว่าเป็นซากปรักหักพัง -> ลบทิ้ง!
        if os.path.exists(agent_workspace):
            git_folder = os.path.join(agent_workspace, ".git")
            if not os.path.exists(git_folder):
                logger.warning(f"⚠️ Found corrupt workspace (no .git). Deleting: {agent_workspace}")
                shutil.rmtree(agent_workspace, ignore_errors=True)

        # STEP 1: Clone (ถ้ายังไม่มี)
        if not os.path.exists(agent_workspace):
            logger.info(f"📂 Creating Workspace: {agent_workspace}")
            os.makedirs(agent_workspace, exist_ok=True)
            logger.info(f"⬇️ Cloning repository...")
            # ใช้ --no-checkout เพื่อโหลด .git มาก่อน แล้วค่อยเลือก Branch ทีหลัง
            subprocess.run(f'git clone --no-checkout "{remote_url}" .', shell=True, cwd=agent_workspace, check=True)
        else:
            logger.info(f"📂 Workspace exists. Checking remote...")
            # เช็คว่า Remote ตรงกันไหม (ถ้าไม่ตรง สั่ง Error ให้คนมาดู)
            try:
                current_remote = subprocess.check_output("git config --get remote.origin.url", shell=True,
                                                         cwd=agent_workspace, text=True).strip()
                # หมายเหตุ: การเช็คตรงนี้อาจจะไม่ผ่านถ้า URL เดิมไม่มี Token แต่ URL ใหม่มี Token
                # แต่ในเคสนี้เรายอมให้ Error เพื่อบังคับให้ใช้ URL แบบมี Token
                if current_remote != remote_url:
                    # ถ้า URL ไม่ตรง (เช่น Token เปลี่ยน) ให้ลบทิ้งแล้ว Clone ใหม่เลยจะง่ายกว่า return Error
                    logger.warning("⚠️ Remote URL mismatch. Re-cloning...")
                    shutil.rmtree(agent_workspace, ignore_errors=True)
                    os.makedirs(agent_workspace, exist_ok=True)
                    subprocess.run(f'git clone --no-checkout "{remote_url}" .', shell=True, cwd=agent_workspace,
                                   check=True)
            except:
                pass

                # STEP 2: Detect Default Branch (แก้ปัญหา main vs master)
        result = subprocess.run("git remote show origin", shell=True, cwd=agent_workspace, capture_output=True,
                                text=True)
        match = re.search(r"HEAD branch:\s+(.*)", result.stdout)
        base_branch = match.group(1).strip() if match else "main"
        logger.info(f"🕵️ Detected Base Branch: {base_branch}")

        # STEP 3: Config & Checkout
        subprocess.run(f'git config user.name "{settings.CURRENT_AGENT_NAME}"', shell=True, cwd=agent_workspace)
        subprocess.run('git config user.email "ai@olympus.dev"', shell=True, cwd=agent_workspace)

        subprocess.run(f"git checkout {base_branch}", shell=True, cwd=agent_workspace, check=True)
        subprocess.run(f"git pull origin {base_branch}", shell=True, cwd=agent_workspace, check=True)

        # STEP 4: Switch to Feature
        logger.info(f"🌿 Switching to feature branch: {feature_branch}")
        subprocess.run(f"git checkout -B {feature_branch}", shell=True, cwd=agent_workspace, check=True)

        # ✅ แก้ agent_name -> settings.CURRENT_AGENT_NAME
        return (f"✅ Workspace Ready for {settings.CURRENT_AGENT_NAME}!\n"
                f"📂 Location: {agent_workspace}\n"
                f"🌿 Branch: {feature_branch}\n"
                f"🔗 Base Branch: {base_branch}")

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


def git_pull(branch_name: str = None) -> str:
    """
    Dulls latest changes from remote.
    Useful when git_push fails due to non-fast-forward updates.
    """
    workspace = settings.AGENT_WORKSPACE
    try:
        # ถ้าไม่ส่ง branch_name มา ให้หาเองจาก current branch
        if not branch_name:
            branch_name = subprocess.check_output(
                "git branch --show-current",
                shell=True,
                cwd=workspace,
                text=True
            ).strip()

        logger.info(f"🔄 Pulling latest changes for {branch_name}...")

        # ใช้ --no-rebase เพื่อให้เห็น merge commit ชัดเจนเวลามี conflict
        cmd = f"git pull origin {branch_name} --no-rebase"
        result = subprocess.run(cmd, shell=True, cwd=workspace, capture_output=True, text=True)

        if result.returncode == 0:
            return f"✅ Pull Success: {result.stdout.strip()}"
        else:
            # กรณีมี Conflict หรือ Error อื่นๆ
            return f"❌ Pull Failed (Conflict?): {result.stderr.strip()}"

    except Exception as e:
        return f"❌ Pull Error: {e}"
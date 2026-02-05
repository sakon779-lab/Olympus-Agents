import sys          # <--- อย่าลืม!
import subprocess   # <--- อย่าลืม!
import os
import logging
import shutil
import re
from core.config import settings
from core.tools.cmd_ops import run_command

logger = logging.getLogger("GitOps")


# ==============================================================================
# 🔇 HELPER: Safe Command Runner (Quiet + Nuclear Anti-Popup)
# ==============================================================================
# แก้ไขฟังก์ชัน run_git_cmd ให้มี Timeout และปิด Input
def run_git_cmd(command: str, cwd: str, timeout: int = 60) -> str:
    """
    รัน Git แบบปิดปาก + ปิดหู (No Input) + มีเวลาตาย (Timeout)
    """
    try:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        env["GIT_ASKPASS"] = "echo"
        env["SSH_ASKPASS"] = "echo"

        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            input="",  # ⛔ ไม้ตาย 1: ปิดรับ Input (ตัดปัญหา Git รอพิมพ์)
            timeout=timeout  # ⛔ ไม้ตาย 2: ถ้าเกิน 60 วิ ให้ฆ่าทิ้งแล้วฟ้อง Error
        )

        if result.stdout.strip():
            logger.info(f"   [Git Output]: {result.stdout.strip()[:200]}...")

        if result.returncode != 0:
            logger.error(f"❌ Git Command Failed: {command}")
            logger.error(f"   Stderr: {result.stderr}")
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)

        return result.stdout.strip()

    except subprocess.TimeoutExpired as e:
        # 🚨 จับได้แล้ว! ถ้ามันค้าง มันจะมาตกที่นี่
        logger.error(f"⏰ Git Timeout ({timeout}s): {command}")
        logger.error(f"   Stderr (Before kill): {e.stderr}")  # ดูว่ามันบ่นอะไรก่อนตาย
        # ลองลบ Folder ทิ้งเลยเผื่อไฟล์ Lock
        if os.path.exists(cwd) and "clone" in command:
            shutil.rmtree(cwd, ignore_errors=True)
        raise e
    except Exception as e:
        raise e


# ==============================================================================
# 🔧 GIT SETUP
# ==============================================================================
def git_setup_workspace(issue_key: str, base_branch: str = "main") -> str:
    remote_url = settings.TARGET_REPO_URL
    agent_workspace = settings.AGENT_WORKSPACE
    feature_branch = f"feature/{issue_key}"

    logger.info(f"🔧 Agent '{settings.CURRENT_AGENT_NAME}' setup...")
    logger.info(f"   📂 Workspace: {agent_workspace}")

    try:
        # STEP 0: Zombie Cleanup
        if os.path.exists(agent_workspace):
            git_folder = os.path.join(agent_workspace, ".git")
            if not os.path.exists(git_folder):
                logger.warning(f"⚠️ Corrupt workspace found. Deleting...")
                shutil.rmtree(agent_workspace, ignore_errors=True)

        # STEP 1: Clone (Quiet Mode + No Credential Helper)
        if not os.path.exists(agent_workspace):
            logger.info(f"⬇️ Cloning repository...")
            os.makedirs(agent_workspace, exist_ok=True)

            # ✅ FIX: เพิ่ม --quiet เพื่อแก้ปัญหาท่อตัน
            cmd = f'git clone --quiet -c credential.helper= --no-checkout "{remote_url}" .'
            run_git_cmd(cmd, cwd=agent_workspace)
        else:
            try:
                logger.info(f"📂 Workspace exists. Verifying remote...")
                current_remote = run_git_cmd("git config --get remote.origin.url", cwd=agent_workspace)
                if settings.GITHUB_TOKEN and settings.GITHUB_TOKEN not in current_remote:
                    logger.warning(f"⚠️ Remote token mismatch. Re-cloning...")
                    shutil.rmtree(agent_workspace, ignore_errors=True)
                    os.makedirs(agent_workspace, exist_ok=True)
                    cmd = f'git clone --quiet -c credential.helper= --no-checkout "{remote_url}" .'
                    run_git_cmd(cmd, cwd=agent_workspace)
            except Exception as e:
                logger.warning(f"⚠️ Remote check skipped: {e}")

        # STEP 2: Detect Branch
        logger.info("🕵️ Detecting branch...")
        output = run_git_cmd("git -c credential.helper= remote show origin", cwd=agent_workspace)
        match = re.search(r"HEAD branch:\s+(.*)", output)
        base_branch = match.group(1).strip() if match else "main"
        logger.info(f"✅ Base Branch: {base_branch}")

        # STEP 3: Config & Checkout
        run_git_cmd(f'git config user.name "{settings.CURRENT_AGENT_NAME}"', cwd=agent_workspace)
        run_git_cmd('git config user.email "ai@olympus.dev"', cwd=agent_workspace)

        run_git_cmd(f"git checkout {base_branch}", cwd=agent_workspace)
        run_git_cmd(f"git -c credential.helper= pull --quiet origin {base_branch}", cwd=agent_workspace)

        # STEP 4: Switch to Feature
        logger.info(f"🌿 Switching to {feature_branch}")
        # -B จะ reset branch pointer ใหม่เสมอ (เหมือนเริ่มใหม่ทุกครั้ง) เหมาะกับ Agent มาก
        run_git_cmd(f"git checkout -B {feature_branch}", cwd=agent_workspace)

        # =========================================================
        # 🆕 SYSTEM: Auto-Create Venv (Powered by run_command)
        # =========================================================
        venv_path = os.path.join(agent_workspace, ".venv")

        if not os.path.exists(venv_path):
            logger.info(f"📦 Creating virtual environment at: {venv_path}...")

            # 💡 TRICK: ใช้ sys.executable เพื่อเรียก Python ตัวเดียวกับที่รัน Agent
            # ใส่ฟันหนู "" ครอบ Path กันกรณีมีเว้นวรรค (เช่น C:\Program Files\...)
            create_cmd = f'"{sys.executable}" -m venv .venv'

            # เรียกใช้ run_command ตัวเก่งของคุณ
            result = run_command(create_cmd, cwd=agent_workspace, timeout=300)

            if "Success" in result:
                logger.info("✅ .venv created successfully!")

                # =========================================================
                # 🛡️ OPTION: สร้างเกราะป้องกัน pip --user (ใส่ตรงนี้เลย!)
                # =========================================================
                if os.name == 'nt':  # เฉพาะ Windows
                    try:
                        pip_ini_path = os.path.join(venv_path, "pip.ini")
                        with open(pip_ini_path, "w") as f:
                            f.write("[global]\nuser = false\n")
                        logger.info("🛡️ pip.ini created: Blocked '--user' install.")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to create pip.ini: {e}")
                # =========================================================
            else:
                logger.error(f"⚠️ Failed to create .venv: {result}")
                # (Optional) ถ้าซีเรียสมาก ให้ return Error กลับไปเลย
        else:
            logger.info("ℹ️ .venv already exists.")

        # ✅ STEP 5: Auto-Install Dependencies (Updated to use run_command)
        req_file = os.path.join(agent_workspace, "requirements.txt")
        if os.path.exists(req_file):
            logger.info(f"📦 Found requirements.txt. Installing dependencies...")

            # เลือก pip ให้ถูกตัว
            if os.name == 'nt':
                pip_cmd = os.path.join(agent_workspace, ".venv", "Scripts", "pip.exe")
            else:
                pip_cmd = os.path.join(agent_workspace, ".venv", "bin", "pip")

            # สร้าง Command
            # 💡 เพิ่ม --no-cache-dir เพื่อลดปัญหาพื้นที่เต็มและไฟล์ขยะ
            install_cmd = f'"{pip_cmd}" install --no-cache-dir -r requirements.txt'

            # 🔥 เรียกใช้ run_command แทน subprocess
            # ให้เวลา 600 วินาที (10 นาที) เผื่อเน็ตช้าหรือต้อง Compile library ใหญ่ๆ
            result = run_command(install_cmd, cwd=agent_workspace, timeout=600)

            # เช็คผลลัพธ์ (run_command มักจะคืนค่า text ออกมา ไม่ได้ raise error ตรงๆ)
            # ขึ้นอยู่กับ implementation ของ run_command แต่ปกติถ้า error มันจะฟ้องใน text
            if "Error" not in result and "Failed" not in result:
                logger.info("✅ Dependencies installed successfully!")
            else:
                logger.error(f"❌ Failed to install dependencies. Output:\n{result}")

        return (f"✅ Workspace Ready!\n"
                f"📂 Location: {agent_workspace}\n"
                f"🌿 Branch: {feature_branch}\n"
                f"🔗 Base: {base_branch}\n"
                f"📦 Venv: Configured & Packages Installed")

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
    """
    Pushes changes to remote.
    🤖 SMART LOGIC: If a normal push fails (non-fast-forward) on a feature branch,
    it automatically attempts a FORCE PUSH to overwrite the stale remote branch.
    """
    workspace = settings.AGENT_WORKSPACE

    # 1. เช็ค Branch ปัจจุบัน
    try:
        current_branch = run_git_cmd("git branch --show-current", cwd=workspace)
        if branch_name != current_branch:
            return f"❌ Error: You are on branch '{current_branch}', but tried to push '{branch_name}'."
    except Exception as e:
        return f"❌ Git Error: {e}"

    # 2. ลอง Push แบบปกติ (Standard Push)
    cmd = f"git -c credential.helper= push -u origin {branch_name}"
    result = run_git_cmd(cmd, cwd=workspace)

    # 3. 🚨 เช็คว่าพังไหม? (Auto-Recovery Logic)
    # ถ้า Error บอกว่า [rejected] ... (non-fast-forward)
    if "error" in result.lower() and "non-fast-forward" in result.lower():

        # 🛡️ Safety Guard: ห้าม Force Push ใส่ Main/Master เด็ดขาด!
        if branch_name in ["main", "master", "production"]:
            return f"❌ Push Failed: Remote branch is ahead. Please 'git_pull' first. (Force push blocked on {branch_name})"

        # ⚡ EXECUTE FORCE PUSH (แก้ปัญหา Stale Remote)
        print(f"⚠️ Git Push Failed (Non-fast-forward). Attempting FORCE PUSH on feature branch '{branch_name}'...")

        force_cmd = f"git -c credential.helper= push -f -u origin {branch_name}"
        force_result = run_git_cmd(force_cmd, cwd=workspace)

        if "error" not in force_result.lower():
            return f"✅ Push Success (Forced Update): {branch_name} has been overwritten with your latest code."
        else:
            return f"❌ Force Push Failed: {force_result}"

    # ถ้า Push ปกติผ่าน หรือ Error เรื่องอื่น
    return result


def git_pull(branch_name: str = None) -> str:
    workspace = settings.AGENT_WORKSPACE
    try:
        # ✅ Check Current Branch (ถ้าไม่ส่ง branch_name มา)
        if not branch_name:
            branch_name = run_git_cmd("git branch --show-current", cwd=workspace)

        run_git_cmd(f"git -c credential.helper= pull origin {branch_name} --no-rebase", cwd=workspace)
        return f"✅ Pull Success"
    except Exception as e:
        return f"❌ Pull Error: {e}"


def create_pr(title: str, body: str = "Automated PR by Hephaestus", base_branch: str = "main",
              head_branch: str = None) -> str:
    """
    Creates a Pull Request using GitHub CLI (gh).
    Supports defining base_branch and head_branch explicitly.
    """
    workspace = settings.AGENT_WORKSPACE
    try:
        if not shutil.which("gh"):
            return "❌ Error: GitHub CLI ('gh') is not installed."

        # ✅ 1. Determine Head Branch (Source)
        # ถ้า AI ไม่ส่ง head_branch มา ให้ใช้ Current Branch
        if not head_branch:
            head_branch = run_git_cmd("git branch --show-current", cwd=workspace).strip()

        # ✅ 2. Construct Command
        # รับค่า base_branch มาจาก Argument (Default='main')
        cmd = f'gh pr create --title "{title}" --body "{body}" --head "{head_branch}" --base "{base_branch}"'

        logger.info(f"🔀 Creating PR: {head_branch} -> {base_branch}")
        output = run_git_cmd(cmd, cwd=workspace)

        return f"✅ PR Created: {output}"

    except Exception as e:
        error_msg = str(e).lower()
        if "already exists" in error_msg:
            return f"⚠️ PR already exists (Skipped creation)."
        if "no commits between" in error_msg:
            return f"⚠️ No changes to merge (Skipped creation)."

        return f"❌ PR Error: {e}"
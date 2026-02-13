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


def _get_current_branch() -> str:
    """Helper to get current branch name."""
    try:
        return run_git_cmd("git branch --show-current", cwd=settings.AGENT_WORKSPACE).strip()
    except:
        return None

# ==============================================================================
# 🔧 GIT SETUP
# ==============================================================================
def git_setup_workspace(issue_key: str, base_branch: str = "main", agent_name: str = "ai-agent",
                        job_id: str = None) -> str:
    remote_url = settings.TARGET_REPO_URL
    agent_workspace = settings.AGENT_WORKSPACE

    # ✅ สูตรการตั้งชื่อ Branch (เหมือนเดิม)
    if job_id:
        feature_branch = f"feature/{issue_key}-{agent_name}-{job_id}"
    else:
        feature_branch = f"feature/{issue_key}-{agent_name}"

    logger.info(f"🔧 Agent '{agent_name}' setup...")
    logger.info(f"🌿 Job ID: {job_id}")
    logger.info(f"   📂 Workspace: {agent_workspace}")
    logger.info(f"   🌿 Target Branch: {feature_branch}")

    try:
        # STEP 0: Zombie Cleanup (เหมือนเดิม)
        if os.path.exists(agent_workspace):
            git_folder = os.path.join(agent_workspace, ".git")
            if not os.path.exists(git_folder):
                logger.warning(f"⚠️ Corrupt workspace found. Deleting...")
                shutil.rmtree(agent_workspace, ignore_errors=True)

        # STEP 1: Clone (เหมือนเดิม)
        if not os.path.exists(agent_workspace):
            logger.info(f"⬇️ Cloning repository...")
            os.makedirs(agent_workspace, exist_ok=True)
            cmd = f'git clone --quiet -c credential.helper= --no-checkout "{remote_url}" .'
            run_git_cmd(cmd, cwd=agent_workspace)
        else:
            try:
                # Verify remote (เหมือนเดิม)
                current_remote = run_git_cmd("git config --get remote.origin.url", cwd=agent_workspace)
                if settings.GITHUB_TOKEN and settings.GITHUB_TOKEN not in current_remote:
                    logger.warning(f"⚠️ Remote token mismatch. Re-cloning...")
                    shutil.rmtree(agent_workspace, ignore_errors=True)
                    os.makedirs(agent_workspace, exist_ok=True)
                    cmd = f'git clone --quiet -c credential.helper= --no-checkout "{remote_url}" .'
                    run_git_cmd(cmd, cwd=agent_workspace)
            except Exception as e:
                pass

        # STEP 2: Detect Base Branch (Auto-detect logic)
        logger.info("🕵️ Detecting base branch...")
        try:
            output = run_git_cmd("git -c credential.helper= remote show origin", cwd=agent_workspace)
            match = re.search(r"HEAD branch:\s+(.*)", output)
            if match:
                base_branch = match.group(1).strip()
        except:
            pass  # ถ้าหาไม่เจอ ใช้ default ที่ส่งมา ("main")

        logger.info(f"✅ Base Branch: {base_branch}")

        # STEP 3: Config User (เหมือนเดิม)
        run_git_cmd(f'git config user.name "{settings.CURRENT_AGENT_NAME}"', cwd=agent_workspace)
        run_git_cmd('git config user.email "ai@olympus.dev"', cwd=agent_workspace)

        # ---------------------------------------------------------
        # 🚀 OPTIMIZED GIT FLOW (แก้ตรงนี้!)
        # ---------------------------------------------------------
        # 1. ดึงข้อมูลล่าสุดจาก Server มาเก็บไว้ใน .git (ไม่แตะไฟล์งาน)
        logger.info(f"📡 Fetching latest {base_branch} from remote...")
        run_git_cmd(f"git fetch origin {base_branch}", cwd=agent_workspace)

        # 2. สร้าง Feature Branch ใหม่ โดยให้เริ่มจาก origin/{base_branch} ทันที
        # -B : Force create/reset branch (ถ้ามีอยู่แล้วก็ทับเลย)
        # origin/{base_branch} : ต้นฉบับจาก Server (สดใหม่แน่นอน)
        logger.info(f"🌿 Creating/Resetting {feature_branch} from origin/{base_branch}")
        run_git_cmd(f"git checkout -B {feature_branch} origin/{base_branch}", cwd=agent_workspace)
        # ---------------------------------------------------------

        # =========================================================
        # 🆕 SYSTEM: Auto-Create Venv (เหมือนเดิม)
        # =========================================================
        venv_path = os.path.join(agent_workspace, ".venv")

        if not os.path.exists(venv_path):
            logger.info(f"📦 Creating virtual environment...")
            create_cmd = f'"{sys.executable}" -m venv .venv'
            result = run_command(create_cmd, cwd=agent_workspace, timeout=300)

            if "Success" in result:
                if os.name == 'nt':
                    try:
                        pip_ini_path = os.path.join(venv_path, "pip.ini")
                        with open(pip_ini_path, "w") as f:
                            f.write("[global]\nuser = false\n")
                    except:
                        pass

        # ✅ STEP 5: Auto-Install Dependencies (เหมือนเดิม)
        req_file = os.path.join(agent_workspace, "requirements.txt")
        if os.path.exists(req_file):
            logger.info(f"📦 Installing dependencies...")
            if os.name == 'nt':
                pip_cmd = os.path.join(agent_workspace, ".venv", "Scripts", "pip.exe")
            else:
                pip_cmd = os.path.join(agent_workspace, ".venv", "bin", "pip")

            install_cmd = f'"{pip_cmd}" install --no-cache-dir -r requirements.txt'
            run_command(install_cmd, cwd=agent_workspace, timeout=600)

        return (f"✅ Workspace Ready!\n"
                f"📂 Location: {agent_workspace}\n"
                f"🌿 Branch: {feature_branch} (Based on origin/{base_branch})\n"
                f"📦 Venv: Configured")

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


def git_push(branch_name: str = None) -> str:
    """
    Push to remote.
    🤖 SMART: Auto-detects branch if None. Handles Force Push for feature branches.
    """
    workspace = settings.AGENT_WORKSPACE

    # ✅ 1. Auto-Detect Branch
    if not branch_name:
        branch_name = _get_current_branch()
        if not branch_name:
            return "❌ Error: Could not detect current branch. Please provide branch_name."

    # 2. Safety Check (Prevent pushing to protected branches directly if force needed)
    is_protected = branch_name in ["main", "master", "production"]

    # 3. Try Standard Push
    try:
        cmd = f"git -c credential.helper= push -u origin {branch_name}"
        result = run_git_cmd(cmd, cwd=workspace)

        # Check specific error from our helper
        if "ERROR_NON_FAST_FORWARD" in result:
            raise subprocess.CalledProcessError(1, cmd, output=result, stderr=result)

        return f"✅ Push Success: {branch_name}"

    except subprocess.CalledProcessError as e:
        # 4. Handle Non-Fast-Forward (Force Push)
        err_msg = e.stderr.lower() if e.stderr else ""
        if "non-fast-forward" in err_msg or "fetch first" in err_msg:

            if is_protected:
                return f"❌ Push Failed: Remote is ahead. Please 'git_pull' first. (Force push blocked on {branch_name})"

            # 🔥 Force Push for Feature Branch
            logger.warning(f"⚠️ Non-fast-forward detected. Force pushing to {branch_name}...")
            try:
                force_cmd = f"git -c credential.helper= push -f -u origin {branch_name}"
                run_git_cmd(force_cmd, cwd=workspace)
                return f"✅ Push Success (Forced): {branch_name} updated."
            except Exception as fe:
                return f"❌ Force Push Failed: {fe}"

        return f"❌ Push Error: {e}"
    except Exception as e:
        return f"❌ Push Error: {e}"


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
import subprocess
import os
import shutil

def git_commit(message: str, cwd: str = os.getcwd()) -> str:
    try:
        subprocess.run("git add .", shell=True, cwd=cwd, check=True)
        result = subprocess.run(
            f'git commit -m "{message}"', shell=True, cwd=cwd, capture_output=True, text=True
        )
        if result.returncode == 0:
            return f"✅ Git Commit Success: {message}"
        return f"⚠️ Git Commit Warning: {result.stdout} {result.stderr}"
    except Exception as e:
        return f"❌ Git Commit Error: {e}"

def git_push(branch_name: str, cwd: str = os.getcwd()) -> str:
    try:
        cmd = f"git push -u origin {branch_name}"
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        if result.returncode == 0:
            return f"✅ Git Push Success: {branch_name}"
        return f"❌ Git Push Failed: {result.stderr}"
    except Exception as e:
        return f"❌ Git Push Error: {e}"

def create_pr(title: str, body: str, cwd: str = os.getcwd()) -> str:
    if not shutil.which("gh"):
        return "❌ Error: GitHub CLI ('gh') is not installed."
    try:
        cmd = f'gh pr create --title "{title}" --body "{body}" --base main'
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        if result.returncode == 0:
            return f"✅ PR Created: {result.stdout.strip()}"
        return f"❌ PR Creation Failed: {result.stderr}"
    except Exception as e:
        return f"❌ PR Error: {e}"


def git_setup_workspace(
        repo_url: str,
        branch_name: str,
        base_branch: str = "main",
        cwd: str = os.getcwd(),
        git_username: str = "AI Agent",  # Default generic
        git_email: str = "ai@olympus.local"
) -> str:
    """เตรียม Workspace: Clone -> Config -> Checkout"""
    try:
        # 1. Clone if not exists
        if not os.path.exists(os.path.join(cwd, ".git")):
            subprocess.run(f'git clone "{repo_url}" .', shell=True, cwd=cwd, check=True)

        # 2. Config Git User (ใช้ค่าที่ส่งมา ไม่ Hardcode แล้ว)
        subprocess.run(f'git config user.name "{git_username}"', shell=True, cwd=cwd, check=True)
        subprocess.run(f'git config user.email "{git_email}"', shell=True, cwd=cwd, check=True)

        # 3. Fetch & Checkout Base
        subprocess.run(f"git fetch origin", shell=True, cwd=cwd, check=True, capture_output=True)
        subprocess.run(f"git checkout {base_branch}", shell=True, cwd=cwd, check=True, capture_output=True)
        subprocess.run(f"git pull origin {base_branch}", shell=True, cwd=cwd, capture_output=True)

        # 4. Create/Switch to Feature Branch
        subprocess.run(f"git checkout -B {branch_name}", shell=True, cwd=cwd, check=True, capture_output=True)

        return f"✅ Workspace Ready: Checked out '{branch_name}' (User: {git_username})."
    except Exception as e:
        return f"❌ Git Setup Failed: {e}"
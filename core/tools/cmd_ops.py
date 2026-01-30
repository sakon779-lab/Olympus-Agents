import subprocess
import os
import logging
from core.config import settings

# Setup Logger
logger = logging.getLogger("CmdOps")


def run_command(command: str, cwd: str = None, timeout: int = 300) -> str:
    """
    รันคำสั่ง Shell แบบปลอดภัย (Safe & Smart Execution)
    - Auto-load .venv
    - Prevent Hanging (Timeout + No Input)
    - Fix Encoding (UTF-8)
    """
    # 1. ถ้าไม่ส่ง cwd มา ให้ใช้ Workspace ของ Agent เป็นหลัก
    if not cwd:
        cwd = settings.AGENT_WORKSPACE

    # Security Check (Basic)
    forbidden = ["rm -rf /", "format c:"]
    if any(f in command.lower() for f in forbidden):
        return "❌ Error: Command not allowed."

    # เช็คว่า Folder มีอยู่จริงไหม
    if not os.path.exists(cwd):
        return f"❌ Error: Directory not found: {cwd}"

    logger.info(f"⚡ Executing: {command} (in {cwd})")

    try:
        # 2. เตรียม Environment (สูตรแก้ค้าง + ภาษาไทย)
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"  # บังคับ UTF-8
        env["PIP_NO_INPUT"] = "1"  # ห้าม pip ถาม

        # เพิ่ม PYTHONPATH ให้ Python ใน Sandbox มองเห็น module
        env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")

        # =========================================================
        # 🛡️ VENV AUTO-LOADER (พระเอกขี่ม้าขาว)
        # =========================================================
        venv_path = os.path.join(cwd, ".venv")

        if os.path.exists(venv_path):
            if os.name == 'nt':  # Windows
                venv_scripts = os.path.join(venv_path, "Scripts")
            else:  # Linux/Mac
                venv_scripts = os.path.join(venv_path, "bin")

            # ยัดเข้า PATH เป็นลำดับแรก (บังคับใช้ venv)
            if os.path.exists(venv_scripts):
                env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")
                env["VIRTUAL_ENV"] = venv_path
                # logger.info(f"🔌 Auto-activated venv: {venv_path}")
        # =========================================================

        # 3. รันคำสั่งจริง
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding='utf-8',  # ✅ สำคัญมากสำหรับ Windows
            errors='replace',  # ✅ กันโปรแกรมพังเพราะ Emoji/ภาษาไทย
            env=env,  # ✅ ใช้ Env ที่ปรุงรสแล้ว
            input="",  # ✅ กันค้าง (Input Blocking)
            timeout=timeout  # ✅ กันค้าง (Timeout)
        )

        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode == 0:
            return f"✅ Command Success:\n{output}"
        else:
            return f"❌ Command Failed (Exit Code {result.returncode}):\n{output}\nERROR LOG:\n{error}"

    except subprocess.TimeoutExpired:
        return f"⏰ Command Timeout! (Over {timeout}s). Process killed."
    except Exception as e:
        return f"❌ Execution Error: {e}"
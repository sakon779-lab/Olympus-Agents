import os
import logging
from core.config import settings

# Setup Logger
logger = logging.getLogger("FileOps")


def _get_safe_path(file_path: str) -> str:
    """
    Ensure path is within AGENT_WORKSPACE
    """
    # 1. ดึงค่า Workspace ปัจจุบัน (ซึ่งเปลี่ยนไปตาม Agent Identity)
    base_dir = settings.AGENT_WORKSPACE

    # 2. แปลงเป็น Absolute Path เพื่อความชัวร์
    safe_base = os.path.abspath(base_dir)
    full_path = os.path.abspath(os.path.join(base_dir, file_path))

    # 3. Debug Print (จะโชว์ใน Console)
    # print(f"[DEBUG] FileOps Target: {full_path} (Base: {safe_base})")

    # 4. Security Check: ป้องกันการเขียนไฟล์นอก Workspace
    if not full_path.startswith(safe_base):
        raise ValueError(f"❌ Access Denied: Path '{file_path}' attempts to escape sandbox ({safe_base}).")

    return full_path


def read_file(file_path: str) -> str:
    try:
        full_path = _get_safe_path(file_path)
        if not os.path.exists(full_path):
            return f"❌ Error: File not found at {full_path}"
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"❌ Error reading file: {e}"


def write_file(file_path: str, content: str) -> str:
    try:
        full_path = _get_safe_path(file_path)

        # สร้าง Folder ถ้ายังไม่มี
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"💾 File Written to: {full_path}")
        return f"✅ File Written: {full_path}"
    except Exception as e:
        return f"❌ Error writing file: {e}"


def append_file(file_path: str, content: str) -> str:
    try:
        full_path = _get_safe_path(file_path)
        if not os.path.exists(full_path):
            return f"❌ Error: File {full_path} does not exist. Use write_file first."

        with open(full_path, "a", encoding="utf-8") as f:
            f.write("\n" + content)

        logger.info(f"➕ File Appended to: {full_path}")
        return f"✅ File Appended: {full_path}"
    except Exception as e:
        return f"❌ Error appending file: {e}"


def list_files(directory: str = ".") -> str:
    try:
        target_dir = _get_safe_path(directory)
        files = []

        if not os.path.exists(target_dir):
            return "📂 Directory is empty or does not exist."

        for root, _, filenames in os.walk(target_dir):
            if ".git" in root or "__pycache__" in root: continue
            for filename in filenames:
                rel_path = os.path.relpath(os.path.join(root, filename), settings.AGENT_WORKSPACE)
                files.append(rel_path)

        if not files: return "📂 No files found in workspace."
        return "\n".join(files[:100])
    except Exception as e:
        return f"❌ Error listing files: {e}"
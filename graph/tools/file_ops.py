import os
from langchain_core.tools import tool

# กำหนด Root Project เพื่อความปลอดภัย (ไม่ให้ AI ออกไปยุ่งนอกโปรเจกต์)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@tool
def read_file(file_path: str):
    """
    Read content of a file. Path should be relative to project root.
    Example: 'payment_core/models.py'
    """
    full_path = os.path.join(BASE_DIR, file_path)
    try:
        if not os.path.exists(full_path):
            return f"Error: File not found at {file_path}"
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool
def write_file(file_path: str, content: str):
    """
    Create or Overwrite a file with content.
    Useful for creating new modules or updating code.
    Example: 'payment_core/services.py'
    """
    full_path = os.path.join(BASE_DIR, file_path)
    try:
        # สร้าง folder ถ้ายังไม่มี
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


@tool
def list_directory(dir_path: str = "."):
    """
    List files and folders in a directory.
    """
    full_path = os.path.join(BASE_DIR, dir_path)
    try:
        if not os.path.exists(full_path):
            return f"Error: Directory not found."

        items = os.listdir(full_path)
        # กรองพวก .git, .venv, __pycache__ ออกจะได้ไม่รก
        items = [i for i in items if i not in ['.git', '.venv', '__pycache__', '.idea', 'pg_data']]
        return "\n".join(items)
    except Exception as e:
        return f"Error listing directory: {str(e)}"
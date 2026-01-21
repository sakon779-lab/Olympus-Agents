import os

def read_file(file_path: str, workspace_root: str = os.getcwd()) -> str:
    """อ่านไฟล์จาก Workspace"""
    try:
        full_path = os.path.join(workspace_root, file_path)
        if not os.path.exists(full_path):
            return f"❌ Error: File not found: {file_path}"
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"❌ Error reading file: {e}"

def write_file(file_path: str, content: str, workspace_root: str = os.getcwd()) -> str:
    """เขียนไฟล์ลง Workspace"""
    try:
        full_path = os.path.join(workspace_root, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ File Written: {file_path}"
    except Exception as e:
        return f"❌ Error writing file: {e}"

# ✅ เพิ่มฟังก์ชันนี้
def append_file(file_path: str, content: str, workspace_root: str = os.getcwd()) -> str:
    """ต่อท้ายไฟล์ (Append)"""
    try:
        full_path = os.path.join(workspace_root, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "a", encoding="utf-8") as f:
            f.write("\n\n" + content)
        return f"✅ Appended to: {file_path}"
    except Exception as e:
        return f"❌ Error appending file: {e}"

def list_files(directory: str = ".", workspace_root: str = os.getcwd()) -> str:
    """แสดงรายการไฟล์"""
    try:
        target_dir = os.path.join(workspace_root, directory)
        files_list = []
        for root, dirs, files in os.walk(target_dir):
            if ".git" in root or ".venv" in root or "__pycache__" in root:
                continue
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), workspace_root)
                files_list.append(rel_path)
        return "\n".join(files_list[:50])
    except Exception as e:
        return f"❌ Error listing files: {e}"
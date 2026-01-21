import os

# กำหนด Base Directory เป็น Root ของโปรเจกต์
BASE_DIR = os.path.abspath(os.getcwd())


def list_files(directory: str = ".") -> str:
    """
    List files in the directory.
    VERSION: DEBUG & SAFETY CUT (Max 100 files)
    """
    target_dir = os.path.join(BASE_DIR, directory)

    if not os.path.exists(target_dir):
        return f"Error: Directory '{directory}' not found."

    file_list = []
    # รายชื่อโฟลเดอร์ที่ต้องยกเว้น (เพิ่ม debug folder หรือ tmp เข้าไปเผื่อไว้)
    ignore_dirs = {
        '.git', '__pycache__',
        'venv', '.venv', 'env', '.env', 'Lib', 'site-packages',  # Python Env
        '.idea', '.vscode',  # IDE
        'node_modules',  # Node
        'chroma_db', 'pg_data',  # DB
        'alembic', 'migrations',  # DB
        'bin', 'obj', 'build', 'dist',  # Build artifacts
        'tmp', 'temp', 'logs', 'coverage'  # Misc
    }

    print(f"DEBUG: Start listing files in {target_dir}")  # Debug Print

    try:
        count = 0
        for root, dirs, files in os.walk(target_dir):
            # กรองโฟลเดอร์ขยะออก
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            # Debug: ดูว่ากำลังเดินเข้าไปในโฟลเดอร์ไหน
            # print(f"DEBUG: Scanning dir -> {os.path.relpath(root, BASE_DIR)}")

            for file in files:
                if file.endswith('.pyc') or file.endswith('.DS_Store') or file.endswith('.log'):
                    continue

                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, BASE_DIR)
                file_list.append(rel_path)

                count += 1
                if count >= 100:  # 🚨 HARD LIMIT: หยุดทันทีเมื่อครบ 100 ไฟล์
                    print("DEBUG: 🛑 Hit limit of 100 files. Stopping scan.")
                    break

            if count >= 100:
                break

        result_text = "\n".join(file_list)
        if count >= 100:
            result_text += "\n\n( ... List truncated at 100 files for safety ... )"

        print(f"DEBUG: Total files found: {count}")
        return result_text

    except Exception as e:
        return f"Error listing files: {str(e)}"


def read_file(file_path: str) -> str:
    """Read content of a specific file."""
    target_path = os.path.join(BASE_DIR, file_path)
    if not os.path.exists(target_path):
        return f"Error: File '{file_path}' not found."
    try:
        with open(target_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) > 5000:  # ลดลิมิตลงเหลือ 5000 ตัวอักษร
                return content[:5000] + "\n\n# ... [Content Truncated] ..."
            return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


def write_file(file_path: str, content: str) -> str:
    target_path = os.path.join(BASE_DIR, file_path)
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to '{file_path}'"
    except Exception as e:
        return f"Error writing file: {str(e)}"

# --- Test Block (สำหรับรันเช็คเอง) ---
if __name__ == "__main__":
    # ลอง List file ดู
    print("📂 Files in project:")
    print(list_files())

    # ลองเขียนไฟล์ Test
    print("\n✍️ Testing Write...")
    print(write_file("temp_test_agent.txt", "Hello from Local Agent!"))

    # ลองอ่านไฟล์ Test
    print("\n📖 Testing Read...")
    print(read_file("temp_test_agent.txt"))

    # ลบไฟล์ Test ทิ้ง
    os.remove("temp_test_agent.txt")
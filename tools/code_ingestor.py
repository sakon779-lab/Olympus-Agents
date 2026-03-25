import ast
import os
import json
import logging
from pathlib import Path

# ตั้งค่า Logger เบื้องต้น
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("CodeIngestor")


class PythonCodeVisitor(ast.NodeVisitor):
    def __init__(self, file_path, source_code, epic_key):
        self.file_path = str(file_path)
        self.source_code = source_code
        self.epic_key = epic_key
        self.extracted_data = []

    def visit_FunctionDef(self, node):
        """ทำงานเมื่อเจอการประกาศฟังก์ชัน (def)"""
        func_name = node.name
        docstring = ast.get_docstring(node)

        # ดึงเนื้อหาโค้ด (ครอบด้วย try-except เผื่อ Python เวอร์ชันเก่า)
        try:
            raw_code = ast.get_source_segment(self.source_code, node)
        except Exception:
            raw_code = ""

        # ค้นหาฟังก์ชันอื่นที่ถูกเรียกใช้ข้างใน (Dependencies)
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)

        self.extracted_data.append({
            "type": "function",
            "name": func_name,
            "file_path": self.file_path,
            "epic_key": self.epic_key,  # ล็อกเป้า Epic ตามที่คุณกอล์ฟวางแผนไว้
            "docstring": docstring.strip() if docstring else "",
            "code_snippet": raw_code,
            "calls": list(set(calls))
        })
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        """(แถมให้) ทำงานเมื่อเจอการประกาศคลาส (class)"""
        docstring = ast.get_docstring(node)
        self.extracted_data.append({
            "type": "class",
            "name": node.name,
            "file_path": self.file_path,
            "epic_key": self.epic_key,
            "docstring": docstring.strip() if docstring else "",
            "code_snippet": f"class {node.name}: ...",  # เก็บแค่ชื่อโครงสร้าง ไม่เอาโค้ดทั้งหมด
            "calls": []
        })
        self.generic_visit(node)


def parse_python_file(file_path, epic_key):
    """อ่านและชำแหละไฟล์ Python 1 ไฟล์"""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            source_code = file.read()

        tree = ast.parse(source_code)
        visitor = PythonCodeVisitor(file_path, source_code, epic_key)
        visitor.visit(tree)
        return visitor.extracted_data
    except Exception as e:
        logger.warning(f"⚠️ ข้ามไฟล์ {file_path} เนื่องจาก Parse ไม่ผ่าน: {e}")
        return []


def scan_codebase(target_path: str, epic_key: str, exclude_dirs=None) -> list:
    """
    ฟังก์ชันหลักสำหรับวิ่งสแกนไฟล์เดี่ยว หรือ ทั้งโฟลเดอร์โปรเจกต์
    """
    if exclude_dirs is None:
        # โฟลเดอร์มาตรฐานที่ AI ไม่ควรอ่าน
        exclude_dirs = {".venv", "venv", "__pycache__", ".git", "node_modules", ".idea", "chroma_db", "logs", "pg_data"}

    files_to_parse = []
    
    # 🌟 1. เช็คเป้าหมายและรวบรวม "รายชื่อไฟล์" ที่ต้องอ่าน
    if os.path.isfile(target_path):
        # ถ้าเป็นไฟล์เดี่ยวๆ (เช่นรันจาก Jenkins หรือ Apollo)
        files_to_parse.append(Path(target_path))
    elif os.path.isdir(target_path):
        # ถ้าเป็นโฟลเดอร์ (กวาดทั้งโปรเจกต์) ให้ใช้ rglob วนหาไฟล์ .py
        root_path = Path(target_path)
        for file_path in root_path.rglob("*.py"):
            # เช็คว่าไฟล์อยู่ในโฟลเดอร์ที่ต้องข้ามหรือไม่
            if any(excluded in file_path.parts for excluded in exclude_dirs):
                continue
            files_to_parse.append(file_path)
    else:
        logger.error(f"❌ Path not found: {target_path}")
        return []

    logger.info(f"🔍 เริ่มสแกนโค้ดเป้าหมาย: {target_path} (Epic: {epic_key})")

    all_extracted_nodes = []

    # 🌟 2. นำไฟล์ที่รวบรวมได้ ไปแกะโครงสร้าง (AST) ทีละไฟล์
    for file_path in files_to_parse:
        logger.info(f"📄 กำลังอ่านไฟล์: {file_path}")
        
        # ส่งไปให้ parse_python_file ของคุณก๊อปจัดการแกะเนื้อโค้ด
        extracted_nodes = parse_python_file(file_path, epic_key)
        all_extracted_nodes.extend(extracted_nodes)

    logger.info(f"✅ สแกนเสร็จสิ้น! พบ Class และ Function ทั้งหมด {len(all_extracted_nodes)} โหนด")
    return all_extracted_nodes


# --- สำหรับทดสอบรันแบบ Standalone ---
if __name__ == "__main__":
    # ระบุ Path ของโปรเจกต์ Olympus-Agents ปัจจุบัน
    PROJECT_ROOT = r"D:\Project\Olympus-Agents"  # เปลี่ยน Path ให้ตรงกับเครื่องคุณกอล์ฟ
    TARGET_EPIC = "SCRUM-32"

    results = scan_codebase(PROJECT_ROOT, TARGET_EPIC)

    # ลองเซฟเป็นไฟล์ JSON เพื่อเช็คข้อมูลตาเปล่าก่อนยิงเข้า Graph
    output_file = "scrum_32_code_nodes.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    logger.info(f"💾 บันทึกผลลัพธ์ลงไฟล์ {output_file} เรียบร้อยแล้ว")
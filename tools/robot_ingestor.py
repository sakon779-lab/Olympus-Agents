import sys
import os

# ====================================================================
# 💉 1. เชื่อมท่อไปยัง .venv ของโปรเจกต์เป้าหมาย (QA Repo)
# ====================================================================
# ชี้ไปที่โฟลเดอร์ site-packages ของโปรเจกต์ Athena ของคุณ
EXTERNAL_VENV_PATH = r"D:\WorkSpace\qa-automation-repo_Athena\.venv\Lib\site-packages"

if os.path.exists(EXTERNAL_VENV_PATH):
    # ยัดใส่ index 0 เพื่อให้ Python วิ่งไปหาที่นี่ก่อน
    sys.path.insert(0, EXTERNAL_VENV_PATH)
    print(f"🔗 Linked external libraries from: {EXTERNAL_VENV_PATH}")
else:
    print(f"⚠️ Warning: External path not found -> {EXTERNAL_VENV_PATH}")

# ====================================================================
# 2. Setup Path เพื่อให้เรียก knowledge_base ของ Agent ได้
# ====================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

from knowledge_base.vector_store import add_robot_keyword_to_vector
from robot.libdocpkg import LibraryDocumentation

def ingest_robot_library(library_name: str):
    # ... (โค้ดข้างในฟังก์ชันนี้เหมือนเดิมเป๊ะ ไม่ต้องแก้ครับ) ...
    print(f"\n🚀 เริ่มดูดข้อมูลจาก Library: {library_name} ...")
    try:
        libdoc = LibraryDocumentation(library_name)
    except Exception as e:
        print(f"❌ ไม่สามารถโหลด Library {library_name} ได้: {e}")
        return

    keyword_count = len(libdoc.keywords)
    print(f"📚 พบทั้งหมด {keyword_count} Keywords")

    success = 0
    for kw in libdoc.keywords:
        try:
            args_str = " | ".join([str(arg) for arg in kw.args]) if kw.args else "No Arguments"
            add_robot_keyword_to_vector(
                library_name=libdoc.name,
                keyword_name=kw.name,
                arguments=args_str,
                doc_string=kw.doc[:1000]
            )
            success += 1
        except Exception as e:
            print(f"⚠️ Error ingesting {kw.name}: {e}")

    print(f"✅ Ingest เสร็จสิ้น: สำเร็จ {success}/{keyword_count} keywords.\n")

if __name__ == "__main__":
    # 🎯 อัปเดต List ของ Library ให้ตรงกับ pip list ของคุณ
    libraries_to_ingest = [
        "BuiltIn",
        "Collections",
        "RequestsLibrary",
        "JSONLibrary",      # ตัวจัดการ JSON
        "FakerLibrary",     # ตัว Gen ข้อมูลปลอม
        "DatabaseLibrary"   # ตัวต่อ DB
    ]

    for lib in libraries_to_ingest:
        ingest_robot_library(lib)

    print("🎉 สมองของ Arthemis พร้อมใช้งานแล้ว!")
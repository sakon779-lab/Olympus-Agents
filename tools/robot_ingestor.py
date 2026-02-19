import sys
import os

# Setup Path เพื่อให้เรียก knowledge_base ได้
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

from knowledge_base.vector_store import add_robot_keyword_to_vector
from robot.libdocpkg import LibraryDocumentation


def ingest_robot_library(library_name: str):
    """
    ดูดข้อมูล Keyword ทุกตัวใน Library แล้วยิงเข้า Vector DB
    """
    print(f"\n🚀 เริ่มดูดข้อมูลจาก Library: {library_name} ...")

    try:
        # ใช้ Libdoc ดึงข้อมูลออกมาเป็น Object
        libdoc = LibraryDocumentation(library_name)
    except Exception as e:
        print(f"❌ ไม่สามารถโหลด Library {library_name} ได้: {e}")
        print("💡 อย่าลืม `pip install` library นั้นๆ ลงในเครื่องก่อนนะครับ")
        return

    keyword_count = len(libdoc.keywords)
    print(f"📚 พบทั้งหมด {keyword_count} Keywords")

    success = 0
    for kw in libdoc.keywords:
        try:
            # จัดการ arguments ให้อ่านง่าย เช่น arg1, arg2=Default
            args_str = " | ".join([str(arg) for arg in kw.args]) if kw.args else "No Arguments"

            # โยนเข้า Vector DB (ทีละตัว หรือจะรวมเป็น Batch ก็ได้)
            add_robot_keyword_to_vector(
                library_name=libdoc.name,
                keyword_name=kw.name,
                arguments=args_str,
                doc_string=kw.doc[:1000]  # ตัด Document ให้ยาวไม่เกิน 1000 ตัวอักษรกัน Token บวม
            )
            success += 1
        except Exception as e:
            print(f"⚠️ Error ingesting {kw.name}: {e}")

    print(f"✅ Ingest เสร็จสิ้น: สำเร็จ {success}/{keyword_count} keywords.\n")


if __name__ == "__main__":
    # 🎯 ใส่ชื่อ Library ที่โปรเจกต์คุณต้องใช้
    # (สามารถใส่ Path ของไฟล์ Custom Keyword บริษัทคุณได้ด้วยนะ เช่น "resources/common.robot")

    libraries_to_ingest = [
        "BuiltIn",
        "Collections",
        "RequestsLibrary",  # สำหรับเทส API
        # "SeleniumLibrary",
        # "D:/WorkSpace/qa-automation-repo/resources/my_custom_keywords.robot"
    ]

    for lib in libraries_to_ingest:
        ingest_robot_library(lib)

    print("🎉 สมองของ Arthemis พร้อมใช้งานแล้ว!")
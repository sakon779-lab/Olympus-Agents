# ไฟล์: inspect_vector.py
import sys
import os

# หาตำแหน่งไฟล์นี้ แล้วชี้ไปที่ Root ให้ถูก
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(CURRENT_DIR)

from knowledge_base.vector_store import vector_db, PERSIST_DIRECTORY


def inspect_db():
    print(f"📂 Looking for Database at: {PERSIST_DIRECTORY}")  # 👈 เพิ่มบรรทัดนี้

    if not os.path.exists(PERSIST_DIRECTORY):
        print("❌ FOLDER NOT FOUND! (Path is wrong)")
        return

    print("🔍 Fetching all documents from Vector DB...")

    # สั่งดึงข้อมูลทั้งหมดออกมา (ids, metadatas, documents)
    data = vector_db.get()

    count = len(data['ids'])
    print(f"📊 Total Documents Found: {count}\n")

    if count == 0:
        print("❌ Database is empty!")
        return

    print("-" * 50)
    for i in range(count):
        doc_id = data['ids'][i]
        meta = data['metadatas'][i]
        content = data['documents'][i]

        print(f"🆔 ID: {doc_id}")
        print(f"🏷️ Metadata: {meta}")
        print(f"📄 Content Preview: {content[:100].replace(chr(10), ' ')}...")  # ตัดมาโชว์แค่ 100 ตัวอักษร
        print("-" * 50)


if __name__ == "__main__":
    inspect_db()
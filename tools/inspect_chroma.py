import os
import chromadb
from chromadb.config import Settings

# 1. ระบุ Path ของ ChromaDB (โฟลเดอร์ chroma_db ที่ Root)
CURRENT_FILE_PATH = os.path.abspath(__file__)
BASE_DIR = os.path.dirname(os.path.dirname(CURRENT_FILE_PATH))
CHROMA_PATH = os.path.join( BASE_DIR, "chroma_db")

print(f"📂 Opening ChromaDB at: {CHROMA_PATH}")

try:
    # 2. เชื่อมต่อ Client
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # 3. ลอง List ดูว่ามี Collection อะไรบ้าง
    collections = client.list_collections()
    print(f"📦 Found Collections: {[c.name for c in collections]}")

    # 4. เจาะเข้าไปดูข้อมูลใน 'jira_knowledge' (ชื่อต้องตรงกับใน vector_store.py)
    collection_name = "jira_knowledge"
    try:
        collection = client.get_collection(collection_name)

        # ดึงข้อมูลทั้งหมด (หรือจำกัดแค่ 5 อันแรกด้วย limit=5)
        # include=['documents', 'metadatas'] คือขอเนื้อหาและข้อมูลกำกับ
        data = collection.get(limit=5, include=['documents', 'metadatas'])

        count = collection.count()
        print(f"\n📊 Total Documents: {count}")
        print("-" * 50)

        if count == 0:
            print("❌ Collection is empty.")
        else:
            for i in range(len(data['ids'])):
                print(f"🆔 ID: {data['ids'][i]}")
                print(f"ℹ️ Metadata: {data['metadatas'][i]}")
                print(f"📄 Content (Preview): {data['documents'][i][:200]}...")  # ตัดให้สั้นหน่อย
                print("-" * 50)

    except ValueError:
        print(f"❌ Collection '{collection_name}' not found.")

except Exception as e:
    print(f"❌ Error: {e}")
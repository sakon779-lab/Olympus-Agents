import os
import logging
from typing import List, Dict

# ✅ ใช้ Library เดิมที่คุณถนัด (LangChain)
# from langchain_chroma import Chroma
# from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from core.config import settings

# Setup Path
CURRENT_FILE_PATH = os.path.abspath(__file__)
BASE_DIR = os.path.dirname(os.path.dirname(CURRENT_FILE_PATH))  # Olympus-Agents Root
PERSIST_DIRECTORY = os.path.join(BASE_DIR, "chroma_db")

# ---------------------------------------------------------
# ⚡ LAZY LOADING SETUP (แก้ปัญหา Time Out)
# ---------------------------------------------------------
# ประกาศตัวแปร Global ไว้เป็น None ก่อน (ยังไม่โหลด)
_VECTOR_DBS: Dict[str, any] = {}
_EMBEDDINGS = None

def get_vector_db(collection_name: str = "robot_framework_keywords"):
    """
    Init DB แยกตาม Collection (Lazy Load)
    """
    global _VECTOR_DBS, _EMBEDDINGS

    if collection_name not in _VECTOR_DBS:
        logging.info(f"⏳ Initializing Vector DB for collection: {collection_name}...")

        try:
            from langchain_chroma import Chroma
            from langchain_ollama import OllamaEmbeddings
        except ImportError as e:
            logging.error(f"❌ Critical Import Error: {e}")
            raise e

        # Init Embeddings แค่ครั้งเดียวพอ
        if _EMBEDDINGS is None:
            _EMBEDDINGS = OllamaEmbeddings(
                model=settings.EMBEDDING_MODEL,
                base_url=settings.OLLAMA_LOCAL_URL
            )

        # Init Chroma แยกตามชื่อ Collection
        _VECTOR_DBS[collection_name] = Chroma(
            collection_name=collection_name,
            embedding_function=_EMBEDDINGS,
            persist_directory=PERSIST_DIRECTORY
        )
        logging.info(f"✅ Vector DB Ready for '{collection_name}'!")

    return _VECTOR_DBS[collection_name]

# def add_ticket_to_vector(issue_key: str, summary: str, content: str):
#     """
#     Save ticket data to Vector DB.
#     """
#     # ✅ เรียกใช้ผ่านฟังก์ชันแทนตัวแปรตรงๆ
#     db = get_vector_db()
#
#     logging.info(f"🧠 VECTOR: Embedding ticket {issue_key}...")
#
#     full_text = f"""
#     Ticket: {issue_key}
#     Summary: {summary}
#     Knowledge: {content}
#     """
#
#     doc = Document(
#         page_content=full_text,
#         metadata={"issue_key": issue_key, "source": "jira"}
#     )
#
#     try:
#         # ดึง ID เก่าออกมา
#         existing_docs = db.get(where={"issue_key": issue_key})
#         if existing_docs and existing_docs['ids']:
#             db.delete(ids=existing_docs['ids'])
#             logging.info(f"♻️ Updated existing vector for {issue_key}")
#     except Exception as e:
#         logging.warning(f"⚠️ Vector delete warning: {e}")
#
#     # เพิ่ม Vector ใหม่
#     db.add_documents([doc])
#     logging.info(f"✅ VECTOR: Saved {issue_key} successfully.")
#
# def search_vector_db(query: str, k: int = 4):
#     """ค้นหาข้อมูลด้วยความหมาย (Semantic Search)"""
#     # ✅ เรียกใช้ผ่านฟังก์ชันแทนตัวแปรตรงๆ
#     db = get_vector_db()
#
#     logging.info(f"🧠 Semantic Searching for: '{query}'")
#
#     results = db.similarity_search_with_score(query, k=k)
#
#     if not results:
#         return "❌ No relevant info found in Vector DB."
#
#     parsed_results = []
#     for doc, score in results:
#         parsed_results.append(f"""
#         --- MATCH (Score: {score:.2f}) ---
#         Key: {doc.metadata.get('issue_key')}
#         Content: {doc.page_content}
#         -----------------------------------
#         """)
#
#     return "\n".join(parsed_results)

def add_robot_keyword_to_vector(library_name: str, keyword_name: str, arguments: str, doc_string: str):
    """
    บันทึก Keyword ของ Robot Framework ลงใน Vector DB
    """
    db = get_vector_db("robot_framework_keywords")  # ✅ เรียก Collection ใหม่

    # สร้าง ID แบบไม่ซ้ำกันตามชื่อ Library และ Keyword
    doc_id = f"{library_name}.{keyword_name}".replace(" ", "_")

    # ✂️ จัด Format Text ที่ AI จะอ่าน (Chunking)
    full_text = f"""
    Library: {library_name}
    Keyword: {keyword_name}
    Arguments: [ {arguments} ]
    Documentation: {doc_string}
    """

    doc = Document(
        page_content=full_text,
        metadata={
            "doc_id": doc_id,
            "library": library_name,
            "keyword": keyword_name,
            "source": "robot_libdoc"
        }
    )

    try:
        # เช็คว่าเคยมี Keyword นี้ไหม ถ้ามีให้ลบของเก่าก่อนอัปเดต
        existing = db.get(where={"doc_id": doc_id})
        if existing and existing['ids']:
            db.delete(ids=existing['ids'])
    except Exception as e:
        pass

    db.add_documents([doc])
    logging.info(f"✅ VECTOR: Ingested Keyword '{keyword_name}' from {library_name}")

def search_robot_keywords(query: str, k: int = 5):
    """ฟังก์ชันให้ Arthemis ใช้ค้นหา Keyword เวลาเขียน Code"""
    db = get_vector_db("robot_framework_keywords")
    results = db.similarity_search_with_score(query, k=k)

    if not results:
        return "❌ No matching keywords found. Use standard Python/Robot syntax."

    parsed_results = []
    for doc, score in results:
        parsed_results.append(f"--- MATCH (Score: {score:.2f}) ---\n{doc.page_content.strip()}\n")

    return "\n".join(parsed_results)
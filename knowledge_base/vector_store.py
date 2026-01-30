import os
import logging
from typing import List, Dict

# ✅ ใช้ Library เดิมที่คุณถนัด (LangChain)
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document

# Setup Path
CURRENT_FILE_PATH = os.path.abspath(__file__)
BASE_DIR = os.path.dirname(os.path.dirname(CURRENT_FILE_PATH))  # Olympus-Agents Root
PERSIST_DIRECTORY = os.path.join(BASE_DIR, "chroma_db")

# ---------------------------------------------------------
# ⚡ LAZY LOADING SETUP (แก้ปัญหา Time Out)
# ---------------------------------------------------------
# ประกาศตัวแปร Global ไว้เป็น None ก่อน (ยังไม่โหลด)
_VECTOR_DB = None
_EMBEDDINGS = None


def get_vector_db():
    """
    ฟังก์ชันนี้จะ Init DB ก็ต่อเมื่อถูกเรียกใช้เท่านั้น
    ทำให้ Server Start เร็วปรู๊ดปร๊าด!
    """
    global _VECTOR_DB, _EMBEDDINGS

    if _VECTOR_DB is None:
        logging.info("⏳ Initializing Vector DB (Lazy Load)...")

        # 1. Init Embeddings
        _EMBEDDINGS = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url="http://localhost:11434"
        )

        # 2. Init Chroma
        _VECTOR_DB = Chroma(
            collection_name="jira_knowledge",
            embedding_function=_EMBEDDINGS,
            persist_directory=PERSIST_DIRECTORY
        )
        logging.info("✅ Vector DB Ready!")

    return _VECTOR_DB


# ---------------------------------------------------------
# FUNCTION CALLS (แก้ให้เรียกผ่าน get_vector_db())
# ---------------------------------------------------------

def add_ticket_to_vector(issue_key: str, summary: str, content: str):
    """
    Save ticket data to Vector DB.
    """
    # ✅ เรียกใช้ผ่านฟังก์ชันแทนตัวแปรตรงๆ
    db = get_vector_db()

    logging.info(f"🧠 VECTOR: Embedding ticket {issue_key}...")

    full_text = f"""
    Ticket: {issue_key}
    Summary: {summary}
    Knowledge: {content}
    """

    doc = Document(
        page_content=full_text,
        metadata={"issue_key": issue_key, "source": "jira"}
    )

    try:
        # ดึง ID เก่าออกมา
        existing_docs = db.get(where={"issue_key": issue_key})
        if existing_docs and existing_docs['ids']:
            db.delete(ids=existing_docs['ids'])
            logging.info(f"♻️ Updated existing vector for {issue_key}")
    except Exception as e:
        logging.warning(f"⚠️ Vector delete warning: {e}")

    # เพิ่ม Vector ใหม่
    db.add_documents([doc])
    logging.info(f"✅ VECTOR: Saved {issue_key} successfully.")


def search_vector_db(query: str, k: int = 4):
    """ค้นหาข้อมูลด้วยความหมาย (Semantic Search)"""
    # ✅ เรียกใช้ผ่านฟังก์ชันแทนตัวแปรตรงๆ
    db = get_vector_db()

    logging.info(f"🧠 Semantic Searching for: '{query}'")

    results = db.similarity_search_with_score(query, k=k)

    if not results:
        return "❌ No relevant info found in Vector DB."

    parsed_results = []
    for doc, score in results:
        parsed_results.append(f"""
        --- MATCH (Score: {score:.2f}) ---
        Key: {doc.metadata.get('issue_key')}
        Content: {doc.page_content}
        -----------------------------------
        """)

    return "\n".join(parsed_results)
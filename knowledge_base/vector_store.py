import os
import logging
from typing import List, Dict
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document

# 👇 FIX: ใช้ตำแหน่งของไฟล์นี้ เป็นตัวตั้งต้น แล้วถอยหลังมา 1 step เพื่อหา Project Root
CURRENT_FILE_PATH = os.path.abspath(__file__) # D:\Project\PaymentBlockChain\knowledge_base\vector_store.py
BASE_DIR = os.path.dirname(os.path.dirname(CURRENT_FILE_PATH)) # D:\Project\PaymentBlockChain

# กำหนดที่เก็บ Vector DB (จะเป็น Folder ชื่อ 'chroma_db' ในโปรเจกต์)
PERSIST_DIRECTORY = os.path.join(BASE_DIR, "chroma_db")

# ตั้งค่า Embedding Model (ใช้ Ollama: nomic-embed-text)
embeddings = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url="http://localhost:11434"
)

# โหลด Vector DB เตรียมใช้งาน
vector_db = Chroma(
    collection_name="jira_knowledge",
    embedding_function=embeddings,
    persist_directory=PERSIST_DIRECTORY
)

# 👇 ฟังก์ชันต้องรับ 3 ค่าแบบนี้ครับ
def add_ticket_to_vector(issue_key: str, summary: str, content: str):
    """
    Save ticket data to Vector DB for semantic search.
    """
    logging.info(f"🧠 VECTOR: Embedding ticket {issue_key}...")

    full_text = f"""
    Ticket: {issue_key}
    Summary: {summary}
    Details: {content}
    """

    doc = Document(
        page_content=full_text,
        metadata={"issue_key": issue_key, "source": "jira"}
    )

    # ลบของเก่าก่อนเพิ่มใหม่
    try:
        existing = vector_db.get(where={"issue_key": issue_key})
        if existing and existing['ids']:
            vector_db.delete(ids=existing['ids'])
    except Exception as e:
        logging.warning(f"⚠️ Vector delete error (ignorable): {e}")

    vector_db.add_documents([doc])
    logging.info(f"✅ VECTOR: Saved {issue_key} successfully.")


def search_vector_db(query: str, k: int = 4):
    """ค้นหาข้อมูลด้วยความหมาย (Semantic Search)"""
    logging.info(f"🧠 Semantic Searching for: '{query}'")

    # ค้นหา k อันดับที่ใกล้เคียงที่สุด
    results = vector_db.similarity_search_with_score(query, k=k)

    parsed_results = []
    for doc, score in results:
        parsed_results.append(f"""
        --- MATCH (Score: {score:.2f}) ---
        {doc.page_content}
        -----------------------------------
        """)

    return "\n".join(parsed_results)
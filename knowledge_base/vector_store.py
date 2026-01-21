import os
import logging
from typing import List, Dict

# ✅ ใช้ Library เดิมที่คุณถนัด (LangChain)
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document

# Setup Path
CURRENT_FILE_PATH = os.path.abspath(__file__)
BASE_DIR = os.path.dirname(os.path.dirname(CURRENT_FILE_PATH)) # Olympus-Agents Root
PERSIST_DIRECTORY = os.path.join(BASE_DIR, "chroma_db")

# Setup Embeddings (ใช้ Ollama ตามเดิม)
embeddings = OllamaEmbeddings(
    model="nomic-embed-text",  # ตรวจสอบว่า `ollama pull nomic-embed-text` แล้วนะครับ
    base_url="http://localhost:11434"
)

# Load Vector DB
vector_db = Chroma(
    collection_name="jira_knowledge",
    embedding_function=embeddings,
    persist_directory=PERSIST_DIRECTORY
)

def add_ticket_to_vector(issue_key: str, summary: str, content: str):
    """
    Save ticket data to Vector DB.
    Content ในที่นี้คือ Business Logic + Tech Spec ที่รวมร่างมาแล้ว
    """
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

    # ✅ ลบของเก่าก่อนเพิ่มใหม่ (เพื่อไม่ให้ข้อมูลซ้ำซ้อน)
    try:
        # ดึง ID เก่าออกมา
        existing_docs = vector_db.get(where={"issue_key": issue_key})
        if existing_docs and existing_docs['ids']:
            vector_db.delete(ids=existing_docs['ids'])
            logging.info(f"♻️ Updated existing vector for {issue_key}")
    except Exception as e:
        logging.warning(f"⚠️ Vector delete warning: {e}")

    # เพิ่ม Vector ใหม่
    vector_db.add_documents([doc])
    logging.info(f"✅ VECTOR: Saved {issue_key} successfully.")

def search_vector_db(query: str, k: int = 4):
    """ค้นหาข้อมูลด้วยความหมาย (Semantic Search)"""
    logging.info(f"🧠 Semantic Searching for: '{query}'")

    results = vector_db.similarity_search_with_score(query, k=k)

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
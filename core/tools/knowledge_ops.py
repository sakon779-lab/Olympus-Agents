import logging
import json
from typing import Any
from knowledge_base.database import SessionLocal, init_db
from knowledge_base.models import JiraKnowledge
from knowledge_base.database import SessionLocal
from knowledge_base.models import JiraKnowledge
import re # ✅ เพิ่ม import re

init_db()
logger = logging.getLogger("KnowledgeOps")


# ✅ เพิ่มฟังก์ชันใหม่: อ่านจาก SQL
def get_knowledge_from_sql(issue_key: str) -> str:
    session = SessionLocal()
    try:
        knowledge = session.query(JiraKnowledge).filter(JiraKnowledge.issue_key == issue_key).first()
        if not knowledge:
            return None

        return f"""
        📌 [SQL Source] Ticket: {knowledge.issue_key}
        Summary: {knowledge.summary}
        Status: {knowledge.status}
        Logic: {knowledge.business_logic}
        Tech Spec: {knowledge.technical_spec}
        """
    except Exception as e:
        return None
    finally:
        session.close()

# เพิ่ม parameter: issue_type (default="Task")
# เพิ่ม parameter: issue_type (default="Task") และ assignee, story_point
def save_knowledge(issue_key: str, summary: str, status: str, business_logic: str, technical_spec: Any,
                   test_scenarios: Any, issue_type: str = "Task", parent_key=None, issue_links=None,
                   assignee: str = None, story_point: float = None, epic_key: str = None, epic_name: str = None,  #  [NEW]  4  in 
                   ticket_data: dict = None, extracted_data: dict = None, embedding_vector: list = None,
                   raw_text: str = None) -> str:
    """
    บันทึกความรู้ลง Database (รองรับ issue_type เพื่อกัน Error NotNull)
    """
    session = SessionLocal()
    try:
        # Auto-fix: แปลง List/Dict เป็น String
        if isinstance(technical_spec, (list, dict)):
            technical_spec = json.dumps(technical_spec, indent=2, ensure_ascii=False)

        if isinstance(test_scenarios, (list, dict)):
            test_scenarios = json.dumps(test_scenarios, indent=2, ensure_ascii=False)

        # 1. Update SQL
        knowledge = session.query(JiraKnowledge).filter(JiraKnowledge.issue_key == issue_key).first()
        if not knowledge:
            knowledge = JiraKnowledge(issue_key=issue_key)

        knowledge.summary = summary
        knowledge.status = status
        knowledge.issue_type = issue_type
        knowledge.parent_key = parent_key
        knowledge.issue_links = issue_links
        knowledge.business_logic = business_logic
        knowledge.technical_spec = str(technical_spec)
        knowledge.test_scenarios = str(test_scenarios)

        # [NEW] บันทึกค่าลงคอลัมน์ใหม่ใน Database
        knowledge.assignee = assignee
        knowledge.story_point = story_point
        knowledge.epic_key = epic_key
        knowledge.epic_name = epic_name

        session.add(knowledge)
        session.commit()

        # ==========================================
        # 2. Update Graph & Vector (Neo4j) - แทนที่ ChromaDB
        # ==========================================
        from core.tools.neo4j_ops import sync_ticket_to_graph, sync_unstructured_to_graph

        graph_status = ""
        # 2.1 เซฟข้อมูลพื้นฐาน (Structured Data)
        if ticket_data:
            sync_ticket_to_graph(ticket_data)
            graph_status += "[Graph Nodes OK] "

        # 2.2 เซฟข้อมูลเชิงลึกและ Vector (Unstructured Data)
        if extracted_data:
            sync_unstructured_to_graph(issue_key, extracted_data, embedding_vector, raw_text)
            graph_status += "[Graph Vector OK]"

        return f"✅ Knowledge Saved for {issue_key} (Type: {issue_type}) | {graph_status}"

    except Exception as e:
        session.rollback()
        return f"❌ Error saving knowledge: {e}"
    finally:
        session.close()
import logging
import json
from typing import Any
from knowledge_base.database import SessionLocal, init_db
from knowledge_base.models import JiraKnowledge
from knowledge_base.vector_store import add_ticket_to_vector

init_db()
logger = logging.getLogger("KnowledgeOps")


# ✅ เพิ่ม parameter: issue_type (default="Task")
def save_knowledge(issue_key: str, summary: str, status: str, business_logic: str, technical_spec: Any,
                   test_scenarios: Any, issue_type: str = "Task") -> str:
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
        knowledge.issue_type = issue_type  # ✅ บันทึกค่า issue_type
        knowledge.business_logic = business_logic
        knowledge.technical_spec = str(technical_spec)
        knowledge.test_scenarios = str(test_scenarios)

        session.add(knowledge)
        session.commit()

        # 2. Update Vector
        combined_content = f"""
        Type: {issue_type}
        Status: {status}
        Business Logic: {business_logic}
        Technical Spec: {str(technical_spec)}
        Test Scenarios: {str(test_scenarios)}
        """
        add_ticket_to_vector(issue_key, summary, combined_content)

        return f"✅ Knowledge Saved for {issue_key} (Type: {issue_type})"

    except Exception as e:
        session.rollback()
        return f"❌ Error saving knowledge: {e}"
    finally:
        session.close()
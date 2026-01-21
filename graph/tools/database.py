from typing import List, Dict, Any
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from knowledge_base.database import SessionLocal
from knowledge_base.models import JiraKnowledge
from datetime import datetime, timezone
import logging
from knowledge_base.vector_store import add_ticket_to_vector


@tool
def save_ticket_knowledge(
        issue_key: str,
        summary: str,
        issue_type: str = "Task",
        parent_key: str = None,
        issue_links: List[Dict[str, Any]] = None, # [NEW] รับเป็น List of Dict
        business_logic: str = None,
        technical_spec: str = None,
        test_scenarios: str = None,
        status: str = "UNKNOWN"
) -> str:
    """
    Saves or updates summarized Jira ticket knowledge into the database.
    Use this tool AFTER you have analyzed and categorized the ticket content.

    Args:
        issue_key: The Jira ticket ID (e.g., SCRUM-001)
        summary: Brief title of the ticket
        issue_type: Type of issue (Epic, Story, Task, Subtask, Bug)
        parent_key: ID of the parent ticket (if any)
        issue_links: should be a list like: [{"relation": "blocks", "target_key": "SCRUM-5"}
        business_logic: Summarized business rules, flows, and requirements
        technical_spec: Summarized technical details (API, DB, Libs)
        test_scenarios: Summarized test cases and acceptance criteria
        status: Current status of the ticket
    """
    # ในฟังก์ชัน save_ticket_knowledge ก่อนบรรทัด knowledge = JiraKnowledge(...)
    if parent_key == "None" or parent_key == "":
        parent_key = None

    # 👇 เพิ่ม Log บรรทัดนี้
    logging.info(f"💾 ATTEMPTING TO SAVE: {issue_key}")

    session: Session = SessionLocal()
    try:
        # Check if exists
        ticket = session.query(JiraKnowledge).filter(JiraKnowledge.issue_key == issue_key).first()

        # 🟢 สร้างเวลาปัจจุบันแบบ UTC (เพื่อแก้ปัญหาเวลาเด้ง)
        now_utc = datetime.now(timezone.utc)

        if ticket:
            # UPDATE existing
            ticket.summary = summary
            ticket.status = status
            ticket.business_logic = business_logic
            ticket.technical_spec = technical_spec
            ticket.test_scenarios = test_scenarios
            ticket.issue_links = issue_links
            ticket.parent_key = parent_key
            ticket.issue_type = issue_type

            # ✅ ใช้ตัวแปร UTC ที่สร้างไว้
            ticket.updated_at = now_utc

            action = "Updated"
        else:
            # CREATE new
            ticket = JiraKnowledge(
                issue_key=issue_key,
                summary=summary,
                status=status,
                business_logic=business_logic,
                technical_spec=technical_spec,
                test_scenarios=test_scenarios,
                issue_links=issue_links,
                parent_key=parent_key,
                issue_type=issue_type,

                # ✅ ใช้ตัวแปร UTC ที่สร้างไว้
                created_at=now_utc,
                updated_at=now_utc
            )
            session.add(ticket)
            action = "Created"

        session.commit()

        # 👇 เพิ่ม Log บรรทัดนี้
        logging.info(f"✅ COMMIT SUCCESS: {issue_key}")

        # 👇 2. เพิ่มส่วนนี้ต่อท้าย (หลังจาก Commit SQL เสร็จ)
        # -----------------------------------------------------
        #  VECTOR STORE INTEGRATION
        # -----------------------------------------------------
        try:
            # รวมข้อมูลสำคัญๆ ให้ Vector จำ
            vector_content = f"""
                    Status: {status}
                    Business Logic: {business_logic}
                    Tech Spec: {technical_spec}
                    Test Scenarios: {test_scenarios}
                    """

            # เรียกฟังก์ชันยัดลง Vector
            add_ticket_to_vector(issue_key, summary, vector_content)

        except Exception as vec_e:
            logging.error(f"⚠️ VECTOR SAVE FAILED (But SQL saved): {vec_e}")
        # -----------------------------------------------------

        # ส่งค่ากลับพร้อมเวลา Local (แปลงเป็นไทยให้ดูง่ายๆ ตรงนี้)
        local_time = now_utc.astimezone().strftime('%Y-%m-%d %H:%M:%S')
        return f"Successfully {action} ticket {issue_key} at {local_time}"

    except Exception as e:
        session.rollback()
        # 👇 เพิ่ม Log บรรทัดนี้ (สำคัญที่สุด!)
        logging.error(f"❌ DATABASE ERROR: {str(e)}")
        return f"❌ Error saving to DB: {str(e)}"
    finally:
        session.close()
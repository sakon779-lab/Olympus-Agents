import csv
import logging
import os
from neo4j import GraphDatabase
from core.config import settings
from core.llm_client import get_text_embedding

logger = logging.getLogger("SyncTestPipeline")


def get_neo4j_driver():
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )


# =====================================================================
# 1. 📊 Pipeline สำหรับไฟล์ CSV (Test Design)
# =====================================================================
def sync_test_pipeline(issue_key: str, csv_file_path: str) -> dict:
    """
    อ่านไฟล์ CSV (Test Design) -> ทำ Vector -> Sync เข้า Neo4j (Upsert & Cleanup)
    """
    if not os.path.exists(csv_file_path):
        return {"success": False, "error": f"File not found: {csv_file_path}"}

    test_cases = []
    valid_tc_ids = []

    try:
        with open(csv_file_path, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # อิงจาก Header ในไฟล์ SCRUM-30.csv
                tc_id = row.get('CaseID')
                if not tc_id:
                    continue

                valid_tc_ids.append(tc_id)

                # ดึงข้อมูลจากคอลัมน์ต่างๆ
                test_type = row.get('TestType', '')
                description = row.get('Description', '')
                prereq = row.get('PreRequisites', '')
                steps = row.get('Steps', '')
                expected = row.get('ExpectedResult', '')
                assertions = row.get('Post-Assertions', '')

                # ประกอบร่างข้อความเพื่อทำ Vector
                vector_ready_text = (
                    f"Test Case ID: {tc_id}\n"
                    f"Type: {test_type}\n"
                    f"Description: {description}\n"
                    f"Pre-Requisites: {prereq}\n"
                    f"Steps: {steps}\n"
                    f"Expected Result: {expected}\n"
                    f"Post-Assertions: {assertions}"
                )

                # แปลงข้อความเป็น Vector 768 มิติ
                embedding = get_text_embedding(vector_ready_text)

                test_cases.append({
                    "tc_id": tc_id,
                    "title": description,
                    "test_type": test_type,
                    "raw_text": vector_ready_text,
                    "embedding": embedding
                })
    except Exception as e:
        logger.error(f"❌ Failed to process CSV: {e}")
        return {"success": False, "error": str(e)}

    if not test_cases:
        return {"success": False, "error": "No valid test cases found in CSV."}

    # Cypher Query สำหรับเพิ่ม/อัปเดตข้อมูล (Upsert)
    upsert_query = """
    MERGE (ticket:JiraTicket {issue_key: $issue_key})
    WITH ticket

    UNWIND $test_cases AS tc_data
    MERGE (tc:TestCase {tc_id: tc_data.tc_id})
    SET tc.title = tc_data.title,
        tc.test_type = tc_data.test_type,
        tc.raw_text = tc_data.raw_text,
        tc.embedding = tc_data.embedding,
        tc.updated_at = timestamp()

    MERGE (tc)-[:VALIDATES]->(ticket)
    """

    # Cypher Query สำหรับลบข้อมูลที่ถูกถอดออกจาก CSV (Cleanup)
    cleanup_query = """
    MATCH (tc:TestCase)-[:VALIDATES]->(ticket:JiraTicket {issue_key: $issue_key})
    WHERE NOT tc.tc_id IN $valid_tc_ids
    DETACH DELETE tc
    """

    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            # 1. บันทึกข้อมูลใหม่และอัปเดตข้อมูลเดิม
            session.run(upsert_query, issue_key=issue_key, test_cases=test_cases)

            # 2. ลบ Test Case ที่ไม่มีในไฟล์ CSV รอบนี้
            result = session.run(cleanup_query, issue_key=issue_key, valid_tc_ids=valid_tc_ids)
            deleted_count = result.consume().counters.nodes_deleted

        logger.info(f"✅ Synced {len(test_cases)} Test Cases for {issue_key}.")
        return {"success": True,
                "message": f"Successfully synced {len(test_cases)} cases. Deleted {deleted_count} stale."}
    except Exception as e:
        logger.error(f"❌ Neo4j Sync Error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        driver.close()


# =====================================================================
# 2. 🤖 Pipeline สำหรับไฟล์ Robot Framework (.robot)
# =====================================================================
def sync_robot_pipeline(issue_key: str, robot_file_path: str) -> dict:
    """
    สกัดชื่อ Test Case จากไฟล์ .robot -> สร้าง Node TestScript -> โยงไปหา TestCase Node
    """
    if not os.path.exists(robot_file_path):
        return {"success": False, "error": f"File not found: {robot_file_path}"}

    # TODO: รอเขียน Logic การอ่านไฟล์ .robot ในสเตปถัดไป

    return {"success": True, "message": f"Robot pipeline placeholder for {robot_file_path}"}


if __name__ == "__main__":
    # Test Run กับไฟล์ SCRUM-30.csv ที่มีอยู่
    test_csv_path = r"D:\WorkSpace\qa-automation-repo_Athena\test_designs\SCRUM-30.csv"
    result = sync_test_pipeline("SCRUM-30", test_csv_path)
    print(result)
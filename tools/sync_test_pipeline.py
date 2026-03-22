import csv
import logging
import os
import re
from neo4j import GraphDatabase
from robot.api import get_model
from robot.api.parsing import ModelVisitor
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
    if not os.path.exists(csv_file_path):
        return {"success": False, "error": f"File not found: {csv_file_path}"}

    test_cases = []
    valid_tc_ids = []

    try:
        with open(csv_file_path, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                tc_id = row.get('CaseID')
                if not tc_id:
                    continue

                valid_tc_ids.append(tc_id)

                test_type = row.get('TestType', '')
                description = row.get('Description', '')
                prereq = row.get('PreRequisites', '')
                steps = row.get('Steps', '')
                expected = row.get('ExpectedResult', '')
                assertions = row.get('Post-Assertions', '')

                vector_ready_text = (
                    f"Test Case ID: {tc_id}\n"
                    f"Type: {test_type}\n"
                    f"Description: {description}\n"
                    f"Pre-Requisites: {prereq}\n"
                    f"Steps: {steps}\n"
                    f"Expected Result: {expected}\n"
                    f"Post-Assertions: {assertions}"
                )

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

    # 📌 สร้าง TestCase ครั้งแรกให้ is_automated = false ไว้ก่อน
    upsert_query = """
    MERGE (ticket:JiraTicket {issue_key: $issue_key})
    WITH ticket

    UNWIND $test_cases AS tc_data
    MERGE (tc:TestCase {tc_id: tc_data.tc_id})
    SET tc.title = tc_data.title,
        tc.test_type = tc_data.test_type,
        tc.raw_text = tc_data.raw_text,
        tc.embedding = tc_data.embedding,
        tc.is_automated = coalesce(tc.is_automated, false), 
        tc.updated_at = timestamp()

    MERGE (tc)-[:VALIDATES]->(ticket)
    """

    cleanup_query = """
    MATCH (tc:TestCase)-[:VALIDATES]->(ticket:JiraTicket {issue_key: $issue_key})
    WHERE NOT tc.tc_id IN $valid_tc_ids
    DETACH DELETE tc
    """

    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            session.run(upsert_query, issue_key=issue_key, test_cases=test_cases)
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

class TestCaseExtractor(ModelVisitor):
    def __init__(self, file_lines):
        self.test_cases = []
        self.file_lines = file_lines

    def visit_TestCase(self, node):
        start_line = node.lineno - 1
        end_line = node.end_lineno
        chunk_text = "".join(self.file_lines[start_line:end_line]).strip()

        self.test_cases.append({
            "name": node.name,
            "chunk_text": chunk_text
        })
        self.generic_visit(node)


def sync_robot_pipeline(issue_key: str, robot_file_path: str) -> dict:
    if not os.path.exists(robot_file_path):
        return {"success": False, "error": f"File not found: {robot_file_path}"}

    robot_scripts = []
    valid_tc_ids = []

    try:
        with open(robot_file_path, 'r', encoding='utf-8') as f:
            file_lines = f.readlines()

        model = get_model(robot_file_path)
        extractor = TestCaseExtractor(file_lines)
        extractor.visit(model)

        for tc_data in extractor.test_cases:
            tc_name = tc_data["name"]
            chunk_text = tc_data["chunk_text"]

            # 🕵️ 1. หารหัส TC-XXX จากชื่อ หรือ Tags
            tc_id = None
            match_name = re.search(r'(TC-\d+)', tc_name)
            if match_name:
                tc_id = match_name.group(1)
            else:
                match_tags = re.search(r'\[Tags\]\s+.*?(TC-\d+)', chunk_text, re.IGNORECASE)
                if match_tags:
                    tc_id = match_tags.group(1)

            # 🏷️ 2. กวาด Tags ทั้งหมดเก็บเข้าเป็น List
            tags_list = []
            tags_match = re.search(r'\[Tags\](.*)', chunk_text, re.IGNORECASE)
            if tags_match:
                # Robot ใช้ Space 2 เคาะขึ้นไป หรือ Tab ในการแบ่งคำ
                raw_tags = re.split(r'\s{2,}|\t', tags_match.group(1).strip())
                tags_list = [t.strip() for t in raw_tags if t.strip()]

            if tc_id:
                valid_tc_ids.append(tc_id)
                embedding = get_text_embedding(chunk_text)

                robot_scripts.append({
                    "tc_id": tc_id,
                    "name": tc_name,
                    "file_path": robot_file_path,
                    "chunk_text": chunk_text,
                    "embedding": embedding,
                    "tags": tags_list  # 📌 ส่ง Array ของ Tags เข้าไปด้วย
                })

    except Exception as e:
        logger.error(f"❌ Failed to parse Robot file: {e}")
        return {"success": False, "error": str(e)}

    if not robot_scripts:
        return {"success": False, "error": "No valid TC-XXX found in Robot file."}

    # 🕸️ Cypher: อัปเดตข้อมูล สร้าง property Tags และปรับ is_automated เป็น true
    upsert_query = """
    UNWIND $robot_scripts AS script

    MATCH (tc:TestCase {tc_id: script.tc_id})-[:VALIDATES]->(ticket:JiraTicket {issue_key: $issue_key})

    MERGE (ts:TestScript {tc_id: script.tc_id, file_path: script.file_path})
    SET ts.name = script.name,
        ts.raw_text = script.chunk_text,
        ts.embedding = script.embedding,
        ts.tags = script.tags,         // 🏷️ เซฟ Tags ลง Graph
        ts.is_automated = true,        // 🚩 ชูธงว่าสคริปต์นี้คือ Automation
        tc.is_automated = true,        // 🚩 อัปเดตให้ TestCase ฝั่ง Design รู้ตัวว่าโดน Automate แล้ว
        ts.updated_at = timestamp()

    MERGE (ts)-[:IMPLEMENTS]->(tc)
    """

    # Cleanup: ถ้าโดนลบสคริปต์ทิ้ง ต้องปรับให้ TestCase กลับไปเป็น is_automated = false
    cleanup_query = """
    MATCH (ts:TestScript {file_path: $robot_file_path})-[r:IMPLEMENTS]->(tc:TestCase)-[:VALIDATES]->(ticket:JiraTicket {issue_key: $issue_key})
    WHERE NOT ts.tc_id IN $valid_tc_ids
    SET tc.is_automated = false
    DETACH DELETE ts
    """

    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            session.run(upsert_query, issue_key=issue_key, robot_scripts=robot_scripts)
            result = session.run(cleanup_query, issue_key=issue_key, robot_file_path=robot_file_path,
                                 valid_tc_ids=valid_tc_ids)
            deleted_count = result.consume().counters.nodes_deleted

        logger.info(f"✅ Synced {len(robot_scripts)} Robot Chunks for {issue_key}.")
        return {"success": True,
                "message": f"Successfully synced {len(robot_scripts)} scripts. Deleted {deleted_count} stale."}
    except Exception as e:
        logger.error(f"❌ Neo4j Sync Error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        driver.close()


if __name__ == "__main__":
    # Test Run
    test_csv_path = r"D:\Project\qa-automation-repo\test_designs\SCRUM-30.csv"

    print("Testing CSV Sync...")
    result_csv = sync_test_pipeline("SCRUM-30", test_csv_path)
    print(result_csv)

    # ถ้ามีไฟล์ .robot เอา Path มาใส่ทดสอบตรงนี้ได้เลยครับ
    test_robot_path = r"D:\Project\qa-automation-repo\tests\SCRUM-30.robot"
    print("Testing Robot Sync...")
    result_robot = sync_robot_pipeline("SCRUM-30", test_robot_path)
    print(result_robot)
import json
import logging
from neo4j import GraphDatabase
from core.config import settings
from core.llm_client import get_text_embedding

# ตั้งค่า Logger
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("GraphIngestor")


def ingest_code_to_graph(json_file: str):
    logger.info(f"📂 กำลังอ่านข้อมูลจาก {json_file}")
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            nodes_data = json.load(f)
    except Exception as e:
        logger.error(f"❌ อ่านไฟล์ไม่สำเร็จ: {e}")
        return

    logger.info("🔌 กำลังเชื่อมต่อ Neo4j...")
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )

    with driver.session() as session:
        # =========================================================
        # รอบที่ 1: สร้างโหนดและฝัง Vector
        # =========================================================
        for i, data in enumerate(nodes_data):
            logger.info(f"⏳ [{i + 1}/{len(nodes_data)}] Ingesting Node: {data['name']}")

            # 1. สร้าง Vector Embedding จาก AI Summary
            summary = data.get("ai_summary", "")
            embedding = get_text_embedding(summary) if summary else []

            # สร้าง Unique ID ผสมระหว่าง Path กับชื่อฟังก์ชัน (กันชื่อซ้ำ)
            node_id = f"{data['file_path']}::{data['name']}"
            epic_key = data.get("epic_key", "SCRUM-32")

            # 2. บันทึก CodeNode
            query_node = """
            MERGE (c:CodeNode {node_id: $node_id})
            SET c.name = $name,
                c.type = $type,
                c.file_path = $file_path,
                c.docstring = $docstring,
                c.code_snippet = $code_snippet,
                c.ai_summary = $ai_summary,
                c.embedding = $embedding
            """
            session.run(query_node,
                        node_id=node_id,
                        name=data['name'],
                        type=data.get('type', 'function'),
                        file_path=data['file_path'],
                        docstring=data.get('docstring', ''),
                        code_snippet=data.get('code_snippet', ''),
                        ai_summary=summary,
                        embedding=embedding)

            # 3. โยงเข้าหา Epic Ticket
            query_epic = """
            MATCH (c:CodeNode {node_id: $node_id})
            MERGE (e:Ticket {id: $epic_key})
            MERGE (c)-[:BELONGS_TO]->(e)
            """
            session.run(query_epic, node_id=node_id, epic_key=epic_key)

        # =========================================================
        # รอบที่ 2: ลากเส้น Dependencies (CALLS)
        # =========================================================
        logger.info("🔗 กำลังสร้างเส้นความสัมพันธ์ (Dependencies)...")
        for data in nodes_data:
            caller_id = f"{data['file_path']}::{data['name']}"
            calls = data.get("calls", [])

            for called_name in calls:
                # ลอง Match หาว่าใน Graph เรามีฟังก์ชันชื่อนี้ไหม (เอาเฉพาะฟังก์ชันในโปรเจกต์)
                query_calls = """
                MATCH (caller:CodeNode {node_id: $caller_id})
                MATCH (callee:CodeNode {name: $called_name})
                MERGE (caller)-[:CALLS]->(callee)
                """
                session.run(query_calls, caller_id=caller_id, called_name=called_name)

    driver.close()
    logger.info("🎉 Graph Ingestion Complete! นำเข้าข้อมูลสำเร็จทั้งหมด")


if __name__ == "__main__":
    # ระบุไฟล์ JSON ที่ได้จากขั้นตอนที่แล้ว
    INPUT_JSON = "scrum_32_code_nodes_with_summary.json"
    ingest_code_to_graph(INPUT_JSON)
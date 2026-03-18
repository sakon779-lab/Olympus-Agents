import json
import logging
from neo4j import GraphDatabase
from core.config import settings
from core.llm_client import get_text_embedding
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

# ตั้งค่า Logger
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("GraphIngestor")


def chunk_code_with_sliding_window(name: str, docstring: str, code_snippet: str, chunk_size=2000, overlap=500):
    """ฟังก์ชันหั่นโค้ดแบบรับรู้โครงสร้าง Python (Python-Aware Chunking)"""
    if not code_snippet:
        return []

    lines = code_snippet.strip().splitlines()
    sig_lines = []
    for line in lines:
        sig_lines.append(line)
        if line.strip().endswith(':'):
            break
    signature = "\n".join(sig_lines)

    header = (
        f"=== CODE CHUNK ===\n"
        f"Function/Class: {name}\n"
        f"Signature: {signature}\n"
        f"Docstring: {docstring or 'None'}\n"
        f"--- Code Source ---\n"
    )

    # 🌟 อัปเกรด: ใช้ตัวหั่นสำหรับ Python โดยเฉพาะ ขยายขนาดก้อนโค้ดให้ใหญ่ขึ้น
    splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.PYTHON,
        chunk_size=chunk_size,
        chunk_overlap=overlap
    )
    raw_chunks = splitter.split_text(code_snippet)

    return [f"{header}{chunk}" for chunk in raw_chunks]


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
        # รอบที่ 1: สร้างโหนดและฝัง Vector (CodeNode เดิม + CodeChunk ใหม่)
        # =========================================================
        for i, data in enumerate(nodes_data):
            logger.info(f"⏳ [{i + 1}/{len(nodes_data)}] Ingesting Node & Chunks: {data['name']}")

            # 1. สร้าง Vector Embedding จาก AI Summary (อันนี้ของเดิม ต้องคงไว้)
            summary = data.get("ai_summary", "")
            embedding = get_text_embedding(summary) if summary else []

            # สร้าง Unique ID ผสมระหว่าง Path กับชื่อฟังก์ชัน (กันชื่อซ้ำ)
            node_id = f"{data['file_path']}::{data['name']}"
            epic_key = data.get("epic_key", "SCRUM-32")
            code_snippet = data.get('code_snippet', '')

            # 2. บันทึก CodeNode (✅ คืนชีพ code_snippet และ embedding กลับมาให้ครบตามของเดิมเป๊ะ)
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
                        code_snippet=code_snippet,
                        ai_summary=summary,
                        embedding=embedding)

            # 3. โยงเข้าหา Epic Ticket (อันนี้ของเดิม)
            query_epic = """
            MATCH (c:CodeNode {node_id: $node_id})
            MERGE (e:Ticket {id: $epic_key})
            MERGE (c)-[:BELONGS_TO]->(e)
            """
            session.run(query_epic, node_id=node_id, epic_key=epic_key)

            # 🌟 4. [ส่วนที่เพิ่มใหม่] สร้าง CodeChunk และฝัง Vector ของโค้ดดิบ
            if code_snippet:
                chunks = chunk_code_with_sliding_window(
                    name=data['name'],
                    docstring=data.get('docstring', ''),
                    code_snippet=code_snippet
                )

                # ลบ Chunk เก่าของฟังก์ชันนี้ทิ้งก่อน (ป้องกันขยะเวลาอัปเดตโค้ด)
                session.run("MATCH (c:CodeNode {node_id: $node_id})-[:HAS_CHUNK]->(ch:CodeChunk) DETACH DELETE ch",
                            node_id=node_id)

                for chunk_idx, chunk_text in enumerate(chunks):
                    chunk_id = f"{node_id}_chunk_{chunk_idx}"

                    # แปลง Chunk ที่แปะ Header แล้วให้เป็น Vector
                    chunk_embedding = get_text_embedding(chunk_text)

                    query_chunk = """
                    MATCH (c:CodeNode {node_id: $node_id})
                    MERGE (ch:CodeChunk {chunk_id: $chunk_id})
                    SET ch.text = $text, 
                        ch.embedding = $embedding
                    MERGE (c)-[:HAS_CHUNK]->(ch)
                    """
                    session.run(query_chunk,
                                node_id=node_id,
                                chunk_id=chunk_id,
                                text=chunk_text,
                                embedding=chunk_embedding)

        # =========================================================
        # รอบที่ 2: ลากเส้น Dependencies (CALLS) (อันนี้ของเดิมเป๊ะ ไม่แตะต้อง)
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
    logger.info("🎉 Graph Ingestion Complete! นำเข้าข้อมูลและสร้าง Chunks สำเร็จทั้งหมด")


if __name__ == "__main__":
    # ระบุไฟล์ JSON ที่ได้จากขั้นตอนที่แล้ว
    INPUT_JSON = "scrum_32_code_nodes_with_summary.json"
    ingest_code_to_graph(INPUT_JSON)
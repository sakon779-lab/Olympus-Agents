import logging
from neo4j import GraphDatabase
from core.config import settings

logger = logging.getLogger("Neo4jOps")


def search_knowledge_graph(question_embedding: list, top_k: int = 3) -> str:
    """ค้นหาข้อมูลจาก Neo4j ด้วย Vector Search และดึง Graph Context กลับมา"""

    # คำสั่ง Cypher ผสมผสาน: หา Vector ที่ใกล้เคียง -> วิ่งไปหา Ticket -> วิ่งไปหา Component
    search_query = """
    CALL db.index.vector.queryNodes('chunk_embedding', $top_k, $embedding)
    YIELD node AS chunk, score
    MATCH (t:Ticket)-[:HAS_CHUNK]->(chunk)
    OPTIONAL MATCH (t)-[:IMPACTS]->(c:Component)
    RETURN t.id AS ticket_id, 
           t.summary AS summary, 
           t.status AS status, 
           collect(c.name) AS components, 
           chunk.text AS context, 
           score
    ORDER BY score DESC
    """

    try:
        from core.config import settings
        from neo4j import GraphDatabase

        results_text = []
        with GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)) as driver:
            with driver.session() as session:
                result = session.run(search_query, top_k=top_k, embedding=question_embedding)

                for record in result:
                    ticket_id = record["ticket_id"]
                    components = ", ".join(record["components"]) if record["components"] else "None"
                    # คัดมาเฉพาะข้อมูลเน้นๆ ให้ AI อ่าน
                    doc = (f"🎯 Ticket: {ticket_id} (Status: {record['status']})\n"
                           f"📌 Summary: {record['summary']}\n"
                           f"⚙️ Impacts Systems: {components}\n"
                           f"📖 Details: {record['context']}\n"
                           f"---")
                    results_text.append(doc)

        return "\n".join(results_text) if results_text else "❌ No relevant context found in Graph."

    except Exception as e:
        import logging
        logging.getLogger("Neo4jOps").error(f"❌ Graph Search Error: {e}")
        return f"❌ Graph Search Error: {e}"

def sync_unstructured_to_graph(issue_key: str, extracted_data: dict, embedding_vector: list = None, raw_text: str = ""):
    """นำข้อมูลที่ LLM สกัดได้ (Components) และ Vector Embeddings ไปผูกกับตั๋วใน Graph"""

    def _create_unstructured_nodes(tx):
        # 1. วาดโหนด Component และลากเส้น IMPACTS
        components = extracted_data.get("components", [])
        for comp in components:
            if not comp: continue
            # แปลงชื่อระบบให้เป็นตัวใหญ่ทั้งหมดเพื่อลดความซ้ำซ้อน (เช่น payment api -> PAYMENT API)
            comp_name = str(comp).strip().upper()

            query_comp = """
            MATCH (t:Ticket {id: $id})
            MERGE (c:Component {name: $comp_name})
            MERGE (t)-[:IMPACTS]->(c)
            """
            tx.run(query_comp, id=issue_key, comp_name=comp_name)

        # 2. เก็บ Chunk และ Vector Embedding ลง Graph (แทนที่ ChromaDB)
        if embedding_vector and raw_text:
            # สร้าง ID เฉพาะให้ Chunk ของตั๋วใบนี้
            chunk_id = f"{issue_key}_chunk_1"

            query_chunk = """
            MATCH (t:Ticket {id: $id})
            MERGE (ch:Chunk {chunk_id: $chunk_id})
            SET ch.text = $raw_text,
                ch.embedding = $embedding
            MERGE (t)-[:HAS_CHUNK]->(ch)
            """
            tx.run(query_chunk,
                   id=issue_key,
                   chunk_id=chunk_id,
                   raw_text=raw_text,
                   embedding=embedding_vector)

    try:
        from core.config import settings
        with GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)) as driver:
            with driver.session() as session:
                session.execute_write(_create_unstructured_nodes)
        return True
    except Exception as e:
        logger.error(f"❌ Neo4j Unstructured Sync Error: {e}")
        return False

def _create_graph_nodes(tx, ticket_data):
    """รันคำสั่ง Cypher เพื่ออัปเดตข้อมูล Ticket และความสัมพันธ์ลง Graph"""

    # 1. สร้าง Node: Ticket (สร้างใหม่หรืออัปเดตของเดิม)
    query_ticket = """
    MERGE (t:Ticket {id: $id})
    SET t.summary = $summary, 
        t.status = $status, 
        t.type = $type
    """
    tx.run(query_ticket,
           id=ticket_data['issue_key'],
           summary=ticket_data.get('summary', ''),
           status=ticket_data.get('status', ''),
           type=ticket_data.get('issue_type', ''))

    # 🧹 [เพิ่มใหม่] กวาดล้างเส้นความสัมพันธ์เก่าระหว่างตั๋วทิ้งก่อน (ป้องกัน Ghost Links)
    # ลบเฉพาะเส้นที่ชี้จากตั๋วใบนี้ ไปหา "ตั๋วใบอื่น" เท่านั้น (ไม่กระทบ User หรือ Data อื่น)
    query_clear_edges = """
    MATCH (t:Ticket {id: $id})-[r]->(other:Ticket)
    DELETE r
    """
    tx.run(query_clear_edges, id=ticket_data['issue_key'])

    # 2. สร้างเส้นความสัมพันธ์: Parent (ถ้ามี)
    if ticket_data.get('parent_key'):
        query_parent = """
        MATCH (child:Ticket {id: $id})
        MERGE (parent:Ticket {id: $parent_id})
        MERGE (child)-[:HAS_PARENT]->(parent)
        """
        tx.run(query_parent, id=ticket_data['issue_key'], parent_id=ticket_data['parent_key'])

    # 3. สร้างเส้นความสัมพันธ์: Issue Links (Blocks, Relates to, ฯลฯ)
    # ข้อมูลจาก jira_ops จะมาเป็น list of dicts เช่น [{'type': 'Blocks', 'target': 'SCRUM-31'}]
    for link in ticket_data.get('issue_links', []):
        # แปลงชื่อความสัมพันธ์ให้อยู่ในรูปแบบตัวพิมพ์ใหญ่คั่นด้วย _ (เช่น "is blocked by" -> "IS_BLOCKED_BY")
        rel_type = str(link['type']).upper().replace(" ", "_").replace("-", "_")
        target_id = link['target']

        query_link = f"""
        MATCH (t1:Ticket {{id: $id}})
        MERGE (t2:Ticket {{id: $target_id}})
        MERGE (t1)-[:{rel_type}]->(t2)
        """
        tx.run(query_link, id=ticket_data['issue_key'], target_id=target_id)

def sync_ticket_to_graph(ticket_data: dict) -> bool:
    """ฟังก์ชันรับข้อมูลจาก Jira มารันลง Neo4j"""
    if not ticket_data or not ticket_data.get("success"):
        return False

    try:
        with GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)) as driver:
            with driver.session() as session:
                session.execute_write(_create_graph_nodes, ticket_data)
        return True
    except Exception as e:
        logger.error(f"❌ Neo4j Ingestion Error: {e}")
        return False
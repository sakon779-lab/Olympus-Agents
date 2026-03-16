import json
import logging
import re
from neo4j import GraphDatabase
import core.network_fix
from core.config import settings
from core.llm_client import query_qwen

# ตั้งค่า Logger
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("AutoMapper")


def get_unmapped_code_nodes(session, epic_key="SCRUM-32"):
    """ดึง CodeNode ที่ยังไม่ได้ผูกกับตั๋วใบย่อยๆ (ยังไม่มีเส้น IMPLEMENTS)"""
    query = """
    MATCH (c:CodeNode)-[:BELONGS_TO]->(e:Ticket {id: $epic_key})
    WHERE NOT (c)-[:IMPLEMENTS]->(:Ticket)
    AND c.embedding IS NOT NULL
    RETURN c.node_id AS node_id, c.name AS name, c.ai_summary AS summary, c.embedding AS embedding
    """
    result = session.run(query, epic_key=epic_key)
    return [record.data() for record in result]


def find_candidate_tickets(session, embedding_vector, top_k=5):
    """ใช้ Vector Search หาตั๋ว Jira ที่เนื้อหาคล้ายกับโค้ดมากที่สุด"""
    # อิงจาก index 'chunk_embedding' ที่เราสร้างไว้ใน neo4j_ops.py
    query = """
    CALL db.index.vector.queryNodes('chunk_embedding', $top_k, $embedding)
    YIELD node AS chunk, score
    MATCH (t:Ticket)-[:HAS_CHUNK]->(chunk)
    RETURN DISTINCT t.id AS ticket_id, t.summary AS summary, chunk.text AS details, score
    ORDER BY score DESC
    LIMIT $top_k
    """
    result = session.run(query, top_k=top_k, embedding=embedding_vector)
    return [record.data() for record in result]


def ask_llm_to_match(code_name, code_summary, candidates) -> list:
    """ส่งให้ Qwen ฟันธงว่าโค้ดนี้ตรงกับตั๋วใบไหนบ้าง"""
    if not candidates:
        return []

    # จัดเตรียมข้อมูลตั๋วให้ AI อ่านง่ายๆ
    candidates_text = ""
    for i, cand in enumerate(candidates):
        candidates_text += f"{i + 1}. TICKET: {cand['ticket_id']} | SUMMARY: {cand['summary']}\n"

    system_prompt = """
    You are an AI System Architect. Your job is to map a source code function to the correct Jira Tickets.
    Read the Code Summary and the list of Candidate Jira Tickets.
    Determine which ticket(s) this code was written for. It can match multiple tickets, one ticket, or none.

    CRITICAL RULE:
    You MUST output ONLY a valid JSON object in this exact format:
    {
      "matched_tickets": ["SCRUM-XX", "SCRUM-YY"],
      "reason": "Short explanation of why."
    }
    If no tickets match, return an empty list for matched_tickets.
    """

    user_prompt = f"""
    CODE FUNCTION: {code_name}
    CODE SUMMARY: {code_summary}

    CANDIDATE TICKETS:
    {candidates_text}
    """

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()}
    ]

    try:
        response = query_qwen(messages, temperature=0.1)
        raw_text = response.get('message', {}).get('content', '') if isinstance(response, dict) else str(response)

        # แกะ JSON ออกจากคำตอบ (ดักจับ Markdown ```json)
        match = re.search(r'\{.*\}', raw_text.replace('\n', ' '), re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            return parsed.get("matched_tickets", [])
        return []
    except Exception as e:
        logger.error(f"❌ LLM Parsing Error for {code_name}: {e}")
        return []


def link_code_to_tickets(session, node_id, ticket_ids):
    """สร้างเส้นความสัมพันธ์ [:IMPLEMENTS] ใน Graph"""
    if not ticket_ids:
        return

    query = """
    MATCH (c:CodeNode {node_id: $node_id})
    UNWIND $ticket_ids AS ticket_id
    MATCH (t:Ticket {id: ticket_id})
    MERGE (c)-[:IMPLEMENTS]->(t)
    """
    session.run(query, node_id=node_id, ticket_ids=ticket_ids)


def run_auto_mapper():
    epic_key = "SCRUM-32"
    logger.info(f"🚀 เริ่มต้น AI Auto-Mapper สำหรับ Epic {epic_key}...")

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )

    with driver.session() as session:
        # 1. ดึงโค้ดที่ยังเคว้งคว้าง
        unmapped_nodes = get_unmapped_code_nodes(session, epic_key)
        logger.info(f"🔍 พบ CodeNode ที่ยังไม่ได้จับคู่ {len(unmapped_nodes)} โหนด")

        success_count = 0

        for i, node in enumerate(unmapped_nodes):
            node_id = node['node_id']
            name = node['name']
            summary = node['summary']
            embedding = node['embedding']

            logger.info(f"\n🔄 [{i + 1}/{len(unmapped_nodes)}] กำลังวิเคราะห์โค้ด: {name}")

            # 2. ค้นหา Candidate Tickets
            candidates = find_candidate_tickets(session, embedding, top_k=4)
            if not candidates:
                logger.warning(f"⚠️ ไม่พบตั๋วที่ใกล้เคียงสำหรับ {name}")
                continue

            # 3. ให้ LLM ฟันธง
            matched_tickets = ask_llm_to_match(name, summary, candidates)

            # 4. อัปเดตลง Graph
            if matched_tickets:
                logger.info(f"✅ AI จับคู่ {name} เข้ากับตั๋ว: {matched_tickets}")
                link_code_to_tickets(session, node_id, matched_tickets)
                success_count += 1
            else:
                logger.info(f"🤷 AI มองว่า {name} ไม่ตรงกับตั๋วใบไหนเลยใน Candidate")

    driver.close()
    logger.info(f"\n🎉 Auto-Mapping เสร็จสิ้น! จับคู่สำเร็จ {success_count}/{len(unmapped_nodes)} โหนด")


if __name__ == "__main__":
    run_auto_mapper()
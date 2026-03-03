from neo4j import GraphDatabase

# 1. ตั้งค่าการเชื่อมต่อ (ตามที่เราตั้งไว้ใน Docker)
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password")

# 2. จำลองข้อมูลจาก Jira API (Structured Data)
mock_jira_tickets = [
    {
        "id": "SCRUM-30",
        "summary": "Implement Checkout API",
        "status": "In Progress",
        "assignee": "Dev Alice",
        "reporter": "QA Bob",
        "blocks": "SCRUM-31"  # สมมติว่าตั๋วนี้ทำให้ตั๋วหน้าเว็บชะงัก
    },
    {
        "id": "SCRUM-31",
        "summary": "Integrate Checkout UI",
        "status": "To Do",
        "assignee": "Frontend Charlie",
        "reporter": "PM David",
        "blocks": None
    },
    {
        "id": "SCRUM-32",
        "summary": "Setup Database Schema",
        "status": "Done",
        "assignee": "Dev Alice",  # Alice ทำตั๋วนี้เสร็จแล้ว
        "reporter": "QA Bob",
        "blocks": None
    }
]


def create_jira_graph(tx, ticket):
    """ฟังก์ชันหลักที่ใช้คำสั่ง Cypher ในการสร้าง Node และ Edge"""

    # คำสั่งที่ 1: สร้างตัวตั๋ว (Ticket Node)
    # 💡 ใช้คำว่า MERGE แทน CREATE เพื่อไม่ให้สร้างโหนดซ้ำถ้ารันโค้ดซ้ำ 2 รอบ
    query_ticket = """
    MERGE (t:Ticket {id: $id})
    SET t.summary = $summary, t.status = $status
    """
    tx.run(query_ticket, id=ticket["id"], summary=ticket["summary"], status=ticket["status"])

    # คำสั่งที่ 2: สร้างโหนดคน (User) และลากเส้นความสัมพันธ์
    query_users = """
    MATCH (t:Ticket {id: $id})
    MERGE (assignee:User {name: $assignee})
    MERGE (reporter:User {name: $reporter})

    // ลากเส้นจากตั๋วไปหาคน
    MERGE (t)-[:ASSIGNED_TO]->(assignee)
    MERGE (t)-[:REPORTED_BY]->(reporter)
    """
    tx.run(query_users, id=ticket["id"], assignee=ticket["assignee"], reporter=ticket["reporter"])

    # คำสั่งที่ 3: ลากเส้นเชื่อมตั๋วด้วยกัน (ถ้ามีคนรอมันอยู่)
    if ticket["blocks"]:
        query_blocks = """
        MATCH (t1:Ticket {id: $id})
        MERGE (t2:Ticket {id: $blocked_id}) // ถ้าตั๋วหน้ายังไม่มีในระบบ ให้สร้างรอไว้ก่อนเลย
        MERGE (t1)-[:BLOCKS]->(t2)
        """
        tx.run(query_blocks, id=ticket["id"], blocked_id=ticket["blocks"])


# 3. สั่งรันเชื่อมต่อและยิงข้อมูล
def main():
    print("🔌 Connecting to Neo4j...")
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            for t in mock_jira_tickets:
                session.execute_write(create_jira_graph, t)
                print(f"✅ Ingested Ticket: {t['id']}")

    print("🎉 Graph Ingestion Completed!")


if __name__ == "__main__":
    main()
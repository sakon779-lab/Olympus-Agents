import sys
import os
import logging
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ------------------------------------------------------------------
# 🔇 SILENCE MODE: ดักจับ Log ทุกอย่างให้ไปออก stderr (ช่องทางรอง)
# ห้ามมีอะไรออก stdout (ช่องทางหลัก) เด็ดขาด ไม่งั้น Claude ตัดสาย
# ------------------------------------------------------------------
logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)

# ปิดปาก Library ขี้บ่น (LangChain, SQLAlchemy) ให้เงียบกริบ
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)

# 1. Setup Path
current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))
sys.path.append(project_root)

# 2. Load Environment Variables
load_dotenv(os.path.join(project_root, ".env"))

# 3. Import Functions
# ใช้ sys.stderr.write เพื่อ Debug แทน print (Claude จะไม่อ่านช่องทางนี้)
try:
    from agents.apollo.agent import ask_guru, ask_database_analyst
    sys.stderr.write("✅ [DEBUG] Apollo Agent imported successfully.\n")
except ImportError as e:
    sys.stderr.write(f"❌ [DEBUG] Error importing Apollo: {e}\n")
    sys.exit(1)

# 4. Create Server
mcp = FastMCP("Olympus - Apollo")

@mcp.tool()
def consult_knowledge_base(question: str) -> str:
    """
    Ask Apollo's Knowledge Guru about Business Requirements, Logic, Jira Tickets.
    Useful for: "What is SCRUM-26?", "Explain login flow".
    """
    try:
        return ask_guru(question)
    except Exception as e:
        return f"❌ Guru Error: {str(e)}"

@mcp.tool()
def consult_database_stats(question: str) -> str:
    """
    Ask Apollo's Data Analyst to query the LIVE Database (PostgreSQL).
    Useful for: "How many users?", "Count Jira tickets".
    """
    try:
        return ask_database_analyst(question)
    except Exception as e:
        return f"❌ Analyst Error: {str(e)}"

# 5. Run Server
if __name__ == "__main__":
    # 🚫 ห้าม print ตรงนี้เด็ดขาด!
    # print("🏛️ Apollo MCP Server is running...") <--- ลบทิ้ง
    mcp.run()
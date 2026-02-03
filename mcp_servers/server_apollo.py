import sys
import os
import logging
import builtins
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ==============================================================================
# 🛡️ STDOUT PROTECTION & ENCODING FIX
# ==============================================================================
# 1. บังคับ UTF-8 ที่ stderr (แก้ปัญหา Emoji Crash บน Windows)
try:
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 2. HIJACK PRINT: บังคับทุกคำสั่ง print() ให้ลง stderr
# สิ่งนี้จะช่วยกันไม่ให้ [DEBUG] logs หลุดไป stdout จนทำให้ JSON พัง
original_print = builtins.print
def patched_print(*args, **kwargs):
    kwargs['file'] = sys.stderr
    original_print(*args, **kwargs)
builtins.print = patched_print

# ------------------------------------------------------------------
# 🔇 LOGGING SETUP
# ------------------------------------------------------------------
logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)

# 1. Setup Path
current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))
sys.path.append(project_root)

# 2. Load Environment Variables
load_dotenv(os.path.join(project_root, ".env"))

# 3. Import Functions
try:
    from agents.apollo.agent import ask_guru, ask_database_analyst, sync_ticket_to_knowledge_base
    # ใช้ print ได้เลย เพราะเรา Patch ให้ลง stderr แล้ว
    print("✅ [DEBUG] Apollo Agent imported successfully.")
except ImportError as e:
    print(f"❌ [DEBUG] Error importing Apollo: {e}")
    sys.exit(1)

# 4. Create Server
mcp = FastMCP("Olympus - Apollo")

@mcp.tool()
def consult_knowledge_base(question: str) -> str:
    """Ask Apollo's Knowledge Guru."""
    try:
        return ask_guru(question)
    except Exception as e:
        return f"❌ Guru Error: {str(e)}"

@mcp.tool()
def consult_database_stats(question: str) -> str:
    """Ask Apollo's Data Analyst."""
    try:
        return ask_database_analyst(question)
    except Exception as e:
        return f"❌ Analyst Error: {str(e)}"

@mcp.tool()
def sync_jira(issue_key: str) -> str:
    """Sync a specific Jira ticket into Apollo's Brain."""
    try:
        return sync_ticket_to_knowledge_base(issue_key)
    except Exception as e:
        return f"❌ Sync Error (MCP Layer): {str(e)}"

# 5. Run Server
if __name__ == "__main__":
    mcp.run()
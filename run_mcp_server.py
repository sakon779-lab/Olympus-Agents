import logging
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# ✅ Import Core Tools
from core.tools.jira_ops import read_jira_ticket
from core.tools.file_ops import read_file, list_files
from core.tools.git_ops import git_setup_workspace # หรือ tools อื่นๆ

# ✅ Import Agents (ถ้าจะ dispatch งาน)
# from agents.hephaestus.agent import run_hephaestus_task

# Setup Logging & Env
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Initialize MCP
mcp = FastMCP("Olympus-Gateway")

# --- 🛠️ MAP TOOLS TO MCP ---

@mcp.tool()
def get_jira_info(issue_key: str) -> str:
    """Read Jira ticket details."""
    return read_jira_ticket(issue_key)

@mcp.tool()
def explore_codebase(directory: str = ".") -> str:
    """List files in the project."""
    return list_files(directory)

@mcp.tool()
def read_source_code(file_path: str) -> str:
    """Read content of a file."""
    return read_file(file_path)

# ... (เพิ่ม Tools อื่นๆ ตามต้องการ) ...

if __name__ == "__main__":
    mcp.run()
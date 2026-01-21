import os
from dotenv import load_dotenv

# โหลด .env จาก Root Directory (ถอยหลังไป 1 ชั้นจากโฟลเดอร์ core)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, '.env'))

# Centralized Config
JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN")

# Paths
WORKSPACE_DIR = ROOT_DIR
TEST_DESIGN_DIR = os.path.join(ROOT_DIR, "test_designs")

# Ensure Output Directory Exists
os.makedirs(TEST_DESIGN_DIR, exist_ok=True)
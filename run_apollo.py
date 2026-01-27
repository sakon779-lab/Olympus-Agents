import sys
import os

# 1. Setup Path
sys.path.append(os.getcwd())

# 2. ✅ SET IDENTITY (สำคัญมาก!)
from core.config import settings
settings.CURRENT_AGENT_NAME = "Apollo"

# 3. Import Agent Logic
try:
    from agents.apollo.agent import run_apollo_task
except ImportError as e:
    # เผื่อไฟล์ Agent มีปัญหา หรือยังไม่สร้าง
    print(f"⚠️ Error importing Apollo agent: {e}")
    def run_apollo_task(task): print("❌ Apollo agent file not found or has errors.")

if __name__ == "__main__":
    print(f"🏛️ Agent Identity: {settings.CURRENT_AGENT_NAME}")
    print(f"📂 Target Workspace: {settings.AGENT_WORKSPACE}")
    print("-" * 50)

    if len(sys.argv) < 2:
        print("Usage: python run_apollo.py \"Sync SCRUM-26\"")
    else:
        task = sys.argv[1]
        run_apollo_task(task)
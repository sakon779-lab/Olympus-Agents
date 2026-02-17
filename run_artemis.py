import sys
import os
import core.network_fix
# 1. Setup Path
sys.path.append(os.getcwd())

# 2. ✅ SET IDENTITY (สำคัญมาก!)
from core.config import settings
settings.CURRENT_AGENT_NAME = "Artemis"

# 3. Import Agent Logic
# (สมมติว่าคุณมีไฟล์ agents/artemis/agent.py แล้ว)
try:
    from agents.artemis.agent import run_artemis_task
except ImportError:
    # เผื่อยังไม่ได้สร้างไฟล์ Artemis
    def run_artemis_task(task): print("⚠️ Artemis agent file not found yet.")

if __name__ == "__main__":
    print(f"🆔 Agent Identity: {settings.CURRENT_AGENT_NAME}")
    print(f"📂 Target Workspace: {settings.AGENT_WORKSPACE}")
    print("-" * 50)

    if len(sys.argv) < 2:
        print("Usage: python run_artemis.py \"Test SCRUM-26\"")
    else:
        task = sys.argv[1]
        run_artemis_task(task)
import sys
import os
import core.network_fix

# 1. Setup Path ให้ Python มองเห็น folder 'core' และ 'agents'
sys.path.append(os.getcwd())

# 2. ✅ SET IDENTITY (สำคัญมาก!)
# ต้องทำก่อน Import Agent เพื่อให้ค่า Config ถูกต้องตั้งแต่เริ่ม
from core.config import settings
settings.CURRENT_AGENT_NAME = "Hephaestus"

# 3. Import Agent Logic
from agents.hephaestus.agent import run_hephaestus_task

if __name__ == "__main__":
    print(f"🆔 Agent Identity: {settings.CURRENT_AGENT_NAME}")
    print(f"📂 Target Workspace: {settings.AGENT_WORKSPACE}")
    print("-" * 50)

    if len(sys.argv) < 2:
        print("Usage: python run_hephaestus.py \"Implement SCRUM-26\"")
    else:
        task = sys.argv[1]
        run_hephaestus_task(task)
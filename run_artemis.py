import sys
import os

# เพิ่ม Path ให้ Python หา agents/core เจอ
sys.path.append(os.getcwd())

from agents.artemis.agent import run_artemis_task

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_artemis.py \"Process SCRUM-24\"")
    else:
        run_artemis_task(sys.argv[1])
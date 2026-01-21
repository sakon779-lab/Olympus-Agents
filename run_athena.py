import sys
import os

# เพิ่ม Current Dir ให้ Python หา agents/core เจอ
sys.path.append(os.getcwd())

# ✅ แก้ชื่อ import ให้ตรงกับในไฟล์ agent.py (จาก run_athena เป็น run_athena_task)
from agents.athena.agent import run_athena_task

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_athena.py \"Design test cases for SCRUM-XX\"")
    else:
        # ✅ เรียกใช้ฟังก์ชันชื่อใหม่
        run_athena_task(sys.argv[1])
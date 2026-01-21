import sys
import os
from langchain_core.tools import tool

# Import สมองของ Local Agent ที่เราเพิ่งเตรียมโครงสร้างไว้
# (ต้องมั่นใจว่า path ถูกต้อง หรือใช้ sys.path.append ถ้าจำเป็น)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from local_agent.dev_agent import run_dev_agent_task  # สมมติว่าเราห่อ logic ไว้ใน function นี้
from local_agent.qa_agent import run_qa_agent_task

@tool
def assign_task_to_local_dev(task_description: str):
    """
    มอบหมายงาน Coding ให้ Local AI (Qwen) ทำงาน
    Use this tool when you want to write code, implement features, or refactor logic locally.
    Arguments:
      - task_description: คำสั่งที่ชัดเจน เช่น "Implement SCRUM-20 logic based on skeleton"
    """
    try:
        # เรียก function ของ Local Agent โดยตรง
        result = run_dev_agent_task(task_description)
        return f"✅ Local Agent Finished:\n{result}"
    except Exception as e:
        return f"❌ Local Agent Failed: {str(e)}"

@tool
def assign_task_to_local_qa(file_path: str):
    """
    มอบหมายงาน Test/Verify ให้ Local QA (Qwen) ทำงาน
    Use this tool to run tests or verify specific files.
    """
    try:
        result = run_qa_agent_task(file_path)
        return f"✅ QA Report:\n{result}"
    except Exception as e:
        return f"❌ QA Agent Failed: {str(e)}"
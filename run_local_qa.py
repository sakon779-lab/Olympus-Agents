import sys
import os
import traceback

# เพิ่ม Path ปัจจุบันเข้าไปใน system path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def main():
    # รับ Task จาก Command Line Arguments
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Check system status"

    print("=" * 60)
    print(f"🚀 Launching Local QA Agent (Gamma)...")
    print(f"📋 Task: {task}")
    print("=" * 60)

    try:
        # Import จาก local_agent/qa_agent.py
        from local_agent.qa_agent import run_qa_agent_task

        # เรียก Agent ทำงาน
        result = run_qa_agent_task(task)

        print("\n" + "=" * 60)
        print(f"✅ FINAL RESULT:\n{result}")
        print("=" * 60)

    except ImportError as e:
        print("\n❌ Error: Could not import 'local_agent.qa_agent'.")
        print("Please check if 'local_agent/qa_agent.py' exists.")
        print(f"Details: {e}")
    except Exception as e:
        print("\n" + "!" * 60)
        print(f"❌ CRITICAL CRASH: {e}")
        traceback.print_exc()
        print("!" * 60)
    finally:
        # บังคับให้รอ User กด Enter ก่อนปิดหน้าต่าง (เหมือน Dev Agent)
        print("\nPress ENTER to close this window...")
        input()

if __name__ == "__main__":
    main()
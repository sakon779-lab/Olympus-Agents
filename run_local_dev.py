import sys
import os

# เพิ่ม Path ปัจจุบันเข้าไปใน system path เพื่อให้มั่นใจว่า Python หาโฟลเดอร์ local_agent เจอ
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from local_agent.dev_agent import run_dev_agent_task
except ImportError as e:
    print("❌ Error: Could not import 'local_agent'. Please check your project structure.")
    print(f"Details: {e}")
    sys.exit(1)


def main():
    # 1. เช็คว่าผู้ใช้ใส่คำสั่งมาไหม
    if len(sys.argv) < 2:
        print("\nUsage: python run_local_dev.py \"<คำสั่งของคุณ>\"")
        print("Example: python run_local_dev.py \"Create api/test.py with hello world function\"\n")
        sys.exit(1)

    # 2. รับคำสั่งจาก Argument ตัวแรก
    task_description = sys.argv[1]

    print("=" * 60)
    print(f"🚀 Launching Local Dev Agent (Qwen)")
    print(f"📋 Task: {task_description}")
    print("=" * 60)

    try:
        # 3. ส่งงานให้ Agent (Qwen) ทำ
        result = run_dev_agent_task(task_description, max_steps=50)

        # 4. แสดงผลลัพธ์
        print("\n" + "=" * 60)
        print("✅ FINAL RESULT:")
        print(result)
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n⚠️ Process cancelled by user.")
    except Exception as e:
        print(f"\n❌ System Error: {str(e)}")


if __name__ == "__main__":
    # รับ Task จาก Command Line Arguments
    import sys

    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Task: Check system health"

    print(f"🚀 Launching Local Dev Agent...")
    print(f"📋 Task: {task}")
    print("=" * 60)

    try:
        # เรียก Agent ทำงาน
        # (สมมติว่าฟังก์ชันหลักคุณชื่อ run_dev_agent_task หรือคล้ายกัน)
        from local_agent.dev_agent import run_dev_agent_task

        result = run_dev_agent_task(task)

        print("\n" + "=" * 60)
        print(f"✅ FINAL RESULT:\n{result}")
        print("=" * 60)

    except Exception as e:
        print("\n" + "!" * 60)
        print(f"❌ CRITICAL CRASH: {e}")
        import traceback

        traceback.print_exc()  # ปริ้นท์จุดที่พังออกมาให้หมด
        print("!" * 60)

    finally:
        # 🟢 เพิ่มบรรทัดนี้: บังคับให้รอ User กด Enter ก่อนปิดหน้าต่าง
        print("\nPress ENTER to close this window...")
        input()
# check_models.py
import os
import google.generativeai as genai
from dotenv import load_dotenv

# 1. โหลด Key
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ Error: ไม่เจอ GOOGLE_API_KEY ในไฟล์ .env")
    exit()

print(f"🔑 Found Key: {api_key[:5]}...{api_key[-3:]}")

# 2. ตั้งค่า
genai.configure(api_key=api_key)

# 3. ดึงรายการโมเดลทั้งหมดที่ใช้ได้
print("\n📡 Connecting to Google AI Studio...")
try:
    print("📋 รายชื่อ Model ที่คุณใช้ได้:")
    count = 0
    for m in genai.list_models():
        # กรองเฉพาะตัวที่ใช้คุยได้ (generateContent)
        if 'generateContent' in m.supported_generation_methods:
            print(f"   ✅ {m.name}")
            count += 1

    if count == 0:
        print("⚠️ ไม่เจอโมเดล Chat เลย (อาจต้องเปิดสิทธิ์ใน Google AI Studio)")

except Exception as e:
    print(f"\n❌ เกิดข้อผิดพลาดในการเชื่อมต่อ: {e}")
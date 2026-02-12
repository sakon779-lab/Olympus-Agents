import requests
import json
import socket
import urllib3.util.connection as connection
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# 1. ปิด Warning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


# 2. 💉 บังคับ IPv4
def allowed_gai_family():
    return socket.AF_INET


connection.allowed_gai_family = allowed_gai_family

# 3. 🎯 ตั้งค่าเป้าหมาย
base_url = "https://ku5rp3pvihdvb3-11434.proxy.runpod.net"
chat_url = f"{base_url}/api/chat"
model_name = "qwen2.5-coder:32b"  # เอาชื่อมาจากที่คุณเช็คเจอเมื่อกี้

# 4. 🎭 หน้ากาก Chrome (ห้ามลืม!)
headers = {
    'content-type': 'application/json',  # เพิ่มอันนี้สำหรับ POST
    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
}

# 5. 📦 เตรียมกล่องข้อความ (Payload)
payload = {
    "model": model_name,
    "messages": [
        {"role": "user", "content": "Hello! Are you ready to work?"}
    ],
    "stream": False  # ขอคำตอบรวดเดียวจบ
}

print(f"🚀 Sending Message to: {chat_url}")
print("⏳ Waiting for reply...")

try:
    # เปลี่ยนเป็น POST !!!
    response = requests.post(chat_url, headers=headers, json=payload, verify=False, timeout=60)

    if response.status_code == 200:
        print("\n✅ SUCCESS! คุยกับน้องรู้เรื่องแล้ว! 🎉")
        response_json = response.json()
        print("🤖 AI Reply:", response_json['message']['content'])
    else:
        print(f"\n❌ FAILED. Status Code: {response.status_code}")
        print("Response:", response.text)

except Exception as e:
    print(f"\n💀 ERROR: {e}")
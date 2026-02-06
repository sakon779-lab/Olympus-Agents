import requests
import socket
import urllib3.util.connection as connection
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# ปิด Warning รกหน้าจอ
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


# 💉 VACCINE: บังคับใช้ IPv4 (ป้องกันปัญหา Network บางค่าย)
def allowed_gai_family():
    return socket.AF_INET


connection.allowed_gai_family = allowed_gai_family

# 🎯 เป้าหมาย (จาก Curl ของคุณ)
url = "https://l83lnu9nu2pig6-11434.proxy.runpod.net/api/chat"

# 🎭 หน้ากากขั้นเทพ (เอามาจาก Curl ของคุณเป๊ะๆ)
headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-US,en;q=0.9,th;q=0.8',
    'cache-control': 'max-age=0',
    'priority': 'u=0, i',
    # ตัวสำคัญ! บอก Server ว่าเราคือ Chrome เวอร์ชันล่าสุด
    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
}

print(f"🚀 Launching Request to: {url}")
print("🎭 Applying Chrome Headers...")

try:
    # ยิง Request (verify=False เพื่อข้าม SSL Check)
    response = requests.get(url, headers=headers, verify=False, timeout=15)

    if response.status_code == 200:
        print("\n✅ SUCCESS! เจาะผ่านแล้วครับ!")
        print("🎉 Server ตอบรับ: ", response.text[:100])
    else:
        print(f"\n❌ FAILED. Status Code: {response.status_code}")
        print("Response:", response.text)

except Exception as e:
    print(f"\n💀 ERROR: {e}")
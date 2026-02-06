# file: core/network_fix.py
import socket
import requests.sessions
import urllib3
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# 1. ปิด Warning ตัวแดงๆ รกหน้าจอ
urllib3.disable_warnings(InsecureRequestWarning)


# 2. 💉 บังคับใช้ IPv4 (แก้เรื่องเน็ตบางค่าย/VPN)
def allowed_gai_family():
    return socket.AF_INET


urllib3.util.connection.allowed_gai_family = allowed_gai_family

# 3. 🎭 หน้ากาก Chrome (ชุดเดียวกับที่เทสผ่านเป๊ะๆ)
FAKE_HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-US,en;q=0.9,th;q=0.8',
    'cache-control': 'max-age=0',
    'priority': 'u=0, i',
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

# 4. 💉 Monkey Patch: สั่งให้ requests ทุกตัวในโปรแกรมสวมหน้ากากนี้อัตโนมัติ
_original_request = requests.sessions.Session.request


def patched_request(self, method, url, *args, **kwargs):
    # ถ้ายังไม่มี headers หรือมีไม่ครบ ให้เติมของปลอมเข้าไป
    kwargs.setdefault('headers', {})
    kwargs['headers'].update(FAKE_HEADERS)

    # ปิดการตรวจ SSL Certificate (กัน Error ฝั่ง Server)
    kwargs['verify'] = False

    return _original_request(self, method, url, *args, **kwargs)


# เริ่มการทำงานของ Patch ทันทีที่ import ไฟล์นี้
requests.sessions.Session.request = patched_request

print("✅ Network Fix Applied: Connection secured with Fake Chrome Headers!")
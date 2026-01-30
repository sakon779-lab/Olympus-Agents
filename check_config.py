# check_config.py
import os
# ✅ แก้บรรทัดนี้: Import BASE_DIR มาด้วย (เพราะมันอยู่นอก Class)
from core.config import settings, BASE_DIR

print("="*40)
print("🕵️ CONFIG DEBUGGER (Fixed)")
print("="*40)

# 1. เช็คว่ามันหา .env ที่ไหน
print(f"📂 Base Dir: {BASE_DIR}")  # <--- เรียกตรงๆ ไม่ผ่าน settings
env_path = os.path.join(BASE_DIR, ".env")
print(f"📄 Looking for .env at: {env_path}")
print(f"👀 File exists? : {os.path.exists(env_path)}")

print("-" * 20)

# 2. เช็คค่า Token (แบบเซ็นเซอร์)
token = settings.GITHUB_TOKEN
if token:
    # โชว์ 4 ตัวหน้าและ 4 ตัวหลัง
    masked_token = token[:4] + "*"*10 + token[-4:]
    print(f"✅ GITHUB_TOKEN Loaded: {masked_token}")
else:
    print(f"❌ GITHUB_TOKEN is EMPTY! (สาเหตุที่ Git ค้างอยู่ที่นี่!)")

print("-" * 20)

# 3. เช็ค URL ที่จะส่งให้ Git
print(f"🔗 TARGET_REPO_URL: {settings.TARGET_REPO_URL}")

if "@" in settings.TARGET_REPO_URL:
    print("🎉 URL has credentials! Git should work.")
else:
    print("💀 URL has NO credentials. Git will ask for password and FREEZE.")

print("="*40)
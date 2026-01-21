import requests
import json
import sys
import time

# Config ของ Ollama
OLLAMA_URL = "http://localhost:11434/api/chat"

# ⚠️ เช็คชื่อ Model ให้ตรงกับใน 'ollama list'
# (จาก Log เก่าคุณใช้ชื่อ model path ยาวๆ แต่ถ้า ollama list ขึ้นว่า qwen3:8b ก็ใช้ตามนั้น)
# MODEL_NAME = "qwen3:8b"
# MODEL_NAME = "qwen2.5-coder:1.5b"
# MODEL_NAME = "qwen2.5-coder:7b"
MODEL_NAME = "qwen2.5-coder:14b"



def query_qwen(messages: list, temperature=0.2) -> str:
    print(f"\n[DEBUG] 📡 Connecting to Ollama at {OLLAMA_URL}...", flush=True)
    print(f"[DEBUG] 🧠 Model: {MODEL_NAME}", flush=True)

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "options": {
            "num_ctx": 4096,  # 🔻 ลด Context ลงเหลือ 4096 ก่อน เพื่อความเร็วและชัวร์
            "temperature": 0.2,  # ลดความ Creative ลงให้นิ่งขึ้น
            "num_predict": -1
        }
    }

    try:
        start_time = time.time()

        print("[DEBUG] ⏳ Sending request... (Waiting for headers)", flush=True)

        # ✅ แก้ตรงนี้: เปลี่ยน timeout=30 เป็น timeout=120 (2 นาที) หรือ None
        with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=None) as response:
            print(f"[DEBUG] ✅ Connected! Status Code: {response.status_code}", flush=True)

            if response.status_code != 200:
                print(f"[ERROR] Server returned error: {response.text}", flush=True)
                return f"Error: Server returned {response.status_code}"

            print("🤖 AI: ", end="", flush=True)
            full_content = ""

            for line in response.iter_lines():
                if line:
                    try:
                        body = json.loads(line)
                        content = body.get("message", {}).get("content", "")

                        if content:
                            print(content, end="", flush=True)
                            full_content += content

                        if body.get("done", False):
                            total_duration = body.get("total_duration", 0) / 1e9
                            eval_count = body.get("eval_count", 0)
                            print(f"\n\n[DEBUG] 🏁 Done in {total_duration:.2f}s (Tokens: {eval_count})")
                            break

                    except json.JSONDecodeError:
                        continue

            print("\n")
            return full_content

    except requests.exceptions.Timeout:
        print("\n[ERROR] ❌ Connection Timed Out! (Ollama took longer than 120s)")
        return "Error: Timeout"
    except requests.exceptions.ConnectionError:
        print("\n[ERROR] ❌ Could not connect to Ollama. Is the server running?")
        return "Error: Connection Refused"
    except Exception as e:
        print(f"\n[ERROR] ❌ Unexpected Error: {str(e)}")
        return f"Error: {str(e)}"
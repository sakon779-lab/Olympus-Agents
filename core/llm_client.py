import requests
import json
import time
import logging
import socket
from core.config import settings

# ✅ Setup Logger
logger = logging.getLogger("LLM_Client")

def allowed_gai_family():
    return socket.AF_INET

# ✅ Import LangChain (Optional)
try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None


# def get_langchain_llm(temperature: float = 0):
#     """
#     ✅ Factory Function: สร้าง LangChain Object
#     ใช้สำหรับ SQL Agent หรือ Tool ที่ต้องการ LangChain Inteface
#     """
#     if ChatOllama is None:
#         raise ImportError("❌ Please install 'langchain-ollama' to use this feature.")
#
#     return ChatOllama(
#         base_url=settings.OLLAMA_BASE_URL,
#         model=settings.MODEL_NAME,
#         temperature=temperature,
#
#         # 🟢 ย้าย config สำคัญมาไว้ในนี้ครับ (สำคัญมาก)
#         # LangChain บางเวอร์ชันต้องการให้ใส่ใน constructor โดยตรง
#         num_ctx=32000,
#         num_predict=-1,
#         keep_alive="60m",
#         request_timeout=600.0,  # 🟢 เพิ่มตรงนี้
#         timeout=600.0,
#
#         # 🟢 ใส่ options ย้ำอีกที (LangChain บางตัวอ่านจากตรงนี้)
#         options={
#             "num_ctx": 32000,
#             "num_predict": -1,
#             "temperature": temperature
#         }
#     )

def get_text_embedding(text: str, model: str = None) -> list:
    """ฟังก์ชันกลางสำหรับแปลงข้อความเป็น Vector Embedding (รัน Local ตาม Config)"""

    # 🎯 1. ถ้าไม่ได้ระบุ Model มา ให้ใช้ค่า Default จาก Config (nomic-embed-text)
    target_model = model or getattr(settings, "EMBEDDING_MODEL", "nomic-embed-text")

    try:
        # 🎯 2. ดึง URL ของเครื่อง Local จาก Config
        local_ollama_url = getattr(settings, "OLLAMA_LOCAL_URL", "http://localhost:11434")

        response = requests.post(
            f"{local_ollama_url}/api/embed",
            json={"model": target_model, "input": text, "options": {"num_ctx": 4096}}

        )

        if response.status_code == 200:
            embeddings = response.json().get("embeddings", [])
            if embeddings:
                return embeddings[0]
        else:
            logger.error(f"❌ Embedding API Error: Status {response.status_code} - {response.text}")

    except Exception as e:
        logger.error(f"❌ Local Embedding Error: {e}")

    return []


def query_qwen(messages: list, temperature: float = 0.2) -> str:
    """
    ✅ Raw Function: ยิง Request ตรงๆ พร้อม Streaming output
    ใช้สำหรับ Conversation ทั่วไปของ Agent
    """
    # --- ส่วนวัดขนาด ---
    raw_payload = json.dumps(messages, ensure_ascii=False)
    char_count = len(raw_payload)
    est_tokens = char_count // 4  # ประเมินคร่าวๆ 4 char = 1 token

    print(f"\n[DEBUG] 📦 Outgoing Request Size:")
    print(f"        - Total Characters: {char_count:,}")
    print(f"        - Estimated Tokens: ~{est_tokens:,}")
    # ------------------

    # Construct Full URL
    api_url = f"{settings.OLLAMA_BASE_URL}/api/chat"

    print(f"\n[DEBUG] 📡 Connecting to Ollama at {api_url}...", flush=True)
    print(f"[DEBUG] 🧠 Model: {settings.MODEL_NAME}", flush=True)

    payload = {
        "model": settings.MODEL_NAME,
        "messages": messages,
        "stream": True,
        "options": {
            # "num_ctx": 4096,
            "num_ctx": 64000,
            "num_predict": -1,
            "temperature": temperature,  # ความคิดสร้างสรรค์ (0 = เป๊ะสุด, 1 = กาวสุด)
            "top_k": 40,  # 10 ถึง 40 (ปกติ Ollama default อยู่ที่ 40 ครับ สำหรับโค้ดดิ้งลดลงมาเหลือ 20-40 จะทำให้มันไม่เผลอหยิบตัวแปรแปลกๆ มาใช้)
            "top_p": 0.85,  # (Nucleus): 0.1 ถึง 0.5 (ตัดคำที่เป็นไปได้น้อยๆ ทิ้งไปเลย ให้มันโฟกัสแค่คำสั่งโค้ดที่ถูกต้อง)
            "repeat_penalty": 1.1
        }
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            print("[DEBUG] ⏳ Sending request... (Waiting for headers)", flush=True)

            # Timeout 120s เผื่อ Model คิดนาน
            with requests.post(api_url, json=payload, stream=True, timeout=120) as response:
                if response.status_code != 200:
                    error_msg = f"Error: Server returned {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return error_msg

                print(f"[DEBUG] ✅ Connected! Status Code: {response.status_code}", flush=True)
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
                                tokens = body.get("eval_count", 0)
                                print(f"\n\n[DEBUG] 🏁 Done in {total_duration:.2f}s (Tokens: {tokens})")

                        except json.JSONDecodeError:
                            continue

                print("\n")
                return full_content

        except requests.exceptions.ConnectionError:
            print(f"⚠️ Connection Refused. Server might be loading model. Retrying in 5s...", flush=True)
            time.sleep(5)  # ⏳ รอให้ Server ตื่น (สำคัญมาก!)
            continue  # วนไปรอบถัดไป

        except requests.exceptions.Timeout:
            logger.error("Connection Timed Out")
            return "Error: Timeout (Ollama took too long)"

        except Exception as e:
            logger.exception("Unexpected Error")
            return f"Error: {str(e)}"

    return "Error: Failed to connect after retries"
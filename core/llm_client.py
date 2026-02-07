import requests
import json
import time
import logging
from core.config import settings

# ✅ Setup Logger
logger = logging.getLogger("LLM_Client")

# ✅ Import LangChain (Optional)
try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None


def get_langchain_llm(temperature: float = 0):
    """
    ✅ Factory Function: สร้าง LangChain Object
    ใช้สำหรับ SQL Agent หรือ Tool ที่ต้องการ LangChain Inteface
    """
    if ChatOllama is None:
        raise ImportError("❌ Please install 'langchain-ollama' to use this feature.")

    return ChatOllama(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.MODEL_NAME,
        temperature=temperature
    )


def query_qwen(messages: list, temperature: float = 0.0) -> str:
    """
    ✅ Raw Function: ยิง Request ตรงๆ พร้อม Streaming output
    ใช้สำหรับ Conversation ทั่วไปของ Agent
    """
    # Construct Full URL
    api_url = f"{settings.OLLAMA_BASE_URL}/api/chat"

    print(f"\n[DEBUG] 📡 Connecting to Ollama at {api_url}...", flush=True)
    print(f"[DEBUG] 🧠 Model: {settings.MODEL_NAME}", flush=True)

    payload = {
        "model": settings.MODEL_NAME,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "options": {
            # "num_ctx": 4096,
            "num_ctx": 16000,
            "num_predict": -1
        }
    }

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

    except requests.exceptions.Timeout:
        logger.error("Connection Timed Out")
        return "Error: Timeout (Ollama took too long)"
    except requests.exceptions.ConnectionError:
        logger.error("Could not connect to Ollama")
        return "Error: Connection Refused (Is Ollama running?)"
    except Exception as e:
        logger.exception("Unexpected Error")
        return f"Error: {str(e)}"
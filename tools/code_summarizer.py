import json
import logging
from pathlib import Path
import core.network_fix
from core.llm_client import query_qwen

# ตั้งค่า Logger
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("CodeSummarizer")


def summarize_code_node(node: dict) -> str:
    """ส่งข้อมูล Function/Class ไปให้ LLM ช่วยสรุปการทำงานแบบกระชับ"""

    # 1. จัดเตรียมข้อมูล Input ให้ LLM อ่านง่าย
    name = node.get("name", "Unknown")
    node_type = node.get("type", "function")
    docstring = node.get("docstring", "")
    code_snippet = node.get("code_snippet", "")

    # ถ้าโค้ดยาวเกินไป ให้ตัดทอนหน่อย (ประหยัด Token และกัน AI งง)
    if len(code_snippet) > 1500:
        code_snippet = code_snippet[:1500] + "\n...[TRUNCATED]..."

    # 2. ตั้งค่า Prompt เพื่อบังคับพฤติกรรม AI
    system_prompt = """
    You are an expert Software Architect. Your task is to briefly summarize the purpose of a Python code snippet.
    - Keep it SHORT and CONCISE (1-3 sentences maximum).
    - Explain WHAT it does and WHY it exists in the system.
    - Focus on the business logic or core utility.
    - Respond ONLY with the summary. No introductory text.
    """

    user_prompt = f"""
    Type: {node_type}
    Name: {name}
    Docstring: {docstring}

    Code:
    ```python
    {code_snippet}
    ```
    """

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()}
    ]

    # 3. ยิง API ไปหา Local LLM ของเรา
    try:
        logger.info(f"🧠 กำลังให้ AI สรุป {node_type}: {name}...")
        response = query_qwen(messages, temperature=0.1)  # อุณหภูมิต่ำ = ตอบตรงไปตรงมา

        # จัดการ Format การตอบกลับเผื่อได้มาเป็น JSON
        if isinstance(response, dict):
            summary = response.get('message', {}).get('content', '') or response.get('content', '')
        else:
            summary = str(response)

        # ทำความสะอาดผลลัพธ์
        return summary.strip()

    except Exception as e:
        logger.error(f"❌ Error summarzing {name}: {e}")
        return "Failed to generate summary."


def process_extracted_nodes(input_file: str, output_file: str):
    """ฟังก์ชันหลัก: อ่านไฟล์ JSON -> วนลูปสรุป -> เซฟกลับลงไฟล์ใหม่"""

    input_path = Path(input_file)
    if not input_path.exists():
        logger.error(f"❌ ไม่พบไฟล์ {input_file}")
        return

    # อ่านข้อมูลเดิม
    with open(input_path, "r", encoding="utf-8") as f:
        nodes = json.load(f)

    logger.info(f"📂 พบข้อมูลทั้งหมด {len(nodes)} โหนด กำลังเริ่มกระบวนการสรุป...")

    processed_nodes = []

    for i, node in enumerate(nodes):
        logger.info(f"⏳ [{i + 1}/{len(nodes)}] Processing: {node.get('name')}")

        # ถ้ามีคำสรุปอยู่แล้ว ให้ข้าม (เผื่อรันสคริปต์ซ้ำแล้วขาดตอน)
        if node.get("ai_summary"):
            processed_nodes.append(node)
            continue

        # เรียกใช้ AI
        summary = summarize_code_node(node)

        # เพิ่มฟิลด์ใหม่เข้าไปใน Dict
        node["ai_summary"] = summary
        processed_nodes.append(node)

        # บันทึกทีละรอบเผื่อโปรแกรมค้างกลางทาง (Checkpoint)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(processed_nodes, f, ensure_ascii=False, indent=4)

    logger.info(f"🎉 เสร็จสิ้น! บันทึกผลลัพธ์ที่มีคำสรุปแล้วลงใน {output_file}")


# --- สำหรับทดสอบ ---
if __name__ == "__main__":
    # ระบุไฟล์ Input ที่ได้มาจากขั้นตอนที่ 1
    INPUT_JSON = "scrum_32_code_nodes.json"
    # ระบุชื่อไฟล์ Output ที่จะใส่ ai_summary เพิ่มเข้าไป
    OUTPUT_JSON = "scrum_32_code_nodes_with_summary.json"

    process_extracted_nodes(INPUT_JSON, OUTPUT_JSON)
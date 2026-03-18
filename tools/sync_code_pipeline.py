import os
import json
import logging
import core.network_fix
from pathlib import Path

# ตั้งค่า Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger("SyncPipeline")

# Import เครื่องมือทั้ง 4 ตัวของเรา
from tools.code_ingestor import scan_codebase
from tools.code_summarizer import process_extracted_nodes
from tools.code_to_graph import ingest_code_to_graph
from tools.ai_auto_mapper import run_auto_mapper


def run_full_sync_pipeline(project_root: str, epic_key: str = "SCRUM-32"):
    logger.info(f"🚀 เริ่มต้นการรัน Sync Pipeline สำหรับ Epic: {epic_key}")

    # กำหนดชื่อไฟล์ชั่วคราว
    raw_json = "scrum_32_code_nodes.json"
    summary_json = "scrum_32_code_nodes_with_summary.json"

    # =========================================================
    # STEP 1: AST Code Extraction (ดูดโค้ดใหม่ล่าสุด)
    # =========================================================
    logger.info("\n" + "=" * 50 + "\n🛠️ STEP 1: AST Code Extraction\n" + "=" * 50)
    raw_nodes = scan_codebase(project_root, epic_key)

    # 🌟 [SMART INCREMENTAL LOGIC] 🌟
    # โหลดไฟล์เก่า (ถ้ามี) เพื่อเอามาเทียบว่าฟังก์ชันไหนโค้ดเหมือนเดิมบ้าง
    old_summaries = {}
    if os.path.exists(summary_json):
        try:
            with open(summary_json, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for item in old_data:
                    # สร้าง ID เฉพาะตัว (Path + ชื่อฟังก์ชัน)
                    node_id = f"{item['file_path']}::{item['name']}"
                    old_summaries[node_id] = {
                        "code_snippet": item.get("code_snippet", ""),
                        "ai_summary": item.get("ai_summary", "")
                    }
            logger.info(f"♻️ โหลดข้อมูลความจำเดิมสำเร็จ ({len(old_summaries)} โหนด)")
        except Exception as e:
            logger.warning(f"⚠️ ไม่สามารถอ่านความจำเดิมได้ (เริ่มใหม่ทั้งหมด): {e}")

    # เทียบของใหม่กับของเก่า
    reused_count = 0
    for node in raw_nodes:
        node_id = f"{node['file_path']}::{node['name']}"
        if node_id in old_summaries:
            # ถ้าโค้ดข้างในฟังก์ชัน ไม่มีการเปลี่ยนแปลงเลย!
            if node["code_snippet"] == old_summaries[node_id]["code_snippet"]:
                if old_summaries[node_id]["ai_summary"]:
                    # แอบเอาคำสรุปเดิมมาแปะให้เลย AI จะได้ไม่ต้องทำใหม่
                    node["ai_summary"] = old_summaries[node_id]["ai_summary"]
                    reused_count += 1

    logger.info(f"⚡ นำคำสรุปเดิมมาใช้ซ้ำ (ไม่ต้องผ่าน AI): {reused_count} โหนด")

    # เซฟข้อมูลดิบ (ที่อาจจะมี ai_summary แปะมาแล้วบางส่วน) ลงไฟล์
    with open(raw_json, "w", encoding="utf-8") as f:
        json.dump(raw_nodes, f, ensure_ascii=False, indent=4)

    # =========================================================
    # STEP 2: AI Code Summarization
    # =========================================================
    logger.info("\n" + "=" * 50 + "\n🧠 STEP 2: AI Code Summarization\n" + "=" * 50)
    # มันจะทำงานเฉพาะโหนดที่ยังไม่มี ai_summary เท่านั้น (เฉพาะไฟล์ที่แก้ใหม่)
    process_extracted_nodes(raw_json, summary_json)

    # =========================================================
    # STEP 3: Neo4j Graph Ingestion
    # =========================================================
    logger.info("\n" + "=" * 50 + "\n🕸️ STEP 3: Neo4j Graph Ingestion\n" + "=" * 50)
    # MERGE ของ Neo4j จะทำหน้าที่อัปเดตข้อมูลให้ทันสมัยโดยไม่สร้างโหนดซ้ำ
    ingest_code_to_graph(summary_json)

    # =========================================================
    # STEP 4: AI Auto-Mapper
    # =========================================================
    logger.info("\n" + "=" * 50 + "\n🎯 STEP 4: AI Auto-Mapper (Link to Jira Tickets)\n" + "=" * 50)
    # มันจะข้ามโหนดที่เคยมีเส้น [:IMPLEMENTS] โยงไปหาตั๋วแล้วอัตโนมัติ
    run_auto_mapper()

    logger.info("\n✅✅✅ SYNC PIPELINE COMPLETED SUCCESSFULLY! ✅✅✅")


if __name__ == "__main__":
    # เปลี่ยน Path ให้ตรงกับเครื่องคุณกอล์ฟ (ถ้าจำเป็น)
    from core.config import settings

    PROJECT_ROOT = settings.AGENT_WORKSPACE if hasattr(settings, 'AGENT_WORKSPACE') else r"D:\Project\Olympus-Agents"
    TARGET_EPIC = "SCRUM-32"

    run_full_sync_pipeline(PROJECT_ROOT, TARGET_EPIC)
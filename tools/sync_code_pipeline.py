import os
import sys
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

def run_single_file_sync(file_path: str, epic_key: str = "SCRUM-32") -> str:
    """รัน Sync Pipeline สำหรับ 'ไฟล์เดียว' (รองรับทั้ง CI/CD และ MCP)"""
    
    if not os.path.exists(file_path):
        err_msg = f"❌ File not found: {file_path}"
        logger.error(err_msg)
        return err_msg

    logger.info(f"🚀 เริ่มต้นการรัน Sync Pipeline สำหรับไฟล์: {file_path} (Epic: {epic_key})")

    base_name = os.path.basename(file_path).replace(".", "_")
    raw_json = f"temp_{base_name}_raw.json"
    summary_json = f"temp_{base_name}_summary.json"

    try:
        # STEP 1: AST Code Extraction
        logger.info("\n" + "=" * 40 + "\n🛠️ STEP 1: AST Extraction\n" + "=" * 40)
        raw_nodes = scan_codebase(file_path, epic_key)
        
        if not raw_nodes:
            msg = f"⏭️ No interesting functions/classes found in {file_path}. Skipped."
            logger.info(msg)
            return msg

        with open(raw_json, "w", encoding="utf-8") as f:
            json.dump(raw_nodes, f, ensure_ascii=False, indent=4)

        # STEP 2: AI Code Summarization
        logger.info("\n" + "=" * 40 + "\n🧠 STEP 2: AI Summarization\n" + "=" * 40)
        process_extracted_nodes(raw_json, summary_json)

        # STEP 3: Neo4j Graph Ingestion
        logger.info("\n" + "=" * 40 + "\n🕸️ STEP 3: Graph Ingestion\n" + "=" * 40)
        ingest_code_to_graph(summary_json)

        # STEP 4: AI Auto-Mapper
        logger.info("\n" + "=" * 40 + "\n🎯 STEP 4: Auto-Mapper\n" + "=" * 40)
        run_auto_mapper(epic_key, file_path)

        success_msg = f"✅ SYNC COMPLETED FOR: {file_path} (Epic: {epic_key})"
        logger.info(f"\n{success_msg}")
        return success_msg

    except Exception as e:
        err_msg = f"❌ Error during sync pipeline: {str(e)}"
        logger.error(err_msg)
        return err_msg

    finally:
        # Clean up files
        if os.path.exists(raw_json): os.remove(raw_json)
        if os.path.exists(summary_json): os.remove(summary_json)


def run_recent_code_sync(repo_path: str, hours: int = 24, epic_key: str = "SCRUM-32") -> str:
    """
    กวาดหาเฉพาะ 'ไฟล์ Code' ที่ถูกแก้ใน X ชั่วโมงที่ผ่านมา แล้วสั่ง Sync ทีละไฟล์ 
    """
    logger.info(f"🔍 Checking for modified CODE files in {repo_path} (Last {hours} hours)...")
    
    if not os.path.exists(repo_path):
        err_msg = f"❌ Repo path not found: {repo_path}"
        logger.error(err_msg)
        return err_msg

    try:
        # 💡 ใช้ subprocess เรียก Git เช็คประวัติ
        cmd = ["git", "-C", repo_path, "log", f"--since={hours} hours ago", "--name-only", "--pretty=format:"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        # 💡 กรองเอาเฉพาะไฟล์ Code นามสกุลที่น่าสนใจ (ตัดพวก .md, .txt, .json ออกไป)
        valid_extensions = ('.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.cs', '.go')
        
        changed_files = list(set([
            f.strip() for f in result.stdout.split('\n') 
            if f.strip().endswith(valid_extensions)
        ]))

        if not changed_files:
            msg = f"😴 No code files were changed in the last {hours} hours. (Epic: {epic_key})"
            logger.info(msg)
            return msg

        success_count = 0
        logger.info(f"📝 Found {len(changed_files)} changed code files. Starting sync...")
        
        for file_name in changed_files:
            # รวม Path ของ Repo เข้ากับชื่อไฟล์ที่ Git หาเจอ
            full_path = os.path.join(repo_path, file_name)
            
            # เช็คว่าไฟล์ยังมีอยู่จริง (ไม่ได้โดนลบทิ้งไปแล้ว)
            if os.path.exists(full_path):
                logger.info(f"🚀 Triggering sync for: {full_path}")
                run_single_file_sync(full_path, epic_key)
                success_count += 1

        return f"✅ Successfully synced {success_count} recently modified CODE files (Epic: {epic_key})."

    except subprocess.CalledProcessError as e:
        err_msg = f"❌ Git command failed (Is it a valid Git repo?): {e.stderr}"
        logger.error(err_msg)
        return err_msg
    except Exception as e:
        err_msg = f"❌ Error checking recent code files: {str(e)}"
        logger.error(err_msg)
        return err_msg


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
    run_auto_mapper(epic_key)

    logger.info("\n✅✅✅ SYNC PIPELINE COMPLETED SUCCESSFULLY! ✅✅✅")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("⚠️ Usage:")
        print("  1. Single File : python -m tools.sync_code_pipeline <file_path> [epic_key]")
        print("  2. Recent Files: python -m tools.sync_code_pipeline --recent <repo_path> <hours> [epic_key]")
        sys.exit(1)

    # 🌟 โหมดกวาดไฟล์ย้อนหลัง
    if sys.argv[1] == "--recent":
        if len(sys.argv) < 4:
            print("⚠️ Error: Missing arguments for --recent")
            print("Usage: python -m tools.sync_code_pipeline --recent <repo_path> <hours> [epic_key]")
            sys.exit(1)
            
        repo_path = sys.argv[2]
        hours = int(sys.argv[3])
        epic_key = sys.argv[4] if len(sys.argv) > 4 else "SCRUM-32"
        
        result = run_recent_code_sync(repo_path, hours, epic_key)
        print(result)
        
    # 🌟 โหมดไฟล์เดียว (แบบเดิม)
    else:
        target_file = sys.argv[1]
        epic_key = sys.argv[2] if len(sys.argv) > 2 else "SCRUM-32"
        
        result = run_single_file_sync(target_file, epic_key)
        print(result)
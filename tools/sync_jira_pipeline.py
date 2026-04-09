"""
Jira Ticket Sync Pipeline Tools
"""

import sys
import os
# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""
รวบรวมฟังก์ชันที่เกี่ยวข้องกับการ sync Jira tickets จาก Apollo agent
"""

import json
import logging
import ast
import re
from typing import Dict, Any, List

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [Jira Sync] %(message)s')
logger = logging.getLogger("JiraSyncPipeline")


def robust_json_parser(text: str) -> Dict[str, Any]:
    """ พยายามแกะ JSON หรือ Python Dict จาก Text ให้ได้ """
    # 1. ลองใช้ Parser ตัวเก่งของคุณ _extract_all_jsons
    extracted = _extract_all_jsons(text)
    if extracted:
        return extracted[0]  # เอาตัวแรกที่เจอ

    # 2. ถ้าไม่เจอ ลองท่าไม้ตาย clean string
    try:
        clean = text.strip()
        if clean.startswith("```json"): clean = clean[7:]
        if clean.startswith("```"): clean = clean[3:]
        if clean.endswith("```"): clean = clean[:-3]
        return json.loads(clean.strip())
    except:
        return {}


def _extract_all_jsons(text: str) -> List[Dict[str, Any]]:
    """ robust JSON extractor handling multiple blocks and python dict strings """
    results = []
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text):
        try:
            search = ast.literal_eval(re.search(r"\{", text[pos:]).group())
            start_index = pos + text[pos:].find("{")
            obj, end_index = decoder.raw_decode(text, idx=start_index)
            if isinstance(obj, dict) and "action" in obj:
                results.append(obj)
            pos = end_index
        except:
            pos += 1

    # Fallback for Python dict strings
    if not results:
        try:
            matches = re.findall(r"(\{.*?\})", text, re.DOTALL)
            for match in matches:
                try:
                    clean = match.replace("true", "True").replace("false", "False").replace("null", "None")
                    obj = ast.literal_eval(clean)
                    if isinstance(obj, dict) and "action" in obj: results.append(obj)
                except:
                    continue
        except:
            pass

    return results


def sync_recent_jira_to_graph(hours: int = 24) -> str:
    """Tool สำหรับให้ Apollo สั่งดึงตั๋วล่าสุดจาก Jira แล้วอัดเข้า Graph Database"""
    print(f"🔄 [Jira Sync Tool] Syncing Jira issues updated in last {hours} hours...")

    # 1. ดึง Key ของตั๋วที่เพิ่งอัปเดต (จาก jira_ops.py)
    from core.tools.jira_ops import get_recently_updated_issues, get_jira_issue
    from core.tools.neo4j_ops import sync_ticket_to_graph
    
    issues_list = get_recently_updated_issues(hours)
    if not issues_list:
        return "✅ Graph Sync Complete: No new tickets found in the specified timeframe."

    success_count = 0
    # 2. วนลูปดึงรายละเอียดตั๋วทีละใบ แล้วยัดลง Graph
    for issue in issues_list:
        issue_key = issue.get("key")
        if not issue_key: continue

        # ใช้ Tool เดิมที่มีอยู่แล้วดึงรายละเอียด
        details = get_jira_issue(issue_key)
        if details.get("success"):
            # โยนเข้า Neo4j
            is_saved = sync_ticket_to_graph(details)
            if is_saved:
                success_count += 1

    return f"✅ Graph Sync Complete: Successfully updated {success_count} out of {len(issues_list)} tickets to Neo4j Graph."


def sync_recent_tickets(hours: int = 24) -> str:
    """
    Automatically syncs tickets that were updated within the last N hours.
    Useful for keeping the knowledge base fresh.
    """
    # 🟢 [LAZY LOAD]
    from core.tools.jira_ops import get_recently_updated_issues
    logger.info(f"🔄 Starting batch sync for the last {hours} hours...")

    # 1. ไปดึง Keys มา
    issue_keys = get_recently_updated_issues(hours)

    if not issue_keys:
        return f"✅ No tickets were updated in the last {hours} hours. Everything is up to date!"

    # 2. วนลูป Sync ทีละตัว (ใช้ function sync_ticket เดิมที่มีอยู่)
    sync_results = []
    for key in issue_keys:
        try:
            status = sync_ticket_to_knowledge_base(key)
            sync_results.append(f"- {key}: {status}")
        except Exception as e:
            logger.error(f"❌ Failed to sync {key}: {e}")
            sync_results.append(f"- {key}: FAILED (Error: {str(e)})")

    return f"🚀 Sync Complete for the last {hours}h:\n" + "\n".join(sync_results)


def sync_ticket_to_knowledge_base(issue_key: str) -> str:
    """
    Orchestrate the sync process:
    Read Jira -> Extract Info using LLM & Embeddings -> Delegate to knowledge_ops to save (SQL + Graph)
    """
    # 🟢 [LAZY LOAD]
    from core.tools.jira_ops import get_jira_issue
    from core.tools.knowledge_ops import save_knowledge
    from core.llm_client import query_qwen, get_text_embedding  # ✅ โหลด Tool สำหรับทำ Vector

    logger.info(f"🔄 Syncing Ticket to Databases: {issue_key}")

    # 1. ดึงข้อมูลครั้งเดียวจาก Jira (One Shot)
    ticket_data = get_jira_issue(issue_key)

    # เช็คว่า Error ไหม
    if not ticket_data or not ticket_data.get("success"):
        return f" Sync Failed: {ticket_data.get('error', 'Failed to fetch data from Jira')}"

    logger.info(f" Extracting knowledge via LLM for {issue_key}...")

    #  Extract Variables  for 
    raw_content = ticket_data["ai_content"]
    real_status = ticket_data["status"]
    real_type = ticket_data["issue_type"]
    real_summary = ticket_data["summary"]
    real_parent_key = ticket_data.get("parent_key")
    real_issue_links = ticket_data.get("issue_links")
    real_assignee = ticket_data.get("assignee")
    real_story_point = ticket_data.get("story_point")
    real_epic_key = ticket_data.get("epic_key")
    real_epic_name = ticket_data.get("epic_name")
    
    # [NEW] Fallback: Find root epic if epic_key is None
    if not real_epic_key:
        from core.tools.jira_ops import find_root_epic
        real_epic_key = find_root_epic(ticket_data.get("issue_key"))

    # ใช้สมอง (Qwen) สรุปข้อมูล
    # 🟢 [NEW] Update raw_content with resolved epic key
    if real_epic_key:
        raw_content = raw_content.replace(f"EPIC: None", f"EPIC: {real_epic_key}")
    
    extraction_prompt = [
        {"role": "system", "content": """
        You are a Data Extractor parsing Jira ticket content into structured JSON.
        Extract the following fields strictly:
        - summary: The title of the ticket.
        - status: The current status (e.g., To Do, Done).
        - business_logic: The core rules and requirements.
        - technical_spec: API endpoints, database changes, or technical constraints.
        - test_scenarios: Test cases and validation requirements.
        - issue_type: (Story, Bug, Task, Epic, Subtask).
        - epic_key: The Epic this ticket belongs to (extract from EPIC: field).

        EXTRACT GRAPH ENTITIES (Crucial):
        - components: List of technical components/systems mentioned (e.g., ["Payment API", "PostgreSQL", "Frontend UI"]). Empty list if none.
        - implicit_depends_on: List of OTHER ticket keys mentioned in text that this ticket depends on (e.g., ["SCRUM-29", "SCRUM-31"]). Empty list if none.

        STRICT RULES:
        1. Use double quotes (") for keys and string values.
        2. Escape inner quotes properly (e.g. "behavior": "Returns \\"Error\\" message").
        3. Do NOT use single quotes (') for JSON strings.
        4. Output JSON ONLY. No markdown, no explanations.
        """},
        {"role": "user", "content": f"Parse this ticket content:\n\n{raw_content}"}
    ]

    try:
        # Helper Serialize
        def safe_serialize(obj):
            if isinstance(obj, (dict, list)):
                return json.dumps(obj, ensure_ascii=False, indent=2)
            return str(obj) if obj else "-"

        llm_response = query_qwen(extraction_prompt)

        # Handle Response Type
        if isinstance(llm_response, dict):
            content_text = llm_response.get('content', '') or llm_response.get('message', {}).get('content', '')
        else:
            content_text = str(llm_response)

        # 🛡️ Safety Clean
        content_text = content_text.strip()
        if content_text.startswith("```json"): content_text = content_text[7:]
        if content_text.endswith("```"): content_text = content_text[:-3]
        content_text = content_text.strip()

        # แปลงเป็น Dict (เรียกใช้ Global Helper robust_json_parser)
        data = robust_json_parser(content_text)
        vector_ready_text = f"""
                TICKET: {issue_key}
                SUMMARY: {real_summary}
                TYPE: {real_type}
                STATUS: {real_status}
                BUSINESS LOGIC: {safe_serialize(data.get("business_logic"))}
                TECHNICAL SPEC: {safe_serialize(data.get("technical_spec"))}
                COMPONENTS: {", ".join(data.get("components", []))}
                """

        # 🎯 [NEW] ดึง Vector Embedding ก่อนเซฟ
        embedding_vector = get_text_embedding(vector_ready_text)
        # 👇 [เพิ่มบรรทัดนี้ลงไปเพื่อแอบดู] 👇
        print(f"📊 DEBUG Vector Size: {len(embedding_vector)} dimensions")


        # 🗄️ โยนทุกอย่างให้ knowledge_ops จัดการเซฟ (SQL + Neo4j Graph)
        result = save_knowledge(
            issue_key=issue_key,
            summary=real_summary,
            status=real_status,
            business_logic=safe_serialize(data.get("business_logic")),
            technical_spec=safe_serialize(data.get("technical_spec")),
            test_scenarios=safe_serialize(data.get("test_scenarios")),
            issue_type=real_type,
            parent_key=real_parent_key,
            issue_links=real_issue_links,
            assignee=real_assignee,
            story_point=real_story_point,
            epic_key=real_epic_key,
            epic_name=real_epic_name,
            # ✅ โยนของใหม่ไปให้ท่อ Neo4j ด้านในทำต่อ
            ticket_data=ticket_data,
            extracted_data=data,
            embedding_vector=embedding_vector,
            raw_text=raw_content
        )

        return f"✅ Sync Flow Completed for {issue_key}!\nDetails: {result}"

    except json.JSONDecodeError as je:
        logger.error(f" JSON Error: {je} \nRaw Text: {content_text}")
        save_knowledge(
            issue_key=issue_key,
            summary=f"[AI Error] {real_summary}",
            status=real_status,
            business_logic=f" AI Parsing Failed. Raw Content:\n{raw_content[:2000]}",
            technical_spec="-",
            test_scenarios="-",
            issue_type=real_type,
            parent_key=real_parent_key,
            issue_links=real_issue_links,
            assignee=real_assignee,
            story_point=real_story_point,
            epic_key=real_epic_key,
            epic_name=real_epic_name,
            ticket_data=ticket_data  # ส่งข้อมูลดิบไปให้รอดำเนินการทำ Graph ได้แม้ AI จะพัง
        )
        return f" Synced {issue_key} (Meta PostgREST OK, but AI Analysis failed). Saved raw content."

    except Exception as e:
        logger.error(f" General Error: {e}")
        save_knowledge(
            issue_key=issue_key,
            summary=f"[Error] {real_summary}",
            status=real_status,
            business_logic=f" Error Occurred. Raw Content:\n{raw_content[:2000]}",
            technical_spec="-",
            test_scenarios="-",
            issue_type=real_type,
            parent_key=real_parent_key,
            issue_links=real_issue_links,
            assignee=real_assignee,
            story_point=real_story_point,
            epic_key=real_epic_key,
            epic_name=real_epic_name,
            ticket_data=ticket_data  # ส่งข้อมูลดิบไปให้รอดำเนินการทำ Graph ได้แม้ AI จะพัง
        )
        return f" Synced {issue_key} (Meta PostgREST OK, but an error occurred). Saved raw content."


if __name__ == "__main__":
    import sys
    
    # 1.  Validate and parse command line arguments
    if len(sys.argv) > 1:
        try:
            hours = int(sys.argv[1])
            if hours < 1:
                print("Error: LOOKBACK_HOURS must be greater than 0")
                sys.exit(1)
        except ValueError:
            print("Error: LOOKBACK_HOURS must be a valid number")
            sys.exit(1)
    else:
        hours = 24
    
    # 2.  Display start message
    print(f"Jira Sync Pipeline: Starting sync for the last {hours} hours...")
    from datetime import datetime
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 3.  Execute main sync function
    try:
        result = sync_recent_tickets(hours)
        print(result)
        
        # 4.  Provide clear completion status
        if "No tickets were updated" in result:
            print("STATUS: No sync needed - all tickets up to date")
        elif "Sync Complete" in result:
            print("STATUS: Sync completed successfully")
        else:
            print("STATUS: Sync completed with warnings")
            
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)

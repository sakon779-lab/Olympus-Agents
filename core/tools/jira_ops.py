import requests
from requests.auth import HTTPBasicAuth
import logging
from core.config import settings

logger = logging.getLogger("JiraOps")


def get_recently_updated_issues(hours: int = 24) -> list:
    """
    กวาดรายชื่อ Issue Key ที่มีการอัปเดตในช่วง N ชั่วโมงที่ผ่านมา โดยใช้ JQL
    """
    # 1. สร้าง JQL: ค้นหา Ticket ที่ updated >= -Nh และเรียงจากใหม่ไปเก่า
    jql = f'updated >= "-{hours}h" ORDER BY updated DESC'

    url = f"{settings.JIRA_URL}/rest/api/3/search/jql"
    auth = HTTPBasicAuth(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
    # ✅ ใช้ Headers ที่เรียบง่ายที่สุด (ไม่ต้องมี Content-Type เพราะไม่ได้ส่ง body)
    jira_headers = {
        "Accept": "application/json"
    }

    # ✅ ส่งข้อมูลผ่าน Parameters (query string) แทน JSON payload
    params = {
        "jql": jql,
        "maxResults": 50,
        "fields": "key"
    }

    try:
        logger.info(f"🔎 Scanning Jira updates (Last {hours} hours) with JQL: {jql}")

        response = requests.get(
            url,
            params=params,
            headers=jira_headers,
            auth=auth,
            verify=False
        )

        if response.status_code == 200:
            data = response.json()
            issues = data.get('issues', [])

            # ดึงเฉพาะ key ออกมาเป็น list [ "SCRUM-20", "SCRUM-21", ... ]
            issue_keys = [issue.get('key') for issue in issues if issue.get('key')]

            logger.info(f"✅ Found {len(issue_keys)} updated tickets: {issue_keys}")
            return issue_keys
        else:
            logger.error(f"❌ Failed to search Jira. Status: {response.status_code}, Response: {response.text}")
            return []

    except Exception as e:
        logger.error(f"❌ Exception during Jira search: {e}")
        return []

def get_jira_issue(issue_key: str) -> dict:
    """
    Fetches ALL details of a Jira ticket in one go.
    Returns a dict containing both Metadata (for DB) and Formatted Text (for AI).
    """
    url = f"{settings.JIRA_URL}/rest/api/3/issue/{issue_key}"
    auth = HTTPBasicAuth(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
    headers = {
        "Accept": "application/json"
    }

    try:
        # 🚀 ยิง API ครั้งเดียวจบ
        response = requests.get(url, headers=headers, auth=auth)

        if response.status_code == 200:
            data = response.json()
            fields = data.get('fields', {})

            # 1. Basic Fields (Safe Access)
            summary = fields.get('summary', 'No Summary')
            # Handle Description carefully (API might return null)
            desc_raw = fields.get('description')
            description_adf = str(desc_raw) if desc_raw else ""

            # Handle Nested Objects safely
            status_obj = fields.get('status') or {}
            status = status_obj.get('name', 'Unknown') if isinstance(status_obj, dict) else str(status_obj)

            type_obj = fields.get('issuetype') or {}
            issue_type = type_obj.get('name', 'Task') if isinstance(type_obj, dict) else str(type_obj)

            # 🟢 [SAFE] 2. Extract Parent Key
            parent_obj = fields.get('parent') or {}
            parent_key = parent_obj.get('key') if isinstance(parent_obj, dict) else None

            # 🟢 [SAFE] 3. Extract Issue Links (Fix TypeError)
            raw_links = fields.get('issuelinks', [])
            formatted_links = []

            if isinstance(raw_links, list):
                for link in raw_links:
                    if not isinstance(link, dict): continue  # ข้ามถ้าไม่ใช่ Dict

                    # กรณี A: Outward
                    if 'outwardIssue' in link:
                        outward = link.get('outwardIssue', {})
                        if isinstance(outward, dict):
                            rel_type = link.get('type', {}).get('outward', 'relates to')
                            target_key = outward.get('key', 'Unknown')
                            formatted_links.append({"type": rel_type, "target": target_key, "direction": "outward"})

                    # กรณี B: Inward
                    elif 'inwardIssue' in link:
                        inward = link.get('inwardIssue', {})
                        if isinstance(inward, dict):
                            rel_type = link.get('type', {}).get('inward', 'related to')
                            target_key = inward.get('key', 'Unknown')
                            formatted_links.append({"type": rel_type, "target": target_key, "direction": "inward"})

            # Update Context for AI (AI ชอบ String อ่านง่ายๆ)
            # เราต้องแปลงเฉพาะตอนส่งให้ AI อ่าน
            links_text_for_ai = ", ".join(
                [f"{l['type']} {l['target']}" for l in formatted_links]) if formatted_links else "None"

            # ✅ สร้าง Formatted String สำหรับส่งให้ AI อ่าน (รวมไว้ใน dict เลย)
            ai_context_text = (
                f"TICKET: {issue_key}\n"
                f"SUMMARY: {summary}\n"
                f"TYPE: {issue_type}\n"
                f"STATUS: {status}\n"
                f"PARENT: {parent_key if parent_key else 'None'}\n"
                f"LINKS: {links_text_for_ai}\n"
                f"REQUIREMENTS: {description_adf}"
            )

            # Return ก้อนเดียว มีครบทุกอย่าง
            return {
                "success": True,
                "issue_key": issue_key,
                "summary": summary,
                "status": status,
                "issue_type": issue_type,
                "description": description_adf,
                "parent_key": parent_key,
                "issue_links": formatted_links,
                "ai_content": ai_context_text  # <-- AI เอาอันนี้ไปใช้
            }
        else:
            error_msg = f"❌ Error: Failed to fetch {issue_key}. Status: {response.status_code}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

    except Exception as e:
        error_msg = f"❌ Exception: {e}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
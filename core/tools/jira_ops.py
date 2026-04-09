import requests
from requests.auth import HTTPBasicAuth
import logging
from core.config import settings

logger = logging.getLogger("JiraOps")


def find_root_epic(issue_key: str, max_depth: int = 5) -> str | None:
    """
    Traverse up Jira parent hierarchy to find root Epic.
    """
    current_key = issue_key
    depth = 0
    
    while current_key and depth < max_depth:
        # Fetch data for current issue
        result = get_jira_issue(current_key)
        
        # Break if fetch fails or no result
        if not result or not result.get('success'):
            break
            
        # 1. Is current issue Epic?
        if result.get('issue_type') == 'Epic':
            return current_key
            
        # 2. If not, get parent key to check in next iteration
        parent_key = result.get('parent_key')
        
        # Break if there is no parent (reached top without finding an Epic)
        if not parent_key:
            break
            
        # Move up to parent
        current_key = parent_key
        depth += 1
        
    return None # Epic not found within max_depth


def get_recently_updated_issues(hours: int = 24) -> list:
    """
    กวาดรายชื่อ Issue Key ที่มีการอัปเดตในช่วง N ชั่วโมงที่ผ่านมา โดยใช้ JQL
    """
    jql = f'updated >= "-{hours}h" ORDER BY updated DESC'
    url = f"{settings.JIRA_URL}/rest/api/3/search/jql"
    auth = HTTPBasicAuth(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)

    jira_headers = {
        "Accept": "application/json"
    }

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
        response = requests.get(url, headers=headers, auth=auth)

        if response.status_code == 200:
            data = response.json()
            fields = data.get('fields', {})

            # 1. Basic Fields
            summary = fields.get('summary', 'No Summary')
            desc_raw = fields.get('description')
            description_adf = str(desc_raw) if desc_raw else ""

            status_obj = fields.get('status') or {}
            status = status_obj.get('name', 'Unknown') if isinstance(status_obj, dict) else str(status_obj)

            type_obj = fields.get('issuetype') or {}
            issue_type = type_obj.get('name', 'Task') if isinstance(type_obj, dict) else str(type_obj)

            parent_obj = fields.get('parent') or {}
            parent_key = parent_obj.get('key') if isinstance(parent_obj, dict) and parent_obj.get('key') else None

            # 🟢 [NEW] 1.1 Extract Assignee
            assignee_obj = fields.get('assignee') or {}
            assignee = assignee_obj.get('displayName', 'Unassigned') if isinstance(assignee_obj, dict) else 'Unassigned'

            # 🟢 [NEW] 1.2 Extract Story Points
            # Jira มักจะซ่อน Story Point ไว้ใน customfield (ส่วนใหญ่คือ 10016 หรือ 10026)
            story_point_raw = (
                    fields.get('customfield_10016') or
                    fields.get('customfield_10026') or
                    fields.get('storyPoints')  # กรณีใช้ plugin บางตัว
            )
            try:
                # Handle empty string, None, or invalid values
                if story_point_raw is None or story_point_raw == '':
                    story_point = None
                else:
                    story_point = float(story_point_raw)
            except (ValueError, TypeError):
                story_point = None

            # 🟢 [NEW] 1.3 Extract Epic Link
            # Epic Link มักจะอยู่ใน customfield_10011
            epic_obj = fields.get('customfield_10011') or {}
            epic_key = epic_obj.get('key') if isinstance(epic_obj, dict) else None
            
            # ดึง Epic Name ด้วย (customfield_10014)
            epic_name = fields.get('customfield_10014')
            epic_name = epic_name if epic_name and epic_name.strip() else None

            # 2. Extract Issue Links
            raw_links = fields.get('issuelinks', [])
            formatted_links = []

            if isinstance(raw_links, list):
                for link in raw_links:
                    if not isinstance(link, dict): continue

                    if 'outwardIssue' in link:
                        outward = link.get('outwardIssue', {})
                        if isinstance(outward, dict):
                            rel_type = link.get('type', {}).get('outward', 'relates to')
                            target_key = outward.get('key', 'Unknown')
                            formatted_links.append({"type": rel_type, "target": target_key, "direction": "outward"})

                    elif 'inwardIssue' in link:
                        inward = link.get('inwardIssue', {})
                        if isinstance(inward, dict):
                            rel_type = link.get('type', {}).get('inward', 'related to')
                            target_key = inward.get('key', 'Unknown')
                            formatted_links.append({"type": rel_type, "target": target_key, "direction": "inward"})

            links_text_for_ai = ", ".join(
                [f"{l['type']} {l['target']}" for l in formatted_links]) if formatted_links else "None"

            # ✅ เพิ่ม ASSIGNEE, STORY POINTS และ EPIC ให้ AI อ่านด้วย
            ai_context_text = (
                f"TICKET: {issue_key}\n"
                f"SUMMARY: {summary}\n"
                f"TYPE: {issue_type}\n"
                f"STATUS: {status}\n"
                f"ASSIGNEE: {assignee}\n"
                f"STORY POINTS: {story_point if story_point is not None else 'None'}\n"
                f"PARENT: {parent_key if parent_key else 'None'}\n"
                f"EPIC: {epic_key if epic_key else 'None'}\n"
                f"LINKS: {links_text_for_ai}\n"
                f"REQUIREMENTS: {description_adf}"
            )

            # Return ก้อนเดียว ส่งค่าใหม่กลับไปด้วย
            return {
                "success": True,
                "issue_key": issue_key,
                "summary": summary,
                "status": status,
                "issue_type": issue_type,
                "description": description_adf,
                "parent_key": parent_key,
                "issue_links": formatted_links,
                "assignee": assignee,  # ✅ ส่งกลับไปให้ Database
                "story_point": story_point,  # ✅ ส่งกลับไปให้ Database
                "epic_key": epic_key,  # ✅ ส่ง Epic Key กลับไปให้ Database
                "epic_name": epic_name,  # ✅ ส่ง Epic Name กลับไปให้ Database
                "ai_content": ai_context_text
            }
        else:
            error_msg = f"❌ Error: Failed to fetch {issue_key}. Status: {response.status_code}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

    except Exception as e:
        error_msg = f"❌ Exception: {e}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
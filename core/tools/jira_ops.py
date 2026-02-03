import requests
from requests.auth import HTTPBasicAuth
import logging
from core.config import settings

logger = logging.getLogger("JiraOps")


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

            # Extract fields
            summary = fields.get('summary', 'No Summary')
            description_adf = str(fields.get('description', ''))

            # Handle Nested Objects safely
            status = fields.get('status', {}).get('name', 'Unknown')
            issue_type = fields.get('issuetype', {}).get('name', 'Task')

            # ✅ สร้าง Formatted String สำหรับส่งให้ AI อ่าน (รวมไว้ใน dict เลย)
            ai_context_text = (
                f"TICKET: {issue_key}\n"
                f"SUMMARY: {summary}\n"
                f"TYPE: {issue_type}\n"
                f"STATUS: {status}\n"
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
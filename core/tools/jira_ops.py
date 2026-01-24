import requests
from requests.auth import HTTPBasicAuth
import logging
# ✅ เปลี่ยนตรงนี้: Import settings object แทนตัวแปรแยก
from core.config import settings

# Setup Logger
logger = logging.getLogger("JiraOps")


def read_jira_ticket(issue_key: str) -> str:
    """
    Fetches details of a Jira ticket.
    Args:
        issue_key (str): The Jira ticket ID (e.g., SCRUM-26).
    Returns:
        str: Formatted ticket details.
    """
    # ✅ ใช้ settings.JIRA_... แทน
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

            summary = fields.get('summary', 'No Summary')
            description_adf = fields.get('description', {})

            # Simple ADF text extraction (เหมือนเดิม)
            description_text = "No Description"
            if description_adf:
                description_text = str(description_adf)

            result = (
                f"TICKET: {issue_key}\n"
                f"SUMMARY: {summary}\n"
                f"REQUIREMENTS: {description_text}"
            )
            return result
        else:
            return f"❌ Error: Failed to fetch {issue_key}. Status: {response.status_code} - {response.text}"

    except Exception as e:
        return f"❌ Exception: {e}"
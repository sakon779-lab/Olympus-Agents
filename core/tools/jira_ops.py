import requests
import base64
import json
import logging
from core.config import JIRA_URL, JIRA_EMAIL, JIRA_TOKEN

logger = logging.getLogger("JiraOps")


def read_jira_ticket(issue_key: str) -> str:
    """อ่านข้อมูล Requirement จาก Jira (Centralized)"""
    # logger.info(f"🔍 Reading Requirement: {issue_key}...")

    if not JIRA_EMAIL or not JIRA_TOKEN:
        return "⚠️ Jira Config Missing! Please interpret requirements from user input."

    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}"
    auth_str = f"{JIRA_EMAIL}:{JIRA_TOKEN}"
    auth_base64 = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {auth_base64}", "Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            fields = data.get('fields', {})
            summary = fields.get('summary', 'No Summary')
            description = fields.get('description', 'No Description')

            # แปลง Description object ให้เป็น String
            desc_text = json.dumps(description)
            return f"TICKET: {issue_key}\nSUMMARY: {summary}\nREQUIREMENTS: {desc_text}"
        return f"❌ Ticket {issue_key} not found."
    except Exception as e:
        return f"❌ Connection Error: {e}"
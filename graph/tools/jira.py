import os
import httpx
from langchain_core.tools import tool


# 👇 1. ฟังก์ชันช่วยแกะ Text จากโครงสร้าง JSON ของ Jira (ADF)
def extract_text_from_adf(adf_node):
    """
    Recursively extract text from Atlassian Document Format (ADF) JSON.
    """
    if adf_node is None:
        return ""

    # ถ้าเป็น string อยู่แล้ว (กรณี Jira Server เก่าๆ) ก็คืนค่าเลย
    if isinstance(adf_node, str):
        return adf_node

    texts = []

    # ถ้าเป็น Dict (Node)
    if isinstance(adf_node, dict):
        # 1. ถ้าเจอ key "text" ให้เก็บค่าไว้
        if "text" in adf_node:
            texts.append(adf_node["text"])

        # 2. ถ้าเจอ key "content" (ลูกๆ) ให้วนลูปเข้าไปแกะต่อ (Recursive)
        if "content" in adf_node and isinstance(adf_node["content"], list):
            for child in adf_node["content"]:
                texts.append(extract_text_from_adf(child))

    # ถ้าเป็น List (Array ของ Node)
    elif isinstance(adf_node, list):
        for item in adf_node:
            texts.append(extract_text_from_adf(item))

    # เอาข้อความทั้งหมดมาต่อกัน (ขั้นด้วย space ถ้าจำเป็น หรือต่อเลย)
    return " ".join(texts)

@tool
def search_jira_issues(jql_query: str = "project = SCRUM ORDER BY created DESC") -> str:
    """
    Searches for Jira tickets using JQL and returns a list of Issue Keys.
    Args:
        jql_query: JQL string (default: all issues in project, newest first)
    """
    jira_url = os.getenv("JIRA_URL")
    email = os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")

    if not all([jira_url, email, token]):
        return "Error: Jira credentials missing."

    auth = (email, token)
    headers = {"Accept": "application/json"}

    # maxResults=50 (ดึงทีละ 50 ใบพอก่อน กันระบบสำลัก)
    url = f"{jira_url}/rest/api/3/search?jql={jql_query}&fields=key&maxResults=50"

    try:
        with httpx.Client() as client:
            response = client.get(url, auth=auth, headers=headers)
            if response.status_code != 200:
                return f"Error searching issues: {response.text}"

            data = response.json()
            issues = data.get("issues", [])

            # ดึงเฉพาะ Key ออกมาเป็น List
            # เช่น "Found 3 issues: SCRUM-16, SCRUM-5, SCRUM-4"
            keys = [i["key"] for i in issues]

            if not keys:
                return "No issues found."

            return f"Found {len(keys)} issues: {', '.join(keys)}"

    except Exception as e:
        return f"Exception searching issues: {str(e)}"


@tool
def get_jira_ticket(issue_key: str) -> str:
    """
    Fetches details of a Jira ticket (Summary, Status, Description) by its Key.
    Useful when you need to read requirements or checking status.
    Args:
        issue_key: The ID of the ticket, e.g., "PAY-001"
    """
    # ดึง Config จาก Environment
    jira_url = os.getenv("JIRA_URL")
    email = os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")

    # Check config
    if not all([jira_url, email, token]):
        return "Error: Jira credentials are missing in .env"

    auth = (email, token)
    headers = {"Accept": "application/json"}

    # Clean URL (เผื่อ User ลืมใส่ https หรือมี / ปิดท้าย)
    base_url = jira_url.rstrip("/")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    url = f"{base_url}/rest/api/3/issue/{issue_key}"

    try:
        # ใช้ Synchronous Client (httpx)
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, auth=auth, headers=headers)

            if response.status_code == 404:
                return f"Jira Ticket {issue_key} not found."
            if response.status_code != 200:
                return f"Error: {response.status_code} - {response.text}"

            data = response.json()
            fields = data.get("fields", {})

            # --- 0. EXTRACT BASIC INFO ---
            issue_type_name = fields.get("issuetype", {}).get("name", "Unknown")
            status_name = fields.get("status", {}).get("name", "Unknown")
            summary = fields.get("summary", "No Summary")

            # --- 1. FIX PARENT KEY ---
            parent_info = fields.get("parent", {})
            parent_key = parent_info.get("key", "None")

            # --- 2. EXTRACT LINKS ---
            raw_links = fields.get("issuelinks", [])
            formatted_links = []

            for link in raw_links:
                link_type = link.get("type", {}).get("name", "Related")

                # Logic เดิมของคุณ (ดีอยู่แล้ว)
                if "outwardIssue" in link:
                    target = link["outwardIssue"]["key"]
                    direction = "outward"
                    desc = link.get("type", {}).get("outward", link_type)
                elif "inwardIssue" in link:
                    target = link["inwardIssue"]["key"]
                    direction = "inward"
                    desc = link.get("type", {}).get("inward", link_type)
                else:
                    continue

                formatted_links.append(f"- {desc} {target} ({direction})")

            links_text = "\n".join(formatted_links) if formatted_links else "None"

            # --- 3. CLEAN DESCRIPTION (จุดสำคัญที่แก้) ---
            raw_description = fields.get('description')

            # เรียกใช้ฟังก์ชันแกะ Text ที่เราสร้างข้างบน
            clean_description = extract_text_from_adf(raw_description)

            # ถ้าว่างให้ใส่ default text
            if not clean_description.strip():
                clean_description = "No Description provided."

            # สร้าง Output Format ให้ AI อ่านง่ายที่สุด
            return f"""
            --- TICKET FOUND: {issue_key} ---
            Summary: {summary}
            Issue Type: {issue_type_name}
            Status: {status_name}
            Parent Key: {parent_key}
            
            Linked Issues:
            {links_text}
            
            Description:
            {clean_description}
            ---------------------------------
            """

    except Exception as e:
        return f"Exception fetching ticket {issue_key}: {str(e)}"
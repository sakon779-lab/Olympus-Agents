import os
from typing import List
from pydantic_settings import BaseSettings

# หา Path ของ Project Root ให้ชัวร์
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    # --- 🗄️ Database ---
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "secret"
    DB_NAME: str = "payment_poc"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    # --- 🎫 JIRA ---
    JIRA_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""

    # --- 🔑 Secrets ---
    GITHUB_TOKEN: str = ""

    # --- 📂 Paths ---
    BASE_WORKSPACE_DIR: str = r"D:\WorkSpace"

    # --- 🔗 Repositories (URLs) ---
    # Repo หลักสำหรับ Dev (Hephaestus)
    DEV_REPO_URL: str = "https://github.com/sakon779-lab/payment.git"

    # Repo สำหรับ QA/Test (Athena, Arthemis)
    QA_REPO_URL: str = "https://github.com/sakon779-lab/qa-automation-repo.git"

    # --- 🆔 Identity ---
    CURRENT_AGENT_NAME: str = "Common"

    # รายชื่อ Agent ที่สังกัดทีม QA (จะถูกบังคับให้ใช้ QA Repo)
    QA_AGENT_NAMES: List[str] = ["Athena", "Artemis"]

    # ✅ AI CONFIGURATION
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    # แนะนำใช้ 7b ถ้าเครื่อง RAM น้อย หรือ 14b ถ้าเครื่องแรง
    MODEL_NAME: str = "qwen2.5-coder:14b"

    # =========================================================
    # ⚙️ LOGIC PROPERTIES (The Magic Happens Here)
    # =========================================================

    @property
    def is_qa_agent(self) -> bool:
        """เช็คว่า Agent ปัจจุบันเป็นทีม QA หรือไม่"""
        return self.CURRENT_AGENT_NAME in self.QA_AGENT_NAMES

    @property
    def TARGET_REPO_URL(self) -> str:
        """
        เลือก URL ตาม Role (Dev vs QA) และแทรก Token ให้อัตโนมัติ
        """
        # 1. เลือก Repo ตาม Role ของ Agent
        if self.is_qa_agent:
            raw_url = self.QA_REPO_URL
        else:
            raw_url = self.DEV_REPO_URL

        # 2. ถ้ามี Token ใน .env ให้แทรกเข้าไปใน URL (เพื่อ Bypass Login)
        # ผลลัพธ์: https://ghp_xxx@github.com/user/repo.git
        if self.GITHUB_TOKEN and "github.com" in raw_url and "@" not in raw_url:
            return raw_url.replace("https://", f"https://{self.GITHUB_TOKEN}@")

        return raw_url

    @property
    def DATABASE_URI(self) -> str:
        """ประกอบร่าง Connection String สำหรับ SQLAlchemy"""
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def PROJECT_NAME(self) -> str:
        """ดึงชื่อ Project จาก URL (เช่น payment หรือ qa-automation-repo)"""
        # เอา Token ออกก่อนหาชื่อ (เผื่อ URL มี Token แปะมา)
        clean_url = self.TARGET_REPO_URL.split("@")[-1]
        return clean_url.split("/")[-1].replace(".git", "")

    @property
    def AGENT_WORKSPACE(self) -> str:
        """
        สร้าง Path Workspace: D:\WorkSpace\{RepoName}_{AgentName}
        เช่น: D:\WorkSpace\payment_Hephaestus
             D:\WorkSpace\qa-automation-repo_Athena
        """
        folder_name = f"{self.PROJECT_NAME}_{self.CURRENT_AGENT_NAME}"
        return os.path.join(self.BASE_WORKSPACE_DIR, folder_name)

    @property
    def TEST_DESIGN_DIR(self) -> str:
        """กำหนดที่เก็บไฟล์ Test Design (CSV)"""
        return os.path.join(self.AGENT_WORKSPACE, "test_designs")

    # --- ⚙️ Pydantic Config ---
    class Config:
        env_file = os.path.join(BASE_DIR, ".env")
        env_file_encoding = 'utf-8'
        extra = "ignore"


settings = Settings()
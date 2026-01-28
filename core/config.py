import os
from pydantic_settings import BaseSettings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    # --- 🗄️ Database ---
    DB_USER: str = "postgres"      # ใส่ default เผื่อไว้ หรือบังคับรับจาก .env ก็ได้
    DB_PASSWORD: str = "secret"
    DB_NAME: str = "payment_poc"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    # --- 🎫 JIRA ---
    JIRA_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = "" # ⚠️ เช็คใน agent.py ให้ใช้ชื่อนี้ด้วยนะครับ

    # --- 📂 Paths ---
    BASE_WORKSPACE_DIR: str = r"D:\WorkSpace"

    # --- 🔗 Repositories (URLs) ---
    DEV_REPO_URL: str = "https://github.com/sakon779-lab/payment.git"
    QA_REPO_URL: str = "https://github.com/sakon779-lab/qa-automation-repo.git"

    # --- 🆔 Identity ---
    CURRENT_AGENT_NAME: str = "Common"

    # ✅ AI CONFIGURATION
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    MODEL_NAME: str = "qwen2.5-coder:14b"

    # 👇👇👇 ✅ เพิ่มตรงนี้ครับ (Helper Property) 👇👇👇
    @property
    def DATABASE_URI(self) -> str:
        """ประกอบร่าง Connection String สำหรับ SQLAlchemy / SQLDatabase"""
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    # 👆👆👆👆👆👆👆👆👆👆👆👆👆👆👆👆👆👆👆👆👆

    @property
    def TARGET_REPO_URL(self) -> str:
        if self.CURRENT_AGENT_NAME in ["Artemis", "Athena"]:
            return self.QA_REPO_URL
        return self.DEV_REPO_URL

    @property
    def PROJECT_NAME(self) -> str:
        return self.TARGET_REPO_URL.split("/")[-1].replace(".git", "")

    @property
    def AGENT_WORKSPACE(self) -> str:
        folder_name = f"{self.PROJECT_NAME}_{self.CURRENT_AGENT_NAME}"
        return os.path.join(self.BASE_WORKSPACE_DIR, folder_name)

    @property
    def TEST_DESIGN_DIR(self) -> str:
        return os.path.join(self.AGENT_WORKSPACE, "test_designs")

    class Config:
        env_file = os.path.join(BASE_DIR, ".env")
        env_file_encoding = 'utf-8'
        extra = "ignore"

settings = Settings()
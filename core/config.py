import os
from pydantic_settings import BaseSettings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    # --- 🗄️ Database ---
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    # --- 🎫 JIRA ---
    JIRA_URL: str
    JIRA_EMAIL: str
    JIRA_API_TOKEN: str

    # --- 📂 Paths ---
    BASE_WORKSPACE_DIR: str = r"D:\WorkSpace"

    # --- 🔗 Repositories (URLs) ---
    # ✅ ใส่ URL ตรงนี้เลยครับ Agent จะได้ไม่ต้องเดา
    DEV_REPO_URL: str = "https://github.com/sakon779-lab/payment.git"
    QA_REPO_URL: str = "https://github.com/sakon779-lab/qa-automation-repo.git"

    # --- 🆔 Identity ---
    CURRENT_AGENT_NAME: str = "Common"

    @property
    def TARGET_REPO_URL(self) -> str:
        """เลือก URL ตาม Role ของ Agent"""
        if self.CURRENT_AGENT_NAME in ["Artemis", "Athena"]:
            return self.QA_REPO_URL
        return self.DEV_REPO_URL

    @property
    def PROJECT_NAME(self) -> str:
        # ดึงชื่อโปรเจกต์จาก URL (เช่น 'payment' หรือ 'qa-automation-repo')
        return self.TARGET_REPO_URL.split("/")[-1].replace(".git", "")

    @property
    def AGENT_WORKSPACE(self) -> str:
        folder_name = f"{self.PROJECT_NAME}_{self.CURRENT_AGENT_NAME}"
        return os.path.join(self.BASE_WORKSPACE_DIR, folder_name)

    @property
    def TEST_DESIGN_DIR(self) -> str:
        # Test Design อยู่ใน Workspace ของ Agent เองเลย (หลังจาก Clone QA Repo มาแล้ว)
        return os.path.join(self.AGENT_WORKSPACE, "test_designs")

    class Config:
        env_file = os.path.join(BASE_DIR, ".env")
        env_file_encoding = 'utf-8'
        extra = "ignore"


settings = Settings()
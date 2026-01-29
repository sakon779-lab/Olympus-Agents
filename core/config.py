import os
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

    # --- 🔑 Secrets (สำคัญ! ต้องเพิ่มตรงนี้) ---
    GITHUB_TOKEN: str = ""  # <--- ถ้าไม่มีบรรทัดนี้ self.GITHUB_TOKEN จะ Error ครับ

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

    # --- ⚙️ Logic Properties ---

    @property
    def TARGET_REPO_URL(self) -> str:
        """
        เลือก URL ตาม Role และแทรก Token ให้อัตโนมัติ
        """
        # 1. เลือก Repo ตามชื่อ Agent
        if "QA" in self.CURRENT_AGENT_NAME.upper():
            raw_url = self.QA_REPO_URL
        else:
            raw_url = self.DEV_REPO_URL

        # 2. ถ้ามี Token ใน .env ให้แทรกเข้าไปใน URL (เพื่อ Bypass Login)
        if self.GITHUB_TOKEN and "github.com" in raw_url:
            # แทรก Token: https://TOKEN@github.com/...
            return raw_url.replace("https://", f"https://{self.GITHUB_TOKEN}@")

        return raw_url

    @property
    def DATABASE_URI(self) -> str:
        """ประกอบร่าง Connection String สำหรับ SQLAlchemy"""
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

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

    # --- ⚙️ Pydantic Config (ยุบรวมไว้ตรงนี้ที่เดียว) ---
    class Config:
        # ระบุ path ของ .env ให้ชัดเจน (กันหาไม่เจอ)
        env_file = os.path.join(BASE_DIR, ".env")
        env_file_encoding = 'utf-8'
        extra = "ignore"  # ค่าเกินไม่ error

settings = Settings()
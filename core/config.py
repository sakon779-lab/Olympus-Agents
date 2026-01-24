import os
from pydantic_settings import BaseSettings

# หา Path ของ Root Project (Olympus-Agents)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    # --- 🗄️ Database ---
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    # --- 🎫 JIRA Configuration (เพิ่มกลับมาครับ) ---
    JIRA_URL: str
    JIRA_EMAIL: str
    JIRA_API_TOKEN: str

    # --- 📂 Paths ---
    BASE_WORKSPACE_DIR: str = r"D:\WorkSpace"

    # Repositories
    DEV_REPO_PATH: str = r"D:\Project\PaymentBlockChain"
    QA_REPO_PATH: str = r"D:\Project\PaymentBlockChain_RobotTests"

    # --- 🆔 Identity (Dynamic) ---
    CURRENT_AGENT_NAME: str = "Common"

    @property
    def TEST_DESIGN_DIR(self) -> str:
        """
        ตำแหน่งเก็บไฟล์ Test Design (CSV)
        Path: {QA_REPO_PATH}/test_designs
        """
        # ใช้ QA Repo เป็นฐาน (ไม่ว่าจะรันโดยใคร ถ้าเรียก property นี้ต้องได้ path นี้)
        return os.path.join(self.QA_REPO_PATH, "test_designs")

    @property
    def TARGET_REPO_PATH(self) -> str:
        """Select Repo based on Agent Role"""
        # ✅ จับ Athena มาอยู่แก๊งเดียวกับ Artemis (QA Repo)
        if self.CURRENT_AGENT_NAME in ["Artemis", "Athena"]:
            return self.QA_REPO_PATH

        elif self.CURRENT_AGENT_NAME == "Hephaestus":
            return self.DEV_REPO_PATH

        return self.DEV_REPO_PATH

    @property
    def PROJECT_NAME(self) -> str:
        return os.path.basename(os.path.normpath(self.TARGET_REPO_PATH))

    @property
    def AGENT_WORKSPACE(self) -> str:
        """
        Dynamic Workspace Path
        Ex: D:\\WorkSpace\\PaymentBlockChain_Hephaestus
        """
        folder_name = f"{self.PROJECT_NAME}_{self.CURRENT_AGENT_NAME}"
        return os.path.join(self.BASE_WORKSPACE_DIR, folder_name)

    @property
    def DATABASE_URL(self):
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    class Config:
        env_file = os.path.join(BASE_DIR, ".env")
        env_file_encoding = 'utf-8'
        # สำคัญ: ให้ ignore ค่าอื่นๆ ใน .env ที่เราไม่ได้ประกาศในนี้
        extra = "ignore"


settings = Settings()
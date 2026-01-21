import os
from pydantic_settings import BaseSettings

# หา Path ของ Root Project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    # Field ที่เราต้องการ (Database)
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    @property
    def DATABASE_URL(self):
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    class Config:
        env_file = os.path.join(BASE_DIR, ".env")
        env_file_encoding = 'utf-8'
        # ✅ เพิ่มบรรทัดนี้: บอกให้เมินตัวแปรอื่นๆ ใน .env ที่เราไม่ได้ประกาศ (เช่น JIRA_*)
        extra = "ignore" 

settings = Settings()
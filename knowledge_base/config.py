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
        # Handle host that already contains protocol and port
        host = self.DB_HOST
        
        # Remove http:// or https:// prefix if present
        if host.startswith('http://'):
            host = host[7:]  # Remove 'http://'
        elif host.startswith('https://'):
            host = host[8:]  # Remove 'https://'
            
        # Check if host already contains port
        if ':' in host.split('/')[-1]:  # Check if there's a port after the last /
            # Host already has port, don't add DB_PORT
            return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{host}/{self.DB_NAME}"
        else:
            # Host doesn't have port, add DB_PORT
            port = self.DB_PORT if self.DB_PORT and str(self.DB_PORT).strip() else 5432
            return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{host}:{port}/{self.DB_NAME}"

    class Config:
        env_file = os.path.join(BASE_DIR, ".env")
        env_file_encoding = 'utf-8'
        # เพิ่มบรรทัดนี้: บอกให้เมินตัวแปรอื่นๆ ใน .env ที่เราไม่ได้ประกาศ (เช่น JIRA_*)
        extra = "ignore" 

settings = Settings()
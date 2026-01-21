import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

# 1. โหลด Environment Variables
load_dotenv()

USER = os.getenv("DB_USER", "postgres")
PASSWORD = os.getenv("DB_PASSWORD", "secretpassword")
SERVER = os.getenv("DB_HOST", "localhost")
PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "payment_poc")

# 2. สร้าง Connection String
# หมายเหตุ: ถ้าใช้ Driver อื่น (เช่น asyncpg) อาจต้องแก้ตรงนี้ แต่นี่คือ Standard
SQLALCHEMY_DATABASE_URL = f"postgresql://{USER}:{PASSWORD}@{SERVER}:{PORT}/{DB_NAME}?client_encoding=utf8"

# 3. สร้าง Base Class (ย้ายมาจาก base_class.py)
# คลาสนี้จะเป็นแม่แบบให้ Table ต่างๆ สืบทอด
class Base(DeclarativeBase):
    pass

# 4. สร้าง Engine (ย้ายมาจาก session.py)
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 5. สร้าง Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# (Optional) Helper function เผื่อใช้ในอนาคต
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
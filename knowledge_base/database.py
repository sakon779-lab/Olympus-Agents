from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# สร้าง Engine สำหรับ Postgres
# ไม่ต้องใช้ check_same_thread=False แล้ว เพราะ Postgres รองรับ Concurrency ดีอยู่แล้ว
engine = create_engine(settings.DATABASE_URL)

# Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base Model Class
Base = declarative_base()

def init_db():
    """สร้าง Table ทั้งหมดใน Postgres"""
    Base.metadata.create_all(bind=engine)
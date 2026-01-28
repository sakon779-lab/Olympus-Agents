# seed_data.py
import psycopg2
from core.config import settings

def seed_db():
    try:
        # เชื่อมต่อด้วยค่าจาก config
        conn = psycopg2.connect(
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT
        )
        cur = conn.cursor()

        # 1. สร้าง Table แบบง่ายๆ
        print("🛠️ Creating table 'users'...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50),
                email VARCHAR(100),
                role VARCHAR(20)
            );
        """)

        # 2. ยัดข้อมูลตัวอย่าง
        print("🌱 Seeding data...")
        cur.execute("INSERT INTO users (username, email, role) VALUES ('admin', 'admin@olympus.com', 'admin');")
        cur.execute("INSERT INTO users (username, email, role) VALUES ('apollo', 'apollo@olympus.com', 'bot');")
        cur.execute("INSERT INTO users (username, email, role) VALUES ('zeus', 'zeus@olympus.com', 'ceo');")

        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database seeded successfully!")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    seed_db()
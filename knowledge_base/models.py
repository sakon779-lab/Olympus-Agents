from sqlalchemy import Column, String, Numeric, Integer, Date, DateTime, ForeignKey, UniqueConstraint, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class JiraKnowledge(Base):
    __tablename__ = "jira_knowledge"

    # --- Identity ---
    issue_key = Column(String, primary_key=True, index=True)
    issue_type = Column(String, index=True, nullable=True)
    parent_key = Column(String, index=True, nullable=True)

    # ✅ ใช้ JSONB ตามความต้องการเดิม
    issue_links = Column(JSONB, nullable=True, comment="List of related issues")

    # --- Content ---
    summary = Column(String, nullable=False)

    # Knowledge Fields
    business_logic = Column(Text, nullable=True)
    technical_spec = Column(Text, nullable=True)
    test_scenarios = Column(Text, nullable=True)

    # --- Metadata ---
    status = Column(String, default="UNKNOWN")
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    raw_description = Column(Text, nullable=True)

    story_point = Column(Numeric(5, 2), nullable=True)
    assignee = Column(String(100), nullable=True)


# ==========================================
# 2. สร้าง Model ใหม่: ประวัติการเปลี่ยนสถานะ
# ==========================================
class JiraStatusHistory(Base):
    __tablename__ = 'jira_status_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ผูก Foreign Key กลับไปหา JiraKnowledge
    issue_key = Column(String, ForeignKey('jira_knowledge.issue_key', ondelete='CASCADE'), nullable=False)
    field_changed = Column(String(50), nullable=False)
    old_value = Column(String(255), nullable=True)
    new_value = Column(String(255), nullable=True)
    changed_at = Column(DateTime(timezone=True), nullable=False)
    changed_by = Column(String(100), nullable=True)


# ==========================================
# 3. สร้าง Model ใหม่: สรุป Metrics รายวัน
# ==========================================
class ProjectDailyMetrics(Base):
    __tablename__ = 'project_daily_metrics'

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(Date, nullable=False)
    project_key = Column(String(50), nullable=False)
    category = Column(String(50), nullable=True)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Numeric(15, 2), nullable=False)

    # บังคับ Unique Constraint ตามที่เราดีไซน์ไว้
    __table_args__ = (
        UniqueConstraint('snapshot_date', 'project_key', 'metric_name', name='uq_daily_metric'),
    )
from sqlalchemy import Column, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB  # ✅ ใช้ JSONB ของ Postgres
from .database import Base


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
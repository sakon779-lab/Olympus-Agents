from typing import TypedDict, Annotated, List, Dict, Any
from langgraph.graph.message import add_messages
import operator

class AgentState(TypedDict):
    # message history (เก็บแชทที่คุยกัน)
    messages: Annotated[List[Any], add_messages]

    # context data (เก็บข้อมูลดิบที่ดึงมาจาก Jira/DB)
    jira_context: Dict[str, Any]

    # internal logic flags
    next_step: str

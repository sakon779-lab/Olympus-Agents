import core.network_fix
import os
import sys
import json
import logging
import subprocess
import ast
import re
from pathlib import Path
from neo4j import GraphDatabase
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

# Import internal modules

from core.config import settings
from core.llm_client import query_qwen, get_text_embedding

# ตั้งค่า Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger("SyncPipeline")


# ========================= CODE INGESTOR FUNCTIONS =========================
class PythonCodeVisitor(ast.NodeVisitor):
    def __init__(self, file_path, source_code, epic_key):
        self.file_path = str(file_path)
        self.source_code = source_code
        self.epic_key = epic_key
        self.extracted_data = []

    def visit_FunctionDef(self, node):
        func_name = node.name
        docstring = ast.get_docstring(node)
        try:
            raw_code = ast.get_source_segment(self.source_code, node)
        except Exception:
            raw_code = ""

        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)

        self.extracted_data.append({
            "type": "function",
            "name": func_name,
            "file_path": self.file_path,
            "epic_key": self.epic_key,
            "docstring": docstring.strip() if docstring else "",
            "code_snippet": raw_code,
            "calls": list(set(calls))
        })
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        docstring = ast.get_docstring(node)
        self.extracted_data.append({
            "type": "class",
            "name": node.name,
            "file_path": self.file_path,
            "epic_key": self.epic_key,
            "docstring": docstring.strip() if docstring else "",
            "code_snippet": f"class {node.name}: ...",
            "calls": []
        })
        self.generic_visit(node)


def parse_python_file(file_path, epic_key):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            source_code = file.read()
        tree = ast.parse(source_code)
        visitor = PythonCodeVisitor(file_path, source_code, epic_key)
        visitor.visit(tree)
        return visitor.extracted_data
    except Exception as e:
        logger.warning(f"⚠️ ข้ามไฟล์ {file_path} เนื่องจาก Parse ไม่ผ่าน: {e}")
        return []


def scan_codebase(target_path: str, epic_key: str, exclude_dirs=None) -> list:
    if exclude_dirs is None:
        exclude_dirs = {".venv", "venv", "__pycache__", ".git", "node_modules", ".idea", "chroma_db", "logs", "pg_data"}

    files_to_parse = []
    
    if os.path.isfile(target_path):
        files_to_parse.append(Path(target_path))
    elif os.path.isdir(target_path):
        root_path = Path(target_path)
        for file_path in root_path.rglob("*.py"):
            if any(excluded in file_path.parts for excluded in exclude_dirs):
                continue
            files_to_parse.append(file_path)
    else:
        logger.error(f"❌ Path not found: {target_path}")
        return []

    logger.info(f"🔍 เริ่มสแกนโค้ดเป้าหมาย: {target_path} (Epic: {epic_key})")
    all_extracted_nodes = []

    for file_path in files_to_parse:
        logger.info(f"📄 กำลังอ่านไฟล์: {file_path}")
        extracted_nodes = parse_python_file(file_path, epic_key)
        all_extracted_nodes.extend(extracted_nodes)

    logger.info(f"✅ สแกนเสร็จสิ้น! พบ Class และ Function ทั้งหมด {len(all_extracted_nodes)} โหนด")
    return all_extracted_nodes


# ========================= CODE SUMMARIZER FUNCTIONS =========================
def summarize_code_node(node: dict) -> str:
    name = node.get("name", "Unknown")
    node_type = node.get("type", "function")
    docstring = node.get("docstring", "")
    code_snippet = node.get("code_snippet", "")

    if len(code_snippet) > 1500:
        code_snippet = code_snippet[:1500] + "\n...[TRUNCATED]..."

    system_prompt = """
    You are an expert Software Architect. Your task is to briefly summarize the purpose of a Python code snippet.
    - Keep it SHORT and CONCISE (1-3 sentences maximum).
    - Explain WHAT it does and WHY it exists in the system.
    - Focus on the business logic or core utility.
    - Respond ONLY with the summary. No introductory text.
    """

    user_prompt = f"""
    Type: {node_type}
    Name: {name}
    Docstring: {docstring}

    Code:
    ```python
    {code_snippet}
    ```
    """

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()}
    ]

    try:
        logger.info(f"🧠 กำลังให้ AI สรุป {node_type}: {name}...")
        response = query_qwen(messages, temperature=0.1)

        if isinstance(response, dict):
            summary = response.get('message', {}).get('content', '') or response.get('content', '')
        else:
            summary = str(response)

        return summary.strip()

    except Exception as e:
        logger.error(f"❌ Error summarizing {name}: {e}")
        return "Failed to generate summary."


def process_extracted_nodes(nodes: list) -> list:
    logger.info(f"📂 พบข้อมูลทั้งหมด {len(nodes)} โหนด กำลังเริ่มกระบวนการสรุป...")
    processed_nodes = []

    for i, node in enumerate(nodes):
        logger.info(f"⏳ [{i + 1}/{len(nodes)}] Processing: {node.get('name')}")
        if node.get("ai_summary"):
            processed_nodes.append(node)
            continue

        summary = summarize_code_node(node)
        node["ai_summary"] = summary
        processed_nodes.append(node)

    logger.info(f"🎉 เสร็จสิ้น! ประมวลผล {len(processed_nodes)} โหนดเรียบร้อย")
    return processed_nodes


# ========================= CODE TO GRAPH FUNCTIONS =========================
def chunk_code_with_sliding_window(name: str, docstring: str, code_snippet: str, chunk_size=1000, overlap=200):
    if not code_snippet:
        return []

    lines = code_snippet.strip().splitlines()
    sig_lines = []
    for line in lines:
        sig_lines.append(line)
        if line.strip().endswith(':'):
            break
            
    signature = "\n".join(sig_lines)
    
    # 🌟 [FIX] ป้องกัน Signature บวมเกินไป (เผื่อโค้ดที่หาเครื่องหมาย : ไม่เจอ)
    if len(signature) > 300:
        signature = signature[:300] + " ...[TRUNCATED]"

    # 🌟 [FIX] ป้องกัน Docstring บวมเกินไป
    safe_docstring = docstring[:300] + "..." if docstring and len(docstring) > 300 else docstring

    header = (
        f"=== CODE CHUNK ===\n"
        f"Function/Class: {name}\n"
        f"Signature: {signature}\n"
        f"Docstring: {safe_docstring or 'None'}\n"
        f"--- Code Source ---\n"
    )

    splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.PYTHON,
        chunk_size=chunk_size,
        chunk_overlap=overlap
    )
    raw_chunks = splitter.split_text(code_snippet)
    return [f"{header}{chunk}" for chunk in raw_chunks]


def ingest_code_to_graph(nodes_data: list):
    logger.info(f"📂 กำลังนำเข้าข้อมูล {len(nodes_data)} โหนดลง Neo4j...")
    logger.info("🔌 กำลังเชื่อมต่อ Neo4j...")
    
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )

    with driver.session() as session:
        for i, data in enumerate(nodes_data):
            logger.info(f"⏳ [{i + 1}/{len(nodes_data)}] Ingesting Node & Chunks: {data['name']}")

            summary = data.get("ai_summary", "")
            # 🌟 [FIX] ปรับลดเหลือ 2000 เพื่อให้รอดแน่ๆ (โมเดลส่วนใหญ่รับได้สบาย)
            safe_summary = summary[:2000] if summary else ""
            embedding = get_text_embedding(safe_summary) if safe_summary else []
            
            node_id = f"{data['file_path']}::{data['name']}"
            epic_key = data.get("epic_key", "SCRUM-32")
            code_snippet = data.get('code_snippet', '')

            query_node = """
            MERGE (c:CodeNode {node_id: $node_id})
            SET c.name = $name,
                c.type = $type,
                c.file_path = $file_path,
                c.docstring = $docstring,
                c.code_snippet = $code_snippet,
                c.ai_summary = $ai_summary,
                c.embedding = $embedding
            """
            session.run(query_node,
                        node_id=node_id,
                        name=data['name'],
                        type=data.get('type', 'function'),
                        file_path=data['file_path'],
                        docstring=data.get('docstring', ''),
                        code_snippet=code_snippet,
                        ai_summary=summary,
                        embedding=embedding)

            query_epic = """
            MATCH (c:CodeNode {node_id: $node_id})
            MERGE (e:Ticket {id: $epic_key})
            MERGE (c)-[:BELONGS_TO]->(e)
            """
            session.run(query_epic, node_id=node_id, epic_key=epic_key)

            if code_snippet:
                chunks = chunk_code_with_sliding_window(
                    name=data['name'],
                    docstring=data.get('docstring', ''),
                    code_snippet=code_snippet
                )

                session.run("MATCH (c:CodeNode {node_id: $node_id})-[:HAS_CHUNK]->(ch:CodeChunk) DETACH DELETE ch",
                            node_id=node_id)

                for chunk_idx, chunk_text in enumerate(chunks):
                    chunk_id = f"{node_id}_chunk_{chunk_idx}"
                    
                    # 🌟 [FIX] ปรับลดเหลือ 2000 ตัวอักษร
                    safe_chunk_text = chunk_text[:2000]
                    chunk_embedding = get_text_embedding(safe_chunk_text)
                    
                    if not chunk_embedding:
                        logger.warning(f"⚠️ Embedding failed for chunk {chunk_id}, skipping...")
                        continue

                    query_chunk = """
                    MATCH (c:CodeNode {node_id: $node_id})
                    MERGE (ch:CodeChunk {chunk_id: $chunk_id})
                    SET ch.text = $text, 
                        ch.embedding = $embedding
                    MERGE (c)-[:HAS_CHUNK]->(ch)
                    """
                    session.run(query_chunk,
                                node_id=node_id,
                                chunk_id=chunk_id,
                                text=chunk_text,
                                embedding=chunk_embedding)

        logger.info("🔗 กำลังสร้างเส้นความสัมพันธ์ (Dependencies)...")
        for data in nodes_data:
            caller_id = f"{data['file_path']}::{data['name']}"
            calls = data.get("calls", [])
            for called_name in calls:
                query_calls = """
                MATCH (caller:CodeNode {node_id: $caller_id})
                MATCH (callee:CodeNode {name: $called_name})
                MERGE (caller)-[:CALLS]->(callee)
                """
                session.run(query_calls, caller_id=caller_id, called_name=called_name)

    driver.close()
    logger.info("🎉 Graph Ingestion Complete!")


# ========================= AI AUTO MAPPER FUNCTIONS =========================
def get_unmapped_code_nodes(session, epic_key: str, specific_file: str = None) -> list:
    """ดึง CodeNode ที่ยังไม่ได้ผูกกับตั๋วใบย่อยๆ"""
    
    base_query = """
    MATCH (c:CodeNode)-[:BELONGS_TO]->(e:Ticket {id: $epic_key})
    WHERE NOT (c)-[:IMPLEMENTS]->(:Ticket)
    AND c.embedding IS NOT NULL
    AND size(c.embedding) > 0
    """
    
    if specific_file:
        normalized_path = specific_file.replace("\\", "/")
        base_query += f"  AND c.file_path ENDS WITH '{os.path.basename(normalized_path)}'\n"
        
    base_query += " RETURN c.node_id AS node_id, c.name AS name, c.ai_summary AS summary, c.embedding AS embedding, c.file_path AS file_path"
    
    result = session.run(base_query, epic_key=epic_key)
    return [record.data() for record in result]


def find_candidate_tickets(session, embedding_vector, top_k=5):
    query = """
    CALL db.index.vector.queryNodes('chunk_embedding', $top_k, $embedding)
    YIELD node AS chunk, score
    MATCH (t:Ticket)-[:HAS_CHUNK]->(chunk)
    RETURN DISTINCT t.id AS ticket_id, t.summary AS summary, chunk.text AS details, score
    ORDER BY score DESC
    LIMIT $top_k
    """
    result = session.run(query, top_k=top_k, embedding=embedding_vector)
    return [record.data() for record in result]


def ask_llm_to_match(code_name, code_summary, candidates) -> list:
    if not candidates:
        return []

    candidates_text = ""
    for i, cand in enumerate(candidates):
        candidates_text += f"{i + 1}. TICKET: {cand['ticket_id']} | SUMMARY: {cand['summary']}\n"

    system_prompt = """
    You are an AI System Architect. Your job is to map a source code function to the correct Jira Tickets.
    Read the Code Summary and the list of Candidate Jira Tickets.
    Determine which ticket(s) this code was written for. It can match multiple tickets, one ticket, or none.

    CRITICAL RULE:
    You MUST output ONLY a valid JSON object in this exact format:
    {
      "matched_tickets": ["SCRUM-XX", "SCRUM-YY"],
      "reason": "Short explanation of why."
    }
    If no tickets match, return an empty list for matched_tickets.
    """

    user_prompt = f"""
    CODE FUNCTION: {code_name}
    CODE SUMMARY: {code_summary}

    CANDIDATE TICKETS:
    {candidates_text}
    """

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()}
    ]

    try:
        response = query_qwen(messages, temperature=0.1)
        raw_text = response.get('message', {}).get('content', '') if isinstance(response, dict) else str(response)

        if '<!DOCTYPE html>' in raw_text or 'Cloudflare' in raw_text or 'Bad gateway' in raw_text:
            logger.error(f"❌ LLM returned HTML error page instead of JSON for {code_name}")
            return []

        match = re.search(r'\{.*\}', raw_text.replace('\n', ' '), re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            return parsed.get("matched_tickets", [])
        return []
    except Exception as e:
        logger.error(f"❌ LLM Parsing Error for {code_name}: {e}")
        return []


def link_code_to_tickets(session, node_id, ticket_ids):
    if not ticket_ids:
        return
    query = """
    MATCH (c:CodeNode {node_id: $node_id})
    UNWIND $ticket_ids AS ticket_id
    MATCH (t:Ticket {id: ticket_id})
    MERGE (c)-[:IMPLEMENTS]->(t)
    """
    session.run(query, node_id=node_id, ticket_ids=ticket_ids)


def run_auto_mapper(epic_key: str = "SCRUM-32", target_file: str = None):
    logger.info(f"🚀 เริ่มต้น AI Auto-Mapper สำหรับ Epic {epic_key}...")
    if target_file:
        logger.info(f"🎯 โหมด: ทำงานเฉพาะไฟล์เป้าหมาย -> {target_file}")

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )

    try:
        with driver.session() as session:
            unmapped_nodes = get_unmapped_code_nodes(session, epic_key, specific_file=target_file)
            
            if not unmapped_nodes:
                logger.info("🎉 ไม่มี CodeNode ที่ต้องการจับคู่ (หรือจับคู่ครบหมดแล้ว)")
                return
                
            logger.info(f"🔍 พบ CodeNode ที่ยังไม่ได้จับคู่ {len(unmapped_nodes)} โหนด")
            success_count = 0

            for i, node in enumerate(unmapped_nodes):
                node_id = node['node_id']
                name = node['name']
                summary = node['summary']
                embedding = node['embedding']

                logger.info(f"\n🔄 [{i + 1}/{len(unmapped_nodes)}] กำลังวิเคราะห์โค้ด: {name}")

                candidates = find_candidate_tickets(session, embedding, top_k=4)
                if not candidates:
                    logger.warning(f"⚠️ ไม่พบตั๋วที่ใกล้เคียงสำหรับ {name}")
                    continue

                matched_tickets = ask_llm_to_match(name, summary, candidates)

                if matched_tickets:
                    logger.info(f"✅ AI จับคู่ {name} เข้ากับตั๋ว: {matched_tickets}")
                    link_code_to_tickets(session, node_id, matched_tickets)
                    success_count += 1
                else:
                    logger.info(f"🤷 AI มองว่า {name} ไม่ตรงกับตั๋วใบไหนเลยใน Candidate")

        logger.info(f"\n🎉 Auto-Mapping เสร็จสิ้น! จับคู่สำเร็จ {success_count}/{len(unmapped_nodes)} โหนด")
    except Exception as e:
        logger.error(f"❌ Error in Auto-Mapper: {e}")
    finally:
        driver.close()


# ========================= MAIN PIPELINE FUNCTIONS =========================

def run_code_file_sync(file_path: str, epic_key: str = "SCRUM-32") -> str:
    if not os.path.exists(file_path):
        err_msg = f"❌ File not found: {file_path}"
        logger.error(err_msg)
        return err_msg

    logger.info(f"🚀 เริ่มต้นการรัน Sync Pipeline สำหรับไฟล์: {file_path} (Epic: {epic_key})")

    try:
        logger.info("\n" + "=" * 40 + "\n🛠️ STEP 1: AST Extraction\n" + "=" * 40)
        raw_nodes = scan_codebase(file_path, epic_key)
        
        if not raw_nodes:
            msg = f"⏭️ No interesting functions/classes found in {file_path}. Skipped."
            logger.info(msg)
            return msg

        logger.info("\n" + "=" * 40 + "\n🧠 STEP 2: AI Summarization\n" + "=" * 40)
        processed_nodes = process_extracted_nodes(raw_nodes)

        logger.info("\n" + "=" * 40 + "\n🕸️ STEP 3: Graph Ingestion\n" + "=" * 40)
        ingest_code_to_graph(processed_nodes)

        logger.info("\n" + "=" * 40 + "\n🎯 STEP 4: Auto-Mapper\n" + "=" * 40)
        run_auto_mapper(epic_key, file_path)

        success_msg = f"✅ SYNC COMPLETED FOR: {file_path} (Epic: {epic_key})"
        logger.info(f"\n{success_msg}")
        return success_msg

    except Exception as e:
        err_msg = f"❌ Error during sync pipeline: {str(e)}"
        logger.error(err_msg)
        return err_msg


def run_recent_code_sync(repo_path: str, hours: int = 24, epic_key: str = "SCRUM-32") -> str:
    logger.info(f"🔍 Checking for modified CODE files in {repo_path} (Last {hours} hours)...")
    
    if not os.path.exists(repo_path):
        err_msg = f"❌ Repo path not found: {repo_path}"
        logger.error(err_msg)
        return err_msg

    try:
        cmd = ["git", "-C", repo_path, "log", f"--since={hours} hours ago", "--name-only", "--pretty=format:"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        valid_extensions = ('.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.cs', '.go')
        
        changed_files = list(set([
            f.strip() for f in result.stdout.split('\n') 
            if f.strip().endswith(valid_extensions)
        ]))

        if not changed_files:
            msg = f"😴 No code files were changed in the last {hours} hours. (Epic: {epic_key})"
            logger.info(msg)
            return msg

        success_count = 0
        logger.info(f"📝 Found {len(changed_files)} changed code files. Starting sync...")
        
        for file_name in changed_files:
            full_path = os.path.join(repo_path, file_name)
            if os.path.exists(full_path):
                logger.info(f"🚀 Triggering sync for: {full_path}")
                run_code_file_sync(full_path, epic_key)
                success_count += 1

        return f"✅ Successfully synced {success_count} recently modified CODE files (Epic: {epic_key})."

    except subprocess.CalledProcessError as e:
        err_msg = f"❌ Git command failed (Is it a valid Git repo?): {e.stderr}"
        logger.error(err_msg)
        return err_msg
    except Exception as e:
        err_msg = f"❌ Error checking recent code files: {str(e)}"
        logger.error(err_msg)
        return err_msg


def run_full_sync_pipeline(project_root: str, epic_key: str = "SCRUM-32"):
    logger.info(f"🚀 เริ่มต้นการรัน Sync Pipeline สำหรับ Epic: {epic_key}")

    logger.info("\n" + "=" * 50 + "\n🛠️ STEP 1: AST Code Extraction\n" + "=" * 50)
    raw_nodes = scan_codebase(project_root, epic_key)
    logger.info(f"♻️ สแกนพบ {len(raw_nodes)} โหนดใหม่")

    logger.info("\n" + "=" * 50 + "\n🧠 STEP 2: AI Code Summarization\n" + "=" * 50)
    processed_nodes = process_extracted_nodes(raw_nodes)

    logger.info("\n" + "=" * 50 + "\n🕸️ STEP 3: Neo4j Graph Ingestion\n" + "=" * 50)
    ingest_code_to_graph(processed_nodes)

    logger.info("\n" + "=" * 50 + "\n🎯 STEP 4: AI Auto-Mapper (Link to Jira Tickets)\n" + "=" * 50)
    run_auto_mapper(epic_key)

    logger.info("\n✅✅✅ SYNC PIPELINE COMPLETED SUCCESSFULLY! ✅✅✅")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("⚠️ Usage:")
        print("  1. Single File : python -m tools.sync_code_pipeline <file_path> [epic_key]")
        print("  2. Recent Files: python -m tools.sync_code_pipeline --recent <repo_path> <hours> [epic_key]")
        sys.exit(1)

    if sys.argv[1] == "--recent":
        if len(sys.argv) < 3:
            print("⚠️ Error: Missing arguments for --recent")
            print("Usage: python -m tools.sync_code_pipeline --recent <repo_path> <hours> [epic_key]")
            sys.exit(1)
            
        repo_path = sys.argv[2]
        hours_str = sys.argv[3] if len(sys.argv) > 3 else "24"
        hours = int(hours_str) if hours_str.strip() else 24
        epic_key = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4].strip() else "SCRUM-32"
        
        result = run_recent_code_sync(repo_path, hours, epic_key)
        print(result)
        
    else:
        target_file = sys.argv[1]
        epic_key = sys.argv[2] if len(sys.argv) > 2 else "SCRUM-32"
        
        result = run_code_file_sync(target_file, epic_key)
        print(result)
import os
import threading
from fastapi import FastAPI, BackgroundTasks, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import dotenv

# Load environment variables
dotenv.load_dotenv()

from backend.database import Database
from backend.crawler import GeopoliticalCrawler
from backend.extraction import EntityExtractor
from backend.search import SearchEngine
from backend.generator import GeopoliticalGenerator

app = FastAPI(title="Notion-Like Model UN Research Assistant")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize engines
db = Database()
search_engine = SearchEngine(db)
generator = GeopoliticalGenerator()
entity_extractor = EntityExtractor(db)

# Crawler status state
crawler_status = {
    "active": False,
    "pages_indexed": 0,
    "total_attempted": 0,
    "logs": []
}

DEFAULT_SEEDS = [
    "China border security",
    "South China Sea tensions",
    "Taiwan Strait escalation",
    "China hybrid warfare",
    "Indo-Pacific military strategy",
    "border sovereignty disputes",
    "cyber warfare Asia",
    "China maritime security",
    "semiconductor geopolitics",
    "territorial disputes Asia"
]

current_seeds = DEFAULT_SEEDS.copy()

# Pydantic Schemas
class SearchQuery(BaseModel):
    query: str
    top_k: Optional[int] = 10
    domain: Optional[str] = "geopolitics"

class SynthesisRequest(BaseModel):
    committee: str
    portfolio: str
    agenda: str
    mode: str  # "speech", "clash", "resolution", "masterclass"
    top_k: Optional[int] = 5

class NoteCreate(BaseModel):
    title: str
    content: str

class NoteUpdate(BaseModel):
    title: str
    content: str

class SettingsUpdate(BaseModel):
    gemini_key: Optional[str] = ""
    openai_key: Optional[str] = ""
    groq_key: Optional[str] = ""
    prefer_ollama: Optional[bool] = False
    ollama_model: Optional[str] = "qwen3.5:9b"

class ExportRequest(BaseModel):
    title: str
    country: str
    content: str

# --- Helper Callback for Crawler Logs ---
def add_crawler_log(msg: str):
    crawler_status["logs"].append(msg)
    # Keep last 200 logs
    if len(crawler_status["logs"]) > 200:
        crawler_status["logs"].pop(0)

# --- Background Crawl Process ---
def background_crawl_task(seeds: List[str], max_pages: int, max_depth: int):
    crawler_status["active"] = True
    crawler_status["logs"] = []
    add_crawler_log("Initializing crawl engine...")
    
    try:
        crawler = GeopoliticalCrawler(log_callback=add_crawler_log)
        
        # 1. Run Crawl
        # Pass lambda that returns database instance
        results = crawler.crawl_pipeline(
            seed_queries=seeds,
            db_conn_func=lambda: Database(),
            max_pages=max_pages,
            max_depth=max_depth
        )
        
        crawler_status["pages_indexed"] = results["pages_indexed"]
        crawler_status["total_attempted"] = results["total_attempted"]
        
        # 2. Extract Entities
        add_crawler_log("Crawl finished. Starting automated entity extraction...")
        extractor = EntityExtractor(Database())
        extractor.process_all_sources()
        add_crawler_log("Entity extraction complete. Knowledge graph updated.")
        
        # 3. Build/Embed Chunks
        add_crawler_log("Batch embedding new text chunks using SentenceTransformer...")
        embedded_count = search_engine.embed_pending_chunks()
        add_crawler_log(f"Vector search indexing complete. Embedded {embedded_count} chunks.")
        
    except Exception as e:
        add_crawler_log(f"Crawl process encountered an error: {e}")
    finally:
        crawler_status["active"] = False
        add_crawler_log("Crawl job finished.")

# --- API Endpoints ---

@app.get("/api/status")
def get_status():
    """Returns database size, crawled page counts, and API key presence."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sources")
        num_sources = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM chunks")
        num_chunks = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM entities")
        num_entities = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM entity_relations")
        num_relations = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM notes")
        num_notes = cursor.fetchone()[0]

    return {
        "sources_count": num_sources,
        "chunks_count": num_chunks,
        "entities_count": num_entities,
        "relations_count": num_relations,
        "notes_count": num_notes,
        "gemini_api_configured": bool(generator.gemini_key),
        "groq_api_configured": bool(generator.groq_key),
        "openai_api_configured": bool(generator.openai_key),
        "prefer_ollama": generator.prefer_ollama,
        "ollama_model": generator.ollama_model,
        "device_used": search_engine.device,
        "crawler_running": crawler_status["active"]
    }

@app.post("/api/settings")
def update_settings(payload: SettingsUpdate):
    """Updates API keys dynamically in memory."""
    if payload.gemini_key is not None:
        os.environ["GEMINI_API_KEY"] = payload.gemini_key
        generator.gemini_key = payload.gemini_key
    if payload.openai_key is not None:
        os.environ["OPENAI_API_KEY"] = payload.openai_key
        generator.openai_key = payload.openai_key
    if payload.groq_key is not None:
        os.environ["GROQ_API_KEY"] = payload.groq_key
        generator.groq_key = payload.groq_key
        
    # Update Ollama settings
    if payload.prefer_ollama is not None:
        generator.prefer_ollama = bool(payload.prefer_ollama)
        os.environ["PREFER_OLLAMA"] = "true" if generator.prefer_ollama else "false"
    if payload.ollama_model:
        generator.ollama_model = payload.ollama_model
        os.environ["OLLAMA_MODEL"] = payload.ollama_model
        
    return {"status": "success", "message": "API and model configurations updated."}

@app.get("/api/crawler/seeds")
def get_seeds():
    return {"seeds": current_seeds}

@app.post("/api/crawler/seeds")
def set_seeds(seeds: List[str]):
    global current_seeds
    current_seeds = seeds
    return {"seeds": current_seeds}

@app.post("/api/crawler/start")
def start_crawler(background_tasks: BackgroundTasks, max_pages: int = Body(20), max_depth: int = Body(1)):
    """Starts the crawler pipeline in the background."""
    if crawler_status["active"]:
        raise HTTPException(status_code=400, detail="A crawl job is already in progress.")
    
    background_tasks.add_task(
        background_crawl_task, 
        seeds=current_seeds, 
        max_pages=max_pages, 
        max_depth=max_depth
    )
    return {"status": "started", "message": "Crawl job has been scheduled."}

@app.get("/api/crawler/status")
def get_crawler_status():
    return crawler_status

@app.post("/api/search")
def search(payload: SearchQuery):
    """Performs semantic search and trust-rerank over the crawled document database."""
    results = search_engine.execute_search(payload.query, top_k=payload.top_k, domain=payload.domain)
    return {"results": results}

@app.post("/api/debate/synthesis")
def synthesize(payload: SynthesisRequest):
    """Retrieves context chunks and synthesizes an argument speech, clash sheet, or resolution clauses."""
    mode = payload.mode.lower()
    
    # 1. Classify domain dynamically
    combined_text = f"{payload.committee} {payload.agenda}".lower()
    domain = "geopolitics"
    if any(k in combined_text for k in ["quantum", "ai", "intelligence", "neural", "learning", "gene", "crispr", "editing", "genetics", "energy", "fusion", "science", "physics"]):
        domain = "science"
    elif any(k in combined_text for k in ["rome", "roman", "caesar", "history", "historical", "battle", "revolution", "monarch", "empire"]):
        domain = "history"
    elif any(k in combined_text for k in ["market", "finance", "investment", "company", "corporation", "startup", "business", "economics", "equity"]):
        domain = "business"
    elif any(k in combined_text for k in ["court", "legal", "judge", "policy", "regulation", "law", "statute", "constitution"]):
        domain = "law"
        
    # Map fields
    query = payload.agenda
    country = payload.portfolio
    title = f"{payload.committee}: {payload.agenda}"
    
    # 2. Check for relevant chunks count (similarity > 0.3)
    # If < 50 relevant chunks, trigger a targeted discovery crawl automatically
    test_chunks = search_engine.execute_search(query, top_k=100, domain=domain)
    relevant_chunks = [c for c in test_chunks if c.get("similarity", 0.0) >= 0.3]
    
    if len(relevant_chunks) < 50:
        print(f"[Auto-Crawl] Only found {len(relevant_chunks)} relevant chunks. Triggering automated discovery crawl...")
        crawler = GeopoliticalCrawler(log_callback=print)
        auto_seeds = crawler.generate_seeds_for_topic(payload.committee, payload.agenda)
        print(f"[Auto-Crawl] Generated seeds: {auto_seeds}")
        try:
            # Synchronous crawl (max 5 pages for speed)
            crawler.crawl_pipeline(
                seed_queries=auto_seeds,
                db_conn_func=lambda: Database(),
                max_pages=5,
                max_depth=1
            )
            # Update extraction & embed
            extractor = EntityExtractor(Database())
            extractor.process_all_sources()
            search_engine.embed_pending_chunks()
            print("[Auto-Crawl] Crawl complete. Database updated.")
        except Exception as crawl_err:
            print(f"[Auto-Crawl] Error during crawl: {crawl_err}")


    # Now retrieve the updated context
    if mode == "masterclass":
        # Run targeted searches for each masterclass module (top_k_per_module=8)
        structured_chunks = search_engine.decomposed_search(query, country, top_k_per_module=8, domain=domain)
        chunks = []
        seen_ids = set()
        for module_list in structured_chunks.values():
            for c in module_list:
                if c["chunk_id"] not in seen_ids:
                    seen_ids.add(c["chunk_id"])
                    chunks.append(c)
    else:
        chunks = search_engine.execute_search(query, top_k=payload.top_k, domain=domain)
        
    if not chunks:
        # Fallback empty context message
        return {
            "synthesis": "No research content found in the database. Please run the Crawler first on seed queries.",
            "sources": []
        }

        
    # 3. Select appropriate synthesis template
    if mode == "speech":
        synthesis = generator.draft_speech(title, chunks, country=country)
    elif mode == "clash":
        synthesis = generator.draft_counterargument(title, chunks, country=country)
    elif mode == "resolution":
        synthesis = generator.draft_resolution_clauses(title, chunks, country=country)
    elif mode == "masterclass":
        synthesis = generator.draft_masterclass(title, structured_chunks, country=country)
    else:
        raise HTTPException(status_code=400, detail="Invalid synthesis mode. Must be 'speech', 'clash', 'resolution', or 'masterclass'.")

    # 3. Compile sources for reference
    referenced_sources = []
    seen_source_ids = set()
    for c in chunks:
        sid = c["source_id"]
        if sid not in seen_source_ids:
            seen_source_ids.add(sid)
            referenced_sources.append({
                "source_id": sid,
                "title": c["title"],
                "url": c["url"],
                "trust_score": c["trust_score"],
                "category": c["category"]
            })
            
    return {
        "synthesis": synthesis,
        "sources": referenced_sources,
        "chunks": chunks
    }

@app.post("/api/debate/export")
def export_dossier(payload: ExportRequest):
    """Generates a PDF and LaTeX document from the synthesized research content."""
    try:
        from backend.exporter import export_to_pdf, export_to_latex
        pdf_url = export_to_pdf(payload.title, payload.country, payload.content)
        latex_url = export_to_latex(payload.title, payload.country, payload.content)
        return {
            "status": "success",
            "pdf_url": pdf_url,
            "latex_url": latex_url
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Export generation failed: {ex}")

@app.get("/api/export/full-dossier")
def export_full_dossier_endpoint():
    """Exports the entire database as a comprehensive dossier with direct source URLs."""
    try:
        from backend.exporter import export_full_dossier
        result = export_full_dossier(db.db_path)
        return result
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Full dossier export failed: {ex}")

@app.get("/api/graph")
def get_graph():
    """Generates a node-link graph data structure for rendering the knowledge graph."""
    relations = db.get_relations_graph()
    
    # Fetch all entity type classifications from the database
    entity_types = {}
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, type FROM entities")
            for row in cursor.fetchall():
                entity_types[row["name"]] = row["type"]
    except Exception as e:
        print(f"Error querying entity types from database: {e}")
        
    # Track unique nodes and their attributes
    node_set = {}
    links = []
    
    for r in relations:
        e1, e2 = r["entity_1"], r["entity_2"]
        
        # Populate nodes
        for node in [e1, e2]:
            if node not in node_set:
                node_type = entity_types.get(node, "Unknown")
                node_set[node] = {
                    "id": node,
                    "label": node,
                    "type": node_type,
                    "weight": 1
                }
            else:
                node_set[node]["weight"] += 1
                
        links.append({
            "source": e1,
            "target": e2,
            "description": r["description"],
            "source_title": r["source_title"],
            "source_url": r["source_url"],
            "trust_score": r["trust_score"]
        })
        
    return {
        "nodes": list(node_set.values()),
        "links": links
    }

# --- Notes CRUD Endpoints ---

@app.get("/api/notes")
def list_notes():
    return {"notes": db.list_notes()}

@app.post("/api/notes")
def create_note(payload: NoteCreate):
    note_id = db.create_note(payload.title, payload.content)
    return {"id": note_id, "status": "created"}

@app.get("/api/notes/{note_id}")
def get_note(note_id: int):
    note = db.get_note(note_id)
    if not note:
        raise HTTPException(status_code=444, detail="Note not found")
    return note

@app.put("/api/notes/{note_id}")
def update_note(note_id: int, payload: NoteUpdate):
    db.update_note(note_id, payload.title, payload.content)
    return {"status": "updated"}

@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    db.delete_note(note_id)
    return {"status": "deleted"}

# --- Sources Endpoints ---

@app.get("/api/sources")
def list_sources():
    return {"sources": db.list_sources()}

@app.get("/api/sources/{source_id}")
def get_source_detail(source_id: int):
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
        
    # Fetch its chunks
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, text, chunk_index FROM chunks WHERE source_id = ? ORDER BY chunk_index", (source_id,))
        chunks = [dict(row) for row in cursor.fetchall()]
        
    return {
        "source": source,
        "chunks": chunks
    }

@app.get("/api/debug/exports")
def debug_exports():
    from backend.exporter import EXPORTS_DIR
    import os
    return {
        "EXPORTS_DIR": EXPORTS_DIR,
        "absolute_EXPORTS_DIR": os.path.abspath(EXPORTS_DIR),
        "exists": os.path.exists(EXPORTS_DIR),
        "files": os.listdir(EXPORTS_DIR) if os.path.exists(EXPORTS_DIR) else []
    }

# Serving the static frontend SPA files
# Ensure the frontend folder exists, otherwise we wait to mount it
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="static")

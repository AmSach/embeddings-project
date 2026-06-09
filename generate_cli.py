#!/usr/bin/env python
"""
Pure Python CLI Tool for Model UN Research Assistant.
Directly executes crawls, semantic search, local Qwen 3.5 synthesis via Ollama, and exports PDF/LaTeX.
"""
import os
import sys
import argparse
import re
from datetime import datetime

# Fix Windows console encoding to handle special characters cleanly
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Ensure working directory is workspace root
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Import local backend modules directly
try:
    from backend.database import Database
    from backend.crawler import GeopoliticalCrawler
    from backend.extraction import EntityExtractor
    from backend.search import SearchEngine
    from backend.generator import GeopoliticalGenerator
    from backend.exporter import export_to_pdf, export_to_latex, EXPORTS_DIR
except ImportError as err:
    print(f"[Error] Failed to import backend components: {err}")
    print("Please verify you are running this from the workspace root and your venv is active.")
    sys.exit(1)

def run_cli():
    parser = argparse.ArgumentParser(description="Model UN Research Assistant CLI tool")
    parser.add_argument("--committee", type=str, default="UN Committee on Border Security (UNCBS)",
                        help="The committee name")
    parser.add_argument("--portfolio", type=str, default="China",
                        help="Represented country / portfolio")
    parser.add_argument("--agenda", type=str, default="Sovereignty disputes and border fortification strategies in contested territorial zones",
                        help="The debate agenda topic")
    parser.add_argument("--mode", type=str, choices=["speech", "clash", "resolution", "masterclass"], default="masterclass",
                        help="Synthesis mode (speech, clash, resolution, masterclass)")
    parser.add_argument("--model", type=str, default="qwen3.5:9b",
                        help="Ollama model to use")
    parser.add_argument("--top-k", type=int, default=6,
                        help="Number of retrieved context chunks")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="Skip crawling even if relevant chunks count in database is low")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("          MODEL UN SEMANTIC RESEARCH CLI ASSISTANT")
    print("=" * 60)
    print(f"  Committee: {args.committee}")
    print(f"  Portfolio: {args.portfolio}")
    print(f"  Agenda:    {args.agenda}")
    print(f"  Mode:      {args.mode.upper()}")
    print(f"  LLM Model: Ollama ({args.model})")
    print("=" * 60)
    
    # 1. Initialize Engines
    print("\n[1/4] Initializing database and semantic search...")
    db = Database()
    search_engine = SearchEngine(db)
    generator = GeopoliticalGenerator()
    
    # Set Ollama preference
    generator.prefer_ollama = True
    generator.ollama_model = args.model
    
    # 2. Domain classification
    combined_text = f"{args.committee} {args.agenda}".lower()
    domain = "geopolitics"
    if any(k in combined_text for k in ["quantum", "ai", "intelligence", "neural", "learning", "gene", "crispr", "editing", "genetics", "energy", "fusion", "science", "physics"]):
        domain = "science"
    elif any(k in combined_text for k in ["rome", "roman", "caesar", "history", "historical", "battle", "revolution", "monarch", "empire"]):
        domain = "history"
    elif any(k in combined_text for k in ["market", "finance", "investment", "company", "corporation", "startup", "business", "economics", "equity"]):
        domain = "business"
    elif any(k in combined_text for k in ["court", "legal", "judge", "policy", "regulation", "law", "statute", "constitution"]):
        domain = "law"
        
    print(f"  Domain classified as: {domain.upper()}")
    
    # 3. Check for relevant chunks count
    test_chunks = search_engine.execute_search(args.agenda, top_k=100, domain=domain)
    relevant_chunks = [c for c in test_chunks if c.get("similarity", 0.0) >= 0.3]
    print(f"  Found {len(relevant_chunks)} relevant chunks in database (similarity >= 0.3).")
    
    if len(relevant_chunks) < 50 and not args.skip_crawl:
        print("\n  [Auto-Crawl] Triggers auto-crawl because <50 relevant chunks found.")
        crawler = GeopoliticalCrawler(log_callback=print)
        auto_seeds = crawler.generate_seeds_for_topic(args.committee, args.agenda)
        # Use top 2 seeds to accelerate the discovery search phase for CLI execution
        optimized_seeds = auto_seeds[:2]
        print(f"  Generated seeds: {auto_seeds} (Using optimized subset: {optimized_seeds})")
        try:
            crawler.crawl_pipeline(
                seed_queries=optimized_seeds,
                db_conn_func=lambda: Database(),
                max_pages=5,
                max_depth=1
            )
            # Update extraction & embed
            print("  Running entity extraction on new sources...")
            extractor = EntityExtractor(Database())
            extractor.process_all_sources()
            
            print("  Embedding new chunks using SentenceTransformer on GPU/CUDA...")
            search_engine.embed_pending_chunks()
            print("  [Auto-Crawl] Database successfully updated.")
        except Exception as crawl_err:
            print(f"  [ERROR] Crawl process failed: {crawl_err}")
            
    # Retrieve updated context
    print("\n[2/4] Retrieving grounded research context chunks...")
    title = f"{args.committee}: {args.agenda}"
    
    if args.mode == "masterclass":
        structured_chunks = search_engine.decomposed_search(args.agenda, args.portfolio, top_k_per_module=8, domain=domain)
        chunks = []
        seen_ids = set()
        for module_list in structured_chunks.values():
            for c in module_list:
                if c["chunk_id"] not in seen_ids:
                    seen_ids.add(c["chunk_id"])
                    chunks.append(c)
    else:
        chunks = search_engine.execute_search(args.agenda, top_k=args.top_k, domain=domain)
        structured_chunks = None
        
    if not chunks:
        print("  [Error] No grounded research content found in database. Exiting.")
        sys.exit(1)
        
    print(f"  Retrieved {len(chunks)} context chunks from {len(set(c['source_id'] for c in chunks))} sources.")

    # 4. Synthesis
    print(f"\n[3/4] Synthesizing research guide using local {args.model} via Ollama...")
    print("  This may take a moment as it runs RAG-grounded generations...")
    
    if args.mode == "speech":
        synthesis = generator.draft_speech(title, chunks, country=args.portfolio)
    elif args.mode == "clash":
        synthesis = generator.draft_counterargument(title, chunks, country=args.portfolio)
    elif args.mode == "resolution":
        synthesis = generator.draft_resolution_clauses(title, chunks, country=args.portfolio)
    elif args.mode == "masterclass":
        synthesis = generator.draft_masterclass(title, structured_chunks, country=args.portfolio)
        
    print(f"  [OK] Synthesis complete! Generated length: {len(synthesis)} characters (~{len(synthesis.split())} words).")
    
    # 5. Export
    print("\n[4/4] Exporting to PDF, LaTeX, and Markdown...")
    try:
        print(f"  EXPORTS_DIR is resolved to: {os.path.abspath(EXPORTS_DIR)}")
        print(f"  EXPORTS_DIR exists: {os.path.exists(EXPORTS_DIR)}")
        
        pdf_url = export_to_pdf(title, args.portfolio, synthesis)
        latex_url = export_to_latex(title, args.portfolio, synthesis)
        
        pdf_file = os.path.join(EXPORTS_DIR, pdf_url.split("/")[-1])
        latex_file = os.path.join(EXPORTS_DIR, latex_url.split("/")[-1])
        
        # Save markdown
        md_file = os.path.join(EXPORTS_DIR, "china_uncbs_masterclass.md" if args.portfolio.lower() == "china" else f"study_guide_{args.portfolio.lower()}.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(synthesis)
            
        print(f"  [OK] PDF:      {pdf_file} (exists: {os.path.exists(pdf_file)})")
        print(f"  [OK] LaTeX:    {latex_file} (exists: {os.path.exists(latex_file)})")
        print(f"  [OK] Markdown: {md_file} (exists: {os.path.exists(md_file)})")
        print(f"  Files in EXPORTS_DIR after writing: {os.listdir(EXPORTS_DIR)}")
        
        # Attempt to open PDF
        try:
            print("  Opening PDF...")
            os.startfile(pdf_file)
        except Exception:
            pass
            
    except Exception as export_err:
        print(f"  [ERROR] Export generation failed: {export_err}")
        sys.exit(1)
        
    print("\n" + "=" * 60)
    print("  PREVIEW (first 1000 chars)")
    print("=" * 60)
    print(synthesis[:1000])
    print("\n... (truncated)")
    print("=" * 60)
    print("  FINISHED!")
    print("=" * 60)

if __name__ == "__main__":
    run_cli()

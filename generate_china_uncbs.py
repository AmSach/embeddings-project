"""Generate masterclass for China + UNCBS using existing DB data"""
import requests, json, os, sys

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8001"

print("=" * 60)
print("  CHINA + UNCBS MASTERCLASS GENERATION")
print("=" * 60)

# Check status
print("\n[1/3] Checking database status...")
r = requests.get(f"{BASE}/api/status")
status = r.json()
print(f"  Sources: {status['sources_count']}")
print(f"  Chunks: {status['chunks_count']}")
print(f"  Entities: {status['entities_count']}")
print(f"  Gemini API: {status['gemini_api_configured']}")
print(f"  OpenAI API: {status['openai_api_configured']}")
print(f"  Device: {status['device_used']}")

if status['sources_count'] == 0:
    print("\n  [!] No sources in DB. Cannot generate without data.")
    sys.exit(1)

# Configure settings to prefer local Qwen 3.5 via Ollama
print("\nConfiguring settings to use local Qwen 3.5 via Ollama...")
settings_payload = {
    "prefer_ollama": True,
    "ollama_model": "qwen3.5:9b"
}
try:
    r_settings = requests.post(f"{BASE}/api/settings", json=settings_payload)
    print(f"  Settings status: {r_settings.json()['status']}")
except Exception as e:
    print(f"  [ERROR] Failed to configure settings: {e}")
    sys.exit(1)

# Generate masterclass
print("\n[2/3] Generating Masterclass Dossier: China + UNCBS...")
print("  (Using existing crawled data + LLM synthesis)")
print("  This may take a few minutes depending on the LLM backend...")
payload = {
    "committee": "UN Committee on Border Security (UNCBS)",
    "portfolio": "China",
    "agenda": "Sovereignty disputes and border fortification strategies in contested territorial zones",
    "mode": "masterclass",
    "top_k": 6
}
try:
    r = requests.post(f"{BASE}/api/debate/synthesis", json=payload, timeout=600)
    data = r.json()
except Exception as e:
    print(f"  [ERROR] Generation failed: {e}")
    sys.exit(1)

synthesis = data.get("synthesis", "")
sources = data.get("sources", [])

print(f"\n  [OK] Masterclass generated! Length: {len(synthesis)} chars (~{len(synthesis.split())} words)")
print(f"  Sources used: {len(sources)}")
for s in sources:
    print(f"    - [{s.get('trust_score', 0):.2f}] {s.get('title', 'N/A')[:60]}")
    print(f"      URL: {s.get('url', 'N/A')}")

# Export to PDF
print("\n[3/3] Exporting PDF + LaTeX...")
export_payload = {
    "title": "UNCBS Study Dossier - China Border Security Strategy",
    "country": "China",
    "content": synthesis
}
r = requests.post(f"{BASE}/api/debate/export", json=export_payload)
export_data = r.json()

exports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "exports")

if export_data.get("status") == "success":
    pdf_file = os.path.join(exports_dir, export_data["pdf_url"].split("/")[-1])
    latex_file = os.path.join(exports_dir, export_data["latex_url"].split("/")[-1])
    print(f"\n  [OK] PDF:   {pdf_file}")
    print(f"  [OK] LaTeX: {latex_file}")
    
    # Save markdown too
    md_file = os.path.join(exports_dir, "china_uncbs_masterclass.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(synthesis)
    print(f"  [OK] Markdown: {md_file}")
    
    # Open PDF
    print("\n  Opening PDF...")
    os.startfile(pdf_file)
else:
    print(f"  [FAIL] Export failed: {export_data}")

# Also save raw synthesis to console for verification
print("\n" + "=" * 60)
print("  PREVIEW (first 2000 chars)")
print("=" * 60)
print(synthesis[:2000])
print("\n... (truncated)")
print("\n" + "=" * 60)
print("  DONE!")
print("=" * 60)

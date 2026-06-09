import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Tuple
from backend.database import Database
import re

# Domain-Specific Query Expansion Dictionary
DOMAIN_QUERY_EXPANSIONS = {
    "geopolitics": {
        r"\bchina\b|\bprc\b|\bbeijing\b": [
            "Beijing geopolitical strategy", "PLA military posture", "People's Republic of China official statements"
        ],
        r"\btaiwan\b|\broc\b|\btaipei\b": [
            "Taiwan Strait escalation risk", "US strategic ambiguity Taiwan", "semiconductor supply chain TSMC"
        ],
        r"\bcyber\b|\bhacking\b|\bdigital\b": [
            "cyber retaliation critical infrastructure", "state-sponsored cyber espionage", "hybrid warfare guidelines"
        ],
        r"\bmaritime\b|\bsea\b|\bnavy\b|\bcoast guard\b": [
            "UNCLOS sovereignty claims", "freedom of navigation operations FONOPs", "exclusive economic zone disputes"
        ],
        r"\bsemiconductor\b|\bchip\b|\btsmc\b|\basml\b": [
            "advanced lithography export controls", "silicon shield geopolitics", "global microchip supply chain security"
        ],
        r"\bsovereignty\b|\bborder\b|\bterritorial\b": [
            "border demarcation treaties", "bilateral territorial negotiations", "sovereign maritime boundaries"
        ],
        r"\bcounterargument\b|\bjustify\b|\bretaliation\b": [
            "diplomatic pretext crisis response", "reciprocal retaliatory actions international law", "strategic self-defense justification"
        ]
    },
    "science": {
        r"\bquantum\b|\bentanglement\b|\bcomputing\b": [
            "quantum computing entanglement principles", "quantum information theory algorithms", "superconducting qubits hardware engineering"
        ],
        r"\bai\b|\bintelligence\b|\bneural\b|\blearning\b": [
            "deep learning architecture optimization", "large language model scaling laws", "transformer neural network mechanisms"
        ],
        r"\bgene\b|\bcrispr\b|\bediting\b|\bgenetics\b": [
            "CRISPR Cas9 genetic editing precision", "therapeutic genomic sequence correction", "off-target mutations genome sequencing"
        ],
        r"\benergy\b|\bfusion\b|\bnuclear\b": [
            "tokamak magnetic confinement fusion physics", "burning plasma ignition conditions", "clean nuclear energy generation efficiency"
        ]
    },
    "history": {
        r"\brome\b|\broman\b|\bcaesar\b": [
            "Roman Republic constitutional crises", "Julius Caesar Civil War strategy", "Senatus Consultum Ultimum legal parameters"
        ],
        r"\bwar\b|\bbattle\b|\bmilitary\b": [
            "strategic campaign logistical operations", "tactical military command maneuvers", "geopolitical treaties peace agreements"
        ],
        r"\brevolution\b|\buprising\b|\brebel\b": [
            "socio-political revolution root causes", "institutional overthrow ideological frameworks", "civil uprising economic triggers"
        ]
    },
    "business": {
        r"\bmarket\b|\bfinance\b|\binvestment\b": [
            "macroeconomic market sector analysis", "venture capital equity financing trends", "corporate financial asset valuation models"
        ],
        r"\bcompany\b|\bcorporation\b|\bstartup\b": [
            "competitive industry market positioning", "corporate SWOT analysis operational model", "growth strategy product-market fit"
        ],
        r"\btech\b|\bindustry\b|\bsector\b": [
            "industry disruption emerging technologies", "global supply chain logistics optimization", "market share monopoly regulation antitrust"
        ]
    },
    "law": {
        r"\bcourt\b|\blegal\b|\bjudge\b": [
            "judicial constitutional interpretation precedent", "appellate litigation oral argument strategies", "legal doctrine statutory construction standards"
        ],
        r"\bpolicy\b|\bgovernment\b|\bregulation\b": [
            "public policy legislative drafting guidelines", "regulatory compliance oversight frameworks", "administrative law rule-making procedures"
        ]
    }
}

class SearchEngine:
    def __init__(self, db: Database, model_name: str = "all-MiniLM-L6-v2"):
        self.db = db
        # Auto-detect CUDA GPU for sentence-transformers
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Initializing SentenceTransformer on device: {self.device}")
        self.model = SentenceTransformer(model_name, device=self.device)
        self.embedding_dim = 384 # Dimension of all-MiniLM-L6-v2

    def embed_pending_chunks(self, batch_size: int = 64) -> int:
        """Finds chunks with zero/dummy embeddings, generates embeddings, and saves them."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # Find chunks that have 0 or dummy embeddings (all zero bytes)
            # Or chunks where the embedding is missing from the table
            cursor.execute("""
                SELECT c.id, c.text 
                FROM chunks c
                LEFT JOIN embeddings e ON c.id = e.chunk_id
                WHERE e.vector IS NULL OR length(e.vector) < 100
            """)
            rows = cursor.fetchall()
            
            if not rows:
                return 0

            chunk_ids = [r["id"] for r in rows]
            texts = [r["text"] for r in rows]
            
            print(f"Found {len(texts)} pending chunks to embed...")
            
            # Embed in batches
            embeddings = []
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i+batch_size]
                # Encode text
                batch_embs = self.model.encode(batch_texts, show_progress_bar=False, convert_to_numpy=True)
                embeddings.extend(batch_embs)
            
            # Update database
            for cid, emb in zip(chunk_ids, embeddings):
                vector_bytes = emb.astype(np.float32).tobytes()
                cursor.execute("""
                    INSERT OR REPLACE INTO embeddings (chunk_id, vector)
                    VALUES (?, ?)
                """, (cid, vector_bytes))
            
            conn.commit()
            
        # Invalidate cache to force reload
        self.db.invalidate_vector_cache()
        return len(chunk_ids)

    def expand_query(self, query: str, domain: str = "geopolitics") -> List[str]:
        """Expands the user query with domain-specific strategic contexts."""
        expanded_queries = [query]
        query_lower = query.lower()

        # Load expansions for this domain (fallback to geopolitics)
        domain_key = domain.lower() if domain else "geopolitics"
        expansions_dict = DOMAIN_QUERY_EXPANSIONS.get(domain_key, DOMAIN_QUERY_EXPANSIONS["geopolitics"])

        # Add matching expansion strings
        for pattern, expansions in expansions_dict.items():
            if re.search(pattern, query_lower):
                expanded_queries.extend(expansions)
                
        # Return unique queries (up to 4)
        seen = set()
        return [q for q in expanded_queries if not (q in seen or seen.add(q))][:4]

    def execute_search(self, query: str, top_k: int = 15, trust_alpha: float = 0.3, domain: str = "geopolitics") -> List[Dict[str, Any]]:
        """
        Executes expanded query semantic search and applies trust score reranking.
        Formula: final_score = similarity_score * (1.0 + trust_alpha * (trust_score - 0.5))
        """
        # Ensure all pending chunks are embedded first!
        self.embed_pending_chunks()
        
        # 1. Expand query to multiple search targets
        expanded_targets = self.expand_query(query, domain)
        print(f"Searching for expanded queries in domain '{domain}': {expanded_targets}")

        # 2. Get embeddings of expanded queries
        query_embs = self.model.encode(expanded_targets, convert_to_numpy=True)
        
        # 3. Perform semantic search for each expanded query and pool results
        pooled_results = {}
        
        for q_emb in query_embs:
            # db.semantic_search returns results from cache
            search_results = self.db.semantic_search(q_emb, top_k=top_k * 2)
            
            for res in search_results:
                chunk_id = res["chunk_id"]
                similarity = res["similarity"]
                trust_score = res["trust_score"]
                
                # Apply trust reranking formula
                # trust_score ranges from 0.3 (blog) to 1.0 (gov). (trust_score - 0.5) ranges from -0.2 to +0.5.
                # If trust_alpha = 0.3:
                # - Gov (1.0) multiplies similarity by (1.0 + 0.15) = 1.15
                # - Blog (0.3) multiplies similarity by (1.0 - 0.06) = 0.94
                reranked_score = similarity * (1.0 + trust_alpha * (trust_score - 0.5))
                
                if chunk_id not in pooled_results or reranked_score > pooled_results[chunk_id]["reranked_score"]:
                    res["reranked_score"] = reranked_score
                    pooled_results[chunk_id] = res

        # Sort pool by reranked score
        final_results = list(pooled_results.values())
        final_results.sort(key=lambda x: x["reranked_score"], reverse=True)
        
        return final_results[:top_k]

    def decomposed_search(self, query: str, country: str, top_k_per_module: int = 8, domain: str = "geopolitics") -> Dict[str, List[Dict[str, Any]]]:
        """
        Performs 8 targeted semantic searches for each masterclass module to do the RAG heavy lifting.
        Splits retrieval into specialized buckets, ensuring the LLM receives pre-structured fact packets.
        """
        domain_lower = domain.lower() if domain else "geopolitics"
        
        # Customize sub-queries based on research domain to optimize vector grounding
        if domain_lower == "science":
            sub_queries = {
                "Foundations": f"{query} scientific context historical origins discovery theories background baseline",
                "Timeline": f"{query} research milestones breakthroughs timeline chronological development history",
                "Stakeholders": f"{country} researchers institutes institutions laboratories organizations industry applications",
                "Frameworks": f"{query} equations laws principles mechanisms academic literature citations standards",
                "Precedents": f"{query} historical experiments research peer reviewed studies replication success cases",
                "Crisis": f"{query} technology limitations research challenges methodology experimental designs issues",
                "Rhetoric": f"{query} scientific debate hypothesis clashes counter-arguments critiques objections",
                "Resolutions": f"{query} future research directions proposals methodology experimental blueprint future research"
            }
        elif domain_lower == "history":
            sub_queries = {
                "Foundations": f"{query} historical context chronology timeline origins primary facts background",
                "Timeline": f"{query} detailed timeline history chronological key events battles dates",
                "Stakeholders": f"{country} key historical figures factions empires alliances monarchs social classes",
                "Frameworks": f"{query} governing structures treaties laws constitutions documents custom rules",
                "Precedents": f"{query} historical precedents past diplomatic crises military campaigns treaty applications",
                "Crisis": f"{query} political crisis actions battles rebellions diplomatic correspondences strategies",
                "Rhetoric": f"{query} historiographical debate historiography main schools of thought arguments critiques",
                "Resolutions": f"{query} historical analysis source criticism documentation lessons legacy future studies"
            }
        elif domain_lower == "business":
            sub_queries = {
                "Foundations": f"{query} market context history industry growth baseline data status quo analysis",
                "Timeline": f"{query} industry development milestones market trends timeline business history",
                "Stakeholders": f"{country} competitors companies partners customers segments stakeholders structures",
                "Frameworks": f"{query} industry standards financial metrics business regulations market rules guidelines",
                "Precedents": f"{query} past business precedents market case studies corporate mergers bankruptcies successes",
                "Crisis": f"{query} strategic challenges operations marketing execution swot analysis risks",
                "Rhetoric": f"{query} competitive advantages swot arguments counter-strategies negotiations business debate",
                "Resolutions": f"{query} strategic proposal business plan roadmap actionable directives blueprint"
            }
        elif domain_lower == "law":
            sub_queries = {
                "Foundations": f"{query} legal background legislative history case facts baseline status summary",
                "Timeline": f"{query} litigation timeline case history procedural development dates briefs",
                "Stakeholders": f"{country} litigants claimants defendants courts government bodies clients jurists",
                "Frameworks": f"{query} statutes precedents constitutional provisions legal codes regulations rulings",
                "Precedents": f"{query} legal precedents judicial rulings case laws past court decisions holdings",
                "Crisis": f"{query} case briefing litigation actions defense strategy claims arguments liability",
                "Rhetoric": f"{query} appellate debate oral arguments legal reasoning clash points doctrine statutory",
                "Resolutions": f"{query} legal opinion holding legislative draft policy recommendations blueprint briefs"
            }
        else: # geopolitics / MUN fallback
            sub_queries = {
                "Foundations": f"{query} historical origins status quo key events background facts",
                "Timeline": f"{query} chronological timeline of dispute border incidents military actions key dates",
                "Stakeholders": f"{query} {country} adversaries allies interests key stakeholders positions",
                "Frameworks": f"{query} treaties international law governing frameworks UN resolutions articles",
                "Precedents": f"{query} past security council resolutions border treaties legal arbitration precedents",
                "Crisis": f"{query} {country} crisis cabinet actions backroom directives portfolio strategy bloc diplomacy",
                "Rhetoric": f"{query} debate speech moderated caucus clash arguments defensive deflections sword",
                "Resolutions": f"{query} draft resolution preambulatory operative clauses cabinet directive template"
            }

        
        structured_results = {}
        # Ensure all pending chunks are embedded first
        self.embed_pending_chunks()
        
        for module, sub_q in sub_queries.items():
            print(f"Executing sub-query for {module} (Domain: {domain_lower}): '{sub_q}'")
            # Expand sub-query
            expanded = self.expand_query(sub_q, domain_lower)
            
            # Fetch for the sub-query (using the primary expansion)
            q_emb = self.model.encode(expanded[0], convert_to_numpy=True)
            res = self.db.semantic_search(q_emb, top_k=top_k_per_module * 2)
            
            # Apply trust reranking
            reranked = []
            for r in res:
                similarity = r["similarity"]
                trust = r["trust_score"]
                r["reranked_score"] = similarity * (1.0 + 0.3 * (trust - 0.5))
                reranked.append(r)
                
            reranked.sort(key=lambda x: x["reranked_score"], reverse=True)
            structured_results[module] = reranked[:top_k_per_module]
            
        return structured_results


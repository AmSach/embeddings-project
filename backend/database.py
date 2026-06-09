import sqlite3
import os
import json
import numpy as np
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mun_research.db")

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_db()
        self.embeddings_cache = None  # NumPy matrix: (num_chunks, dim)
        self.chunk_ids_cache = []     # List of chunk_ids parallel to cache

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Sources table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    title TEXT,
                    trust_score REAL,
                    raw_content TEXT,
                    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    category TEXT
                )
            """)

            # Chunks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER,
                    text TEXT,
                    chunk_index INTEGER,
                    FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
                )
            """)

            # Embeddings table (Vector stored as float32 binary blob)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    chunk_id INTEGER PRIMARY KEY,
                    vector BLOB,
                    FOREIGN KEY (chunk_id) REFERENCES chunks (id) ON DELETE CASCADE
                )
            """)

            # Entities table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    type TEXT
                )
            """)

            # Entity relations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_1 TEXT,
                    entity_2 TEXT,
                    source_id INTEGER,
                    description TEXT,
                    FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE,
                    UNIQUE(entity_1, entity_2, source_id)
                )
            """)

            # Notes table (Notion-like document capability)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    content TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()

    # --- Source Operations ---
    
    def insert_source(self, url: str, title: str, trust_score: float, raw_content: str, category: str = "General") -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO sources (url, title, trust_score, raw_content, category)
                    VALUES (?, ?, ?, ?, ?)
                """, (url, title, trust_score, raw_content, category))
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # If source URL already exists, update content and trust score
                cursor.execute("""
                    UPDATE sources 
                    SET title = ?, trust_score = ?, raw_content = ?, category = ?, crawled_at = CURRENT_TIMESTAMP
                    WHERE url = ?
                """, (title, trust_score, raw_content, category, url))
                cursor.execute("SELECT id FROM sources WHERE url = ?", (url,))
                row = cursor.fetchone()
                conn.commit()
                return row[0] if row else -1

    def get_source(self, source_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_sources(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, url, title, trust_score, category, crawled_at FROM sources ORDER BY crawled_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    # --- Chunk Operations ---

    def insert_chunks_and_embeddings(self, source_id: int, chunks: List[str], embeddings: List[np.ndarray]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Delete old chunks for this source if they exist (to support overwrite/updates)
            cursor.execute("SELECT id FROM chunks WHERE source_id = ?", (source_id,))
            old_chunk_ids = [r[0] for r in cursor.fetchall()]
            if old_chunk_ids:
                placeholders = ",".join("?" for _ in old_chunk_ids)
                cursor.execute(f"DELETE FROM embeddings WHERE chunk_id IN ({placeholders})", old_chunk_ids)
                cursor.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))

            # Insert new chunks & embeddings
            for i, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
                cursor.execute("""
                    INSERT INTO chunks (source_id, text, chunk_index)
                    VALUES (?, ?, ?)
                """, (source_id, chunk_text, i))
                chunk_id = cursor.lastrowid
                
                # Convert embedding to float32 binary blob
                vector_bytes = emb.astype(np.float32).tobytes()
                cursor.execute("""
                    INSERT INTO embeddings (chunk_id, vector)
                    VALUES (?, ?)
                """, (chunk_id, vector_bytes))
            
            conn.commit()
        # Invalidate cache since database changed
        self.invalidate_vector_cache()

    # --- Vector Cache & Search ---

    def invalidate_vector_cache(self):
        self.embeddings_cache = None
        self.chunk_ids_cache = []

    def load_vector_cache(self):
        """Loads all embeddings from DB into RAM for fast search."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chunk_id, vector FROM embeddings")
            rows = cursor.fetchall()
            
            if not rows:
                self.embeddings_cache = None
                self.chunk_ids_cache = []
                return

            chunk_ids = []
            vectors = []
            for row in rows:
                chunk_ids.append(row[0])
                # Convert blob back to numpy array
                vec = np.frombuffer(row[1], dtype=np.float32)
                vectors.append(vec)
            
            self.embeddings_cache = np.vstack(vectors)
            self.chunk_ids_cache = chunk_ids

    def semantic_search(self, query_vector: np.ndarray, top_k: int = 10) -> List[Dict[str, Any]]:
        """Performs cosine similarity search against cache and joins source metadata."""
        if self.embeddings_cache is None:
            self.load_vector_cache()
            if self.embeddings_cache is None:
                return []

        # Ensure query_vector is float32
        q_vec = query_vector.astype(np.float32)
        
        # Compute cosine similarities in batch using NumPy
        # Cosine Similarity = (A . B) / (||A|| * ||B||)
        dot_products = np.dot(self.embeddings_cache, q_vec)
        norms_matrix = np.linalg.norm(self.embeddings_cache, axis=1)
        norm_query = np.linalg.norm(q_vec)
        
        # Avoid division by zero
        norms_matrix[norms_matrix == 0] = 1e-10
        if norm_query == 0:
            norm_query = 1e-10

        similarities = dot_products / (norms_matrix * norm_query)
        
        # Get top_k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]
        
        results = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for idx in top_indices:
                chunk_id = self.chunk_ids_cache[idx]
                score = float(similarities[idx])
                
                # Fetch text and source info
                cursor.execute("""
                    SELECT c.text, c.chunk_index, s.id as source_id, s.url, s.title, s.trust_score, s.category
                    FROM chunks c
                    JOIN sources s ON c.source_id = s.id
                    WHERE c.id = ?
                """, (chunk_id,))
                row = cursor.fetchone()
                if row:
                    results.append({
                        "chunk_id": chunk_id,
                        "text": row["text"],
                        "chunk_index": row["chunk_index"],
                        "similarity": score,
                        "source_id": row["source_id"],
                        "url": row["url"],
                        "title": row["title"],
                        "trust_score": row["trust_score"],
                        "category": row["category"]
                    })
        
        return results

    # --- Entity & Relation Operations ---

    def insert_entity(self, name: str, entity_type: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO entities (name, type)
                    VALUES (?, ?)
                """, (name, entity_type))
                conn.commit()
            except sqlite3.IntegrityError:
                pass  # Entity already exists

    def insert_relation(self, entity_1: str, entity_2: str, source_id: int, description: str):
        # Always store sorted to prevent duplicates in undirected edges
        e1, e2 = sorted([entity_1, entity_2])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO entity_relations (entity_1, entity_2, source_id, description)
                    VALUES (?, ?, ?, ?)
                """, (e1, e2, source_id, description))
                conn.commit()
            except sqlite3.IntegrityError:
                # If relationship exists for this source, update description
                cursor.execute("""
                    UPDATE entity_relations
                    SET description = ?
                    WHERE entity_1 = ? AND entity_2 = ? AND source_id = ?
                """, (description, e1, e2, source_id))
                conn.commit()

    def get_relations_graph(self) -> List[Dict[str, Any]]:
        """Returns all relations to build the frontend graph visualization."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.entity_1, r.entity_2, r.description, s.title as source_title, s.url as source_url, s.trust_score
                FROM entity_relations r
                JOIN sources s ON r.source_id = s.id
            """)
            return [dict(row) for row in cursor.fetchall()]

    # --- Notes Operations (Notion-like Editor) ---

    def create_note(self, title: str, content: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notes (title, content)
                VALUES (?, ?)
            """, (title, content))
            conn.commit()
            return cursor.lastrowid

    def update_note(self, note_id: int, title: str, content: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE notes
                SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (title, content, note_id))
            conn.commit()

    def get_note(self, note_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_notes(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, updated_at FROM notes ORDER BY updated_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_note(self, note_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()

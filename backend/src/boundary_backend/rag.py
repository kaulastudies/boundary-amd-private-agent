"""Deterministic, local-only synthetic evidence retrieval."""

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

import numpy as np

from .models import EvidenceItem


class RagUnavailableError(RuntimeError):
    """A required local-only embedding or index resource is unavailable."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunk_document(document_id: str, text: str, max_chars: int = 900, overlap: int = 120) -> list[dict[str, str]]:
    """Chunk UTF-8 text deterministically while retaining the active heading."""
    if max_chars < 200 or overlap < 0 or overlap >= max_chars:
        raise ValueError("invalid chunk bounds")
    sections: list[tuple[str, str]] = []
    heading = "Document"
    body: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith("#"):
            if body:
                sections.append((heading, "\n".join(body).strip()))
                body = []
            heading = line.lstrip("#").strip() or "Document"
        else:
            body.append(line)
    if body:
        sections.append((heading, "\n".join(body).strip()))
    chunks: list[dict[str, str]] = []
    for section, content in sections:
        if not content:
            continue
        start = 0
        while start < len(content):
            end = min(start + max_chars, len(content))
            if end < len(content):
                boundary = content.rfind("\n", start, end)
                if boundary <= start:
                    boundary = content.rfind(" ", start, end)
                if boundary > start + 200:
                    end = boundary
            value = content[start:end].strip()
            digest = hashlib.sha256(f"{document_id}\0{section}\0{start}\0{value}".encode("utf-8")).hexdigest()[:24]
            chunks.append({"chunk_id": f"chunk-{digest}", "section": section, "text": value})
            if end >= len(content):
                break
            start = max(start + 1, end - overlap)
    return chunks


class Embedder(Protocol):
    model_name: str
    device: str
    def available(self) -> bool: ...
    def encode(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str) -> None:
        self.model_name, self.device, self._model = model_name, device, None

    def _load(self) -> None:
        if self._model is None:
            os.environ.setdefault("HF_HOME", "/workspace/cache/huggingface")
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/workspace/cache/huggingface/hub")
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RagUnavailableError("local embedding dependencies are unavailable") from exc
            try:
                self._model = SentenceTransformer(self.model_name, device=self.device, local_files_only=True)
            except (OSError, ValueError, RuntimeError) as exc:
                raise RagUnavailableError("local embedding model is not cached or cannot be loaded") from exc

    def available(self) -> bool:
        try:
            self._load()
        except RagUnavailableError:
            return False
        return True

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        values = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return np.asarray(values, dtype=np.float32)


class RagService:
    def __init__(self, database_path: str, index_path: str, embedder: Embedder, demo_path: Path, prefer_faiss: bool = True) -> None:
        self.database_path, self.index_path, self.embedder = database_path, Path(index_path), embedder
        self.metadata_path = self.index_path.with_name("index-metadata.json")
        self.demo_path, self.prefer_faiss = demo_path, prefer_faiss
        self._vectors: Optional[np.ndarray] = None
        self._chunk_ids: list[str] = []
        self._backend = "unavailable"
        self._initialize_tables()
        self._reload_index()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_tables(self) -> None:
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS rag_documents(document_id TEXT PRIMARY KEY,title TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,synthetic INTEGER NOT NULL,ingested_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rag_chunks(chunk_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,ordinal INTEGER NOT NULL,section TEXT NOT NULL,text TEXT NOT NULL,FOREIGN KEY(document_id) REFERENCES rag_documents(document_id));
            CREATE TABLE IF NOT EXISTS run_evidence(run_id TEXT NOT NULL,ordinal INTEGER NOT NULL,citation_label TEXT NOT NULL,document_title TEXT NOT NULL,section TEXT NOT NULL,chunk_id TEXT NOT NULL,snippet TEXT NOT NULL,relevance_score REAL NOT NULL,PRIMARY KEY(run_id,ordinal));
            CREATE TABLE IF NOT EXISTS rag_audit_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,timestamp_utc TEXT NOT NULL,metadata_json TEXT NOT NULL,previous_hash TEXT,event_hash TEXT NOT NULL);
            """)

    def _audit(self, event_type: str, metadata: dict[str, Any]) -> None:
        with self._connect() as db:
            row=db.execute("SELECT event_hash FROM rag_audit_events ORDER BY sequence DESC LIMIT 1").fetchone(); previous=row[0] if row else None
            timestamp=_utc_now(); payload={"event_type":event_type,"timestamp_utc":timestamp,"metadata":metadata,"previous_hash":previous}
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            db.execute("INSERT INTO rag_audit_events(event_type,timestamp_utc,metadata_json,previous_hash,event_hash) VALUES(?,?,?,?,?)",(event_type,timestamp,json.dumps(metadata,sort_keys=True),previous,digest))

    def _reload_index(self) -> None:
        if not self.index_path.exists() or not self.metadata_path.exists():
            return
        try:
            meta = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if meta.get("embedding_model") != self.embedder.model_name:
                return
            self._chunk_ids = meta["chunk_ids"]
            if meta["backend"] == "faiss":
                import faiss
                self._index = faiss.read_index(str(self.index_path))
                if self._index.ntotal != len(self._chunk_ids):
                    raise ValueError("FAISS index count does not match metadata")
                self._backend = "faiss"
            else:
                self._vectors = np.load(self.index_path, allow_pickle=False)
                if self._vectors.ndim != 2 or self._vectors.shape[0] != len(self._chunk_ids):
                    raise ValueError("NumPy index count does not match metadata")
                self._backend = "numpy"
        except Exception:
            self._backend, self._chunk_ids = "unavailable", []

    def _save_index(self, vectors: np.ndarray, chunk_ids: list[str]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        backend = "numpy"
        fd, temp_name = tempfile.mkstemp(dir=self.index_path.parent, prefix="boundary-index-")
        os.close(fd)
        try:
            if self.prefer_faiss:
                try:
                    import faiss
                except ImportError as exc:
                    raise RagUnavailableError("local FAISS dependency is unavailable") from exc
                index = faiss.IndexFlatIP(vectors.shape[1]); index.add(vectors)
                faiss.write_index(index, temp_name); self._index = index; backend = "faiss"
            else:
                with open(temp_name, "wb") as handle: np.save(handle, vectors)
                self._vectors = vectors
            os.replace(temp_name, self.index_path)
            metadata = {"version": 1, "backend": backend, "embedding_model": self.embedder.model_name, "chunk_ids": chunk_ids}
            meta_fd, meta_name = tempfile.mkstemp(dir=self.index_path.parent, prefix="boundary-metadata-")
            try:
                with os.fdopen(meta_fd, "w", encoding="utf-8") as handle:
                    json.dump(metadata, handle, sort_keys=True)
                os.replace(meta_name, self.metadata_path)
            finally:
                if os.path.exists(meta_name): os.unlink(meta_name)
            self._backend, self._chunk_ids = backend, chunk_ids
        finally:
            if os.path.exists(temp_name): os.unlink(temp_name)

    def bootstrap(self) -> dict[str, Any]:
        files = sorted(self.demo_path.glob("*.md"))
        if not files: raise RuntimeError("bundled synthetic evidence is unavailable")
        self._audit("rag_bootstrap_started", {"document_count": len(files)})
        with self._connect() as db:
            for path in files:
                raw = path.read_bytes(); text = raw.decode("utf-8"); sha = hashlib.sha256(raw).hexdigest(); document_id = "doc-" + sha[:20]
                title = next((line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")), path.stem)
                db.execute("INSERT OR IGNORE INTO rag_documents VALUES(?,?,?,?,?)", (document_id,title,sha,1,_utc_now()))
                for ordinal, chunk in enumerate(chunk_document(document_id, text)):
                    db.execute("INSERT OR IGNORE INTO rag_chunks VALUES(?,?,?,?,?)", (chunk["chunk_id"],document_id,ordinal,chunk["section"],chunk["text"]))
            rows = db.execute("SELECT chunk_id,text FROM rag_chunks ORDER BY document_id,ordinal").fetchall()
        vectors = self.embedder.encode([row["text"] for row in rows])
        norms = np.linalg.norm(vectors, axis=1, keepdims=True); vectors = vectors / np.maximum(norms, 1e-12)
        self._save_index(vectors.astype(np.float32), [row["chunk_id"] for row in rows])
        health = self.health(); result={"document_count": health["document_count"],"chunk_count":health["chunk_count"],"embedding_model":self.embedder.model_name,"index_backend":self._backend}
        self._audit("rag_bootstrap_completed", {"document_count":result["document_count"],"chunk_count":result["chunk_count"],"index_backend":result["index_backend"]})
        return result

    def health(self) -> dict[str, Any]:
        with self._connect() as db:
            docs=db.execute("SELECT count(*) FROM rag_documents").fetchone()[0]; chunks=db.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
        checker = getattr(self.embedder, "available", None)
        embedding_available = bool(checker()) if checker is not None else True
        available = embedding_available and self._backend in {"faiss","numpy"} and chunks==len(self._chunk_ids) and chunks>0
        return {"available":available,"local_only":True,"embedding_model":self.embedder.model_name,"embedding_device":self.embedder.device,"index_backend":self._backend,"document_count":docs,"chunk_count":chunks,"persisted_index":"boundary.faiss","remote_apis_enabled":False}

    def documents(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows=db.execute("SELECT d.*,count(c.chunk_id) chunk_count FROM rag_documents d LEFT JOIN rag_chunks c ON c.document_id=d.document_id GROUP BY d.document_id ORDER BY d.title LIMIT 100").fetchall()
        return [{"document_id":r["document_id"],"title":r["title"],"synthetic":True,"sha256":r["sha256"],"chunk_count":r["chunk_count"],"ingested_at":r["ingested_at"]} for r in rows]

    def query(self, query: str, top_k: int) -> tuple[list[EvidenceItem], float]:
        started=time.perf_counter(); health=self.health()
        if not health["available"]:
            if self._backend in {"faiss", "numpy"}:
                raise RagUnavailableError("local embedding model is not cached or cannot be loaded")
            raise RuntimeError("local evidence index is unavailable")
        vector=self.embedder.encode([query]).astype(np.float32); vector/=max(float(np.linalg.norm(vector)),1e-12)
        if self._backend=="faiss": scores, indexes=self._index.search(vector, min(top_k,len(self._chunk_ids))); pairs=list(zip(indexes[0],scores[0]))
        else:
            scores=(self._vectors @ vector[0]); indexes=np.argsort(-scores)[:top_k]; pairs=[(int(i),float(scores[i])) for i in indexes]
        ids=[self._chunk_ids[i] for i,_ in pairs if i>=0]
        with self._connect() as db:
            rows={r["chunk_id"]:r for r in db.execute(f"SELECT c.*,d.title FROM rag_chunks c JOIN rag_documents d ON d.document_id=c.document_id WHERE c.chunk_id IN ({','.join('?' for _ in ids)})",ids)}
        evidence=[]
        for rank,(index,score) in enumerate(pairs,1):
            if index<0: continue
            row=rows[self._chunk_ids[index]]; snippet=" ".join(row["text"].split())[:600]
            evidence.append(EvidenceItem(citation_label=f"E{rank}",document_title=row["title"],section=row["section"],chunk_id=row["chunk_id"],snippet=snippet,relevance_score=round(float(score),6)))
        return evidence,(time.perf_counter()-started)*1000

    def store_run_evidence(self, run_id: str, evidence: list[EvidenceItem]) -> None:
        with self._connect() as db:
            for i,item in enumerate(evidence): db.execute("INSERT OR REPLACE INTO run_evidence VALUES(?,?,?,?,?,?,?,?)",(run_id,i,item.citation_label,item.document_title,item.section,item.chunk_id,item.snippet,item.relevance_score))

    def run_evidence(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as db: rows=db.execute("SELECT * FROM run_evidence WHERE run_id=? ORDER BY ordinal",(run_id,)).fetchall()
        return [{k:r[k] for k in ("citation_label","document_title","section","chunk_id","snippet","relevance_score")} for r in rows]

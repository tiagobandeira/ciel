"""Persistência de artigos salvos no SQLite da interface.

A sessão guarda os artigos em memória; só o que o usuário salvar entra aqui.
Assim salvar um artigo não depende da sessão atual nem sobrevive a um reload
por acidente.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from history_store import DB_PATH

_DDL = """
CREATE TABLE IF NOT EXISTS saved_articles (
    id          TEXT PRIMARY KEY,
    article_id  TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    blocks_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    agent_id    TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    provider    TEXT NOT NULL DEFAULT '',
    session_id  TEXT NOT NULL DEFAULT '',
    origin      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_saved_articles_created
    ON saved_articles(created_at DESC);
"""


class ArticleStore:
    def __init__(self, db_path: Path = DB_PATH):
        self._path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_DDL)
            self._conn.commit()

    def _row(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "article_id": row["article_id"],
            "titulo": row["title"],
            "blocos": json.loads(row["blocks_json"]),
            "criado": row["created_at"],
            "agente": row["agent_id"],
            "modelo": row["model"],
            "provider": row["provider"],
            "sessao": row["session_id"],
            "origem": row["origin"],
        }

    def salvar(self, titulo: str, blocos: list, meta: dict | None = None) -> dict:
        meta = meta or {}
        saved_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO saved_articles
                    (id, article_id, title, blocks_json, created_at,
                     agent_id, model, provider, session_id, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    saved_id,
                    str(meta.get("article_id") or "")[:80],
                    str(titulo or "")[:120],
                    json.dumps(blocos, ensure_ascii=False),
                    now,
                    str(meta.get("agente") or "")[:80],
                    str(meta.get("modelo") or "")[:120],
                    str(meta.get("provider") or "")[:120],
                    str(meta.get("sessao") or "")[:80],
                    str(meta.get("origem") or "")[:80],
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM saved_articles WHERE id=?", (saved_id,)
            ).fetchone()
        return self._row(row)

    def listar(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM saved_articles ORDER BY created_at DESC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def obter(self, saved_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM saved_articles WHERE id=?", (str(saved_id),)
            ).fetchone()
        return self._row(row) if row else None

    def remover(self, saved_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM saved_articles WHERE id=?", (str(saved_id),)
            )
            self._conn.commit()
            return cur.rowcount > 0

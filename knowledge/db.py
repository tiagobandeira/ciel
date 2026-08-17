"""
knowledge/db.py
───────────────
Schema e acesso ao banco SQLite + FTS5.

Estrutura de arquivos:
  sources/
    <agent_id>/
      _shared/          ← fontes permanentes do agente
      <session_id>/     ← fontes da sessão específica

Tabelas:
  sources   → metadados de cada fonte indexada
  chunks    → tabela principal (conteúdo + metadados)
  chunks_fts → índice FTS5 virtual sobre chunks
"""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path("knowledge/knowledge.db")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Cria as tabelas se não existirem."""
    conn = get_conn()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT    NOT NULL,
                session_id  TEXT    NOT NULL,
                filename    TEXT    NOT NULL,
                filepath    TEXT    NOT NULL,
                filetype    TEXT    NOT NULL,
                summary     TEXT,
                topics      TEXT,
                n_chunks    INTEGER DEFAULT 0,
                created_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(agent_id, session_id, filepath)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                content     TEXT    NOT NULL,
                n_tokens    INTEGER DEFAULT 0,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
            USING fts5(
                content,
                content='chunks',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ai
            AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, content)
                VALUES (new.id, new.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ad
            AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_au
            AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
                INSERT INTO chunks_fts(rowid, content)
                VALUES (new.id, new.content);
            END
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_agent ON sources(agent_id, session_id)")

    conn.close()


# ── helpers de escopo ─────────────────────────────────────────────────────────

def get_session_chain(session_id: str) -> list[str]:
    """
    Retorna o session_id atual + todos os ancestrais (pai, avô, …)
    seguindo a cadeia parent_session_id no agent_history.db.
    Sempre inclui o session_id recebido, mesmo se falhar ao ler o histórico.
    """
    ids = [session_id]
    try:
        from history_store import DB_PATH as HIST_PATH
        hconn = sqlite3.connect(str(HIST_PATH))
        hconn.row_factory = sqlite3.Row
        current = session_id
        for _ in range(20):  # limite de profundidade pra evitar loop infinito
            row = hconn.execute(
                "SELECT parent_session_id FROM sessions WHERE id=?",
                (current,)
            ).fetchone()
            if not row or not row["parent_session_id"]:
                break
            parent = str(row["parent_session_id"])
            if parent in ids:  # detecta ciclo
                break
            ids.append(parent)
            current = parent
        hconn.close()
    except Exception:
        pass
    return ids


# ── helpers de escrita ────────────────────────────────────────────────────────

def insert_source(
    agent_id: str,
    session_id: str,
    filename: str,
    filepath: str,
    filetype: str,
    summary: str = "",
    topics: list[str] | None = None,
) -> int:
    conn = get_conn()
    with conn:
        conn.execute(
            "DELETE FROM sources WHERE agent_id=? AND session_id=? AND filepath=?",
            (agent_id, session_id, filepath),
        )
        cur = conn.execute(
            """
            INSERT INTO sources (agent_id, session_id, filename, filepath, filetype, summary, topics)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, session_id, filename, filepath, filetype,
             summary, json.dumps(topics or [], ensure_ascii=False)),
        )
        source_id = cur.lastrowid
    conn.close()
    return source_id


def insert_chunks(source_id: int, chunks: list[str], token_counts: list[int]):
    total = len(chunks)
    conn = get_conn()
    with conn:
        for i, (text, n_tok) in enumerate(zip(chunks, token_counts)):
            conn.execute(
                """
                INSERT INTO chunks (source_id, chunk_index, total_chunks, content, n_tokens)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_id, i, total, text, n_tok),
            )
        conn.execute(
            "UPDATE sources SET n_chunks=? WHERE id=?",
            (total, source_id),
        )
    conn.close()


def delete_source(source_id: int):
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    conn.close()


# ── helpers de leitura ────────────────────────────────────────────────────────

def list_sources(agent_id: str, session_id: str | None = None) -> list[dict]:
    """
    Lista fontes de um agente.

    Escopo:
      - session_id fornecido → sessão atual + todos os ancestrais + _shared
      - session_id None      → só _shared do agente
    """
    conn = get_conn()

    if session_id:
        all_ids = get_session_chain(session_id)
        placeholders = ",".join("?" * len(all_ids))
        rows = conn.execute(
            f"""
            SELECT * FROM sources
            WHERE agent_id=? AND session_id IN ({placeholders}, '_shared')
            ORDER BY session_id, created_at
            """,
            (agent_id, *all_ids),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM sources
            WHERE agent_id=? AND session_id='_shared'
            ORDER BY created_at
            """,
            (agent_id,),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_source(source_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_chunks(source_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM chunks WHERE source_id=? ORDER BY chunk_index",
        (source_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def cleanup_orphan_sources() -> int:
    """
    Remove fontes cujo session_id não existe mais no agent_history.db.
    Mantém _shared intacto.
    Retorna o número de sessões órfãs removidas.
    """
    try:
        from history_store import DB_PATH as HIST_PATH
        hconn = sqlite3.connect(str(HIST_PATH))
        valid_ids = {
            str(r[0]) for r in
            hconn.execute("SELECT id FROM sessions").fetchall()
        }
        hconn.close()
    except Exception:
        return 0  # se não conseguir ler o histórico, não faz nada

    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT session_id FROM sources WHERE session_id != '_shared'"
    ).fetchall()

    orphans = [r[0] for r in rows if r[0] not in valid_ids]

    for sid in orphans:
        conn.execute("DELETE FROM sources WHERE session_id=?", (sid,))

    conn.commit()
    conn.close()
    return len(orphans)

if __name__ == "__main__":
    init_db()
    print(f"Banco inicializado em: {DB_PATH.resolve()}")
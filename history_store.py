"""
history_store.py — Persistência de conversas da Agent CLI via SQLite.

Schema:
  sessions      → uma conversa completa (agent, título, resumo, branch)
  conversations → turnos individuais (user/agent) de uma sessão

Uso:
  from history_store import HistoryStore
  store = HistoryStore()                         # abre/cria agent_history.db
  sid = store.new_session("csv_manager", "título")
  store.append_turn(sid, "user", "olá")
  store.append_turn(sid, "agent", "oi!")
  store.save_summary(sid, "Resumo gerado pelo modelo")
  sessions = store.list_sessions()              # todas, mais recentes primeiro
  sessions = store.list_sessions("csv_manager") # filtrado por agente
  turns    = store.get_turns(sid)
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("agent_history.db")

_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id         TEXT    NOT NULL,
    title            TEXT    NOT NULL DEFAULT '',
    summary          TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    parent_session_id INTEGER REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK(role IN ('user', 'agent')),
    content    TEXT    NOT NULL,
    ts         TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_sess_agent   ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sess_updated ON sessions(updated_at DESC);
"""


class HistoryStore:
    def __init__(self, db_path: Path = DB_PATH):
        self._path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ── sessões ──────────────────────────────────────────────────────────────

    def new_session(
        self,
        agent_id: str,
        title: str = "",
        parent_session_id: int | None = None,
    ) -> int:
        """Cria nova sessão e retorna o id."""
        now = _now()
        cur = self._conn.execute(
            """
            INSERT INTO sessions (agent_id, title, summary, created_at, updated_at, parent_session_id)
            VALUES (?, ?, '', ?, ?, ?)
            """,
            (agent_id, title, now, now, parent_session_id),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_title(self, session_id: int, title: str):
        self._conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (title, _now(), session_id),
        )
        self._conn.commit()

    def save_summary(self, session_id: int, summary: str):
        self._conn.execute(
            "UPDATE sessions SET summary=?, updated_at=? WHERE id=?",
            (summary, _now(), session_id),
        )
        self._conn.commit()

    def list_sessions(self, agent_id: str | None = None) -> list[sqlite3.Row]:
        """
        Retorna sessões ordenadas pela mais recente.
        Se agent_id for passado, filtra por agente.
        """
        if agent_id:
            return self._conn.execute(
                """
                SELECT s.*, COUNT(c.id) AS turn_count
                FROM sessions s
                LEFT JOIN conversations c ON c.session_id = s.id
                WHERE s.agent_id = ?
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                """,
                (agent_id,),
            ).fetchall()
        return self._conn.execute(
            """
            SELECT s.*, COUNT(c.id) AS turn_count
            FROM sessions s
            LEFT JOIN conversations c ON c.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        ).fetchall()

    def get_session(self, session_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()

    def delete_session(self, session_id: int):
        """Remove sessão e todos os turnos (CASCADE)."""
        self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        self._conn.commit()
        # limpa fontes órfãs do knowledge.db
        try:
            from knowledge.db import get_conn
            kconn = get_conn()
            kconn.execute(
                "DELETE FROM sources WHERE session_id=?",
                (str(session_id),)
            )
            kconn.commit()
            kconn.close()
        except Exception:
            pass
        # limpa cache de URLs indexadas nessa sessão
        try:
            from knowledge.ingest_url import delete_session_cache
            delete_session_cache(str(session_id))
        except Exception:
            pass
        

    # ── turnos ───────────────────────────────────────────────────────────────

    def append_turn(self, session_id: int, role: str, content: str, ts: str = ""):
        """Salva um turno e atualiza updated_at da sessão."""
        ts = ts or _now()
        self._conn.execute(
            "INSERT INTO conversations (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (session_id, role, content, ts),
        )
        self._conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id)
        )
        self._conn.commit()

    def get_turns(self, session_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM conversations WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()

    # ── branch (ramificação) ─────────────────────────────────────────────────

    def branch_session(self, parent_id: int, agent_id: str, title: str = "") -> int:
        """Cria nova sessão filha de parent_id."""
        parent = self.get_session(parent_id)
        title = title or (f"[branch] {parent['title']}" if parent else "branch")
        return self.new_session(agent_id, title, parent_session_id=parent_id)

    # ── exportação Markdown ──────────────────────────────────────────────────

    def export_markdown(self, session_id: int, out_path: Path | None = None) -> Path:
        """
        Gera um arquivo .md com toda a conversa formatada.
        Retorna o Path do arquivo criado.
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Sessão {session_id} não encontrada.")

        turns = self.get_turns(session_id)
        lines = [
            f"# {session['title'] or 'Conversa sem título'}",
            f"",
            f"**Agente:** `{session['agent_id']}`  ",
            f"**Data:** {session['created_at'][:16]}  ",
            f"**Sessão:** #{session_id}",
            f"",
        ]

        if session["summary"]:
            lines += [
                "## Resumo",
                "",
                session["summary"],
                "",
                "---",
                "",
            ]

        lines.append("## Conversa")
        lines.append("")

        for turn in turns:
            role_label = "**Você**" if turn["role"] == "user" else "**Agente**"
            ts = f" _{turn['ts']}_" if turn["ts"] else ""
            lines.append(f"{role_label}{ts}")
            lines.append("")
            lines.append(turn["content"])
            lines.append("")
            lines.append("---")
            lines.append("")

        md_content = "\n".join(lines)

        if out_path is None:
            safe_title = "".join(
                c if c.isalnum() or c in "-_ " else "_"
                for c in (session["title"] or f"sessao_{session_id}")
            )[:40].strip()
            out_path = Path(f"history_{session_id}_{safe_title}.md")

        out_path.write_text(md_content, encoding="utf-8")
        return out_path

    def close(self):
        self._conn.close()


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def format_session_row(row: sqlite3.Row, idx: int | None = None) -> str:
    """
    Formata uma linha de sessão para exibição no terminal (sem rich).
    idx: número de seleção (opcional).
    """
    prefix  = f"{idx:>3}. " if idx is not None else "     "
    agent   = row["agent_id"].ljust(14)
    date    = row["updated_at"][:16]
    turns   = row["turn_count"]
    title   = (row["title"] or "(sem título)")[:50]
    has_sum = "★" if row["summary"] else " "
    return f"{prefix}{has_sum} [{date}] {agent}  {turns:>3}t  {title}"

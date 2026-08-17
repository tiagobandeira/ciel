"""
knowledge/retriever.py
──────────────────────
Busca FTS5 nos chunks indexados.

Fluxo:
  query → expand_query() → FTS5 → rerank → top-k chunks

expand_query() é opcional mas muito útil pra modelos locais:
  "como Goldbach prova isso?" → ["Goldbach", "proof", "conjecture", "prime"]
  Pode ser chamado com um modelo local antes da busca.
"""

import sqlite3
from dataclasses import dataclass

from knowledge.db import get_conn, get_session_chain


# ── resultado ─────────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    source_id:    int
    chunk_id:     int
    chunk_index:  int
    total_chunks: int
    filename:     str
    session_id:   str
    content:      str
    score:        float   # bm25 do FTS5 (negativo — menor = melhor)
    n_tokens:     int

    def format(self) -> str:
        """Formato pronto pra injetar no contexto do agente."""
        pos = f"{self.chunk_index + 1}/{self.total_chunks}"
        return (
            f"[FONTE: {self.filename} | chunk {pos}]\n"
            f"{self.content}"
        )


# ── busca principal ───────────────────────────────────────────────────────────

def search(
    query:      str,
    agent_id:   str,
    session_id: str | None = None,
    top_k:      int = 5,
    min_tokens: int = 20,
) -> list[SearchResult]:
    """
    Busca FTS5 nos chunks do agente.

    Escopo:
      - session_id fornecido → sessão atual + ancestrais + _shared
      - session_id None      → só _shared do agente
    """
    if not query.strip():
        return []

    fts_query = _sanitize_fts(query)
    if not fts_query:
        return []

    conn = get_conn()
    try:
        if session_id:
            # inclui sessão atual + todos os ancestrais (branch chain) + _shared
            all_ids = get_session_chain(session_id)
            placeholders = ",".join("?" * len(all_ids))
            rows = conn.execute(
                f"""
                SELECT
                    s.id          AS source_id,
                    c.id          AS chunk_id,
                    c.chunk_index,
                    c.total_chunks,
                    s.filename,
                    s.session_id,
                    c.content,
                    c.n_tokens,
                    bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks  c ON c.id = chunks_fts.rowid
                JOIN sources s ON s.id = c.source_id
                WHERE chunks_fts MATCH ?
                  AND s.agent_id   = ?
                  AND s.session_id IN ({placeholders}, '_shared')
                  AND c.n_tokens   >= ?
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, agent_id, *all_ids, min_tokens, top_k),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    s.id          AS source_id,
                    c.id          AS chunk_id,
                    c.chunk_index,
                    c.total_chunks,
                    s.filename,
                    s.session_id,
                    c.content,
                    c.n_tokens,
                    bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks  c ON c.id = chunks_fts.rowid
                JOIN sources s ON s.id = c.source_id
                WHERE chunks_fts MATCH ?
                  AND s.agent_id = ?
                  AND s.session_id = '_shared'
                  AND c.n_tokens >= ?
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, agent_id, min_tokens, top_k),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    return [
        SearchResult(
            source_id    = r["source_id"],
            chunk_id     = r["chunk_id"],
            chunk_index  = r["chunk_index"],
            total_chunks = r["total_chunks"],
            filename     = r["filename"],
            session_id   = r["session_id"],
            content      = r["content"],
            score        = r["score"],
            n_tokens     = r["n_tokens"],
        )
        for r in rows
    ]


def search_formatted(
    query:      str,
    agent_id:   str,
    session_id: str | None = None,
    top_k:      int = 5,
) -> str:
    """Versão pronta pra injetar no contexto do agente."""
    results = search(query, agent_id, session_id, top_k=top_k)
    if not results:
        return "Nenhum resultado encontrado para a consulta."
    parts = [r.format() for r in results]
    return "\n\n---\n\n".join(parts)


# ── expansão de query (opcional) ──────────────────────────────────────────────

def expand_query(query: str, keywords: list[str]) -> str:
    """
    Combina a query original com palavras-chave extraídas pelo LLM.

    Exemplo:
      query    = "como Goldbach prova isso?"
      keywords = ["Goldbach", "proof", "conjecture", "prime"]
      resultado = "Goldbach OR proof OR conjecture OR prime OR como"
    """
    _stopwords = {"a", "o", "e", "é", "de", "do", "da", "em", "um", "uma",
                  "para", "que", "com", "se", "não", "por", "isso", "como"}
    orig_words = [
        w for w in query.lower().split()
        if len(w) > 2 and w not in _stopwords
    ]
    all_terms = list(dict.fromkeys(keywords + orig_words))
    return " OR ".join(all_terms[:12])


# ── helpers ───────────────────────────────────────────────────────────────────

def _sanitize_fts(query: str) -> str:
    """Remove caracteres que quebram o parser FTS5."""
    import re
    clean = re.sub(r'[^\w\s\-]', ' ', query, flags=re.UNICODE)
    clean = re.sub(r'\s+', ' ', clean).strip()
    fts_keywords = {"AND", "OR", "NOT"}
    terms = [
        f'"{t}"' if t.upper() in fts_keywords else t
        for t in clean.split()
    ]
    return " ".join(terms)


# ── debug / teste rápido ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Uso: python -m knowledge.retriever <query> <agent_id> <session_id>")
        raise SystemExit(1)

    q, ag, sess = sys.argv[1], sys.argv[2], sys.argv[3]
    results = search(q, ag, sess, top_k=5)

    if not results:
        print("Nenhum resultado.")
    else:
        for i, r in enumerate(results, 1):
            print(f"\n{'─'*60}")
            print(f"#{i}  {r.filename}  chunk {r.chunk_index+1}/{r.total_chunks}"
                  f"  score={r.score:.4f}  tokens={r.n_tokens}")
            print(f"{'─'*60}")
            print(r.content[:400])
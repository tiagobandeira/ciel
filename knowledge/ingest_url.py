"""
knowledge/ingest_url.py

Ingere uma URL como fonte no knowledge base.

Fluxo:
  1. Fetch + extração de texto via read_url
  2. Salva texto completo em knowledge/cache/<session_id>/<hash>.txt
     (primeira linha = URL original, pra referência e limpeza manual)
  3. Chunking e indexação via knowledge.db direto (sem depender de ingest.py)
  4. filepath no banco aponta pro .txt local — read_source funciona sem alteração

Cache por sessão:
  knowledge/cache/<session_id>/   → removido junto com a sessão
  knowledge/cache/_shared/        → fontes globais, remoção manual

Limpeza de cache ao deletar sessão — já integrado em history_store.py:
  from knowledge.ingest_url import delete_session_cache
  delete_session_cache(session_id)

Uso:
    from knowledge.ingest_url import ingest_url
    source_id = ingest_url(
        url        = "https://exemplo.com/artigo",
        agent_id   = "general",
        session_id = "_shared",
        verbose    = True,
    )
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


# ── pasta raiz do cache ───────────────────────────────────────────────────────
_CACHE_ROOT = Path(__file__).parent / "cache"

# ── config de chunking (espelha ingest.py) ────────────────────────────────────
_CHUNK_SIZE    = 300
_CHUNK_OVERLAP = 45


# ── cache ─────────────────────────────────────────────────────────────────────

def _cache_dir(session_id: str) -> Path:
    d = _CACHE_ROOT / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _save_cache(session_id: str, url: str, texto: str) -> Path:
    """Salva texto em cache/<session_id>/<hash>.txt. Primeira linha = URL."""
    cache_file = _cache_dir(session_id) / f"{_url_hash(url)}.txt"
    cache_file.write_text(f"{url}\n\n{texto}", encoding="utf-8")
    return cache_file


def delete_session_cache(session_id: str) -> None:
    """Remove pasta de cache da sessão. Chamar ao deletar sessão."""
    import shutil
    pasta = _CACHE_ROOT / session_id
    if pasta.exists():
        shutil.rmtree(pasta)


# ── display name ──────────────────────────────────────────────────────────────

def _url_to_display_name(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").split("/")[-1]
    path = re.sub(r"\.[a-z]{2,4}$", "", path)
    path = re.sub(r"[^a-zA-Z0-9_-]", "_", path)
    host = parsed.netloc.replace("www.", "").replace(".", "_")
    name = f"{host}__{path}" if path else host
    return name[:80] + ".url"


# ── chunking (cópia local — evita importar ingest.py que tem deps relativas) ──

def _split_paragraphs(text: str) -> list[str]:
    paras = re.split(r"\n{2,}", text)
    return [p.strip() for p in paras if p.strip()]


def _word_count(text: str) -> int:
    return len(text.split())


def _chunk_text(text: str) -> list[str]:
    paragraphs = _split_paragraphs(text)
    chunks: list[str] = []
    current_words: list[str] = []
    current_paras: list[str] = []

    for para in paragraphs:
        para_words = para.split()

        if len(para_words) > _CHUNK_SIZE:
            if current_paras:
                chunks.append("\n\n".join(current_paras))
                current_paras = []
                current_words = []
            for start in range(0, len(para_words), _CHUNK_SIZE - _CHUNK_OVERLAP):
                chunks.append(" ".join(para_words[start: start + _CHUNK_SIZE]))
            continue

        if len(current_words) + len(para_words) > _CHUNK_SIZE:
            if current_paras:
                chunks.append("\n\n".join(current_paras))
            if _CHUNK_OVERLAP > 0 and current_words:
                overlap = current_words[-_CHUNK_OVERLAP:]
                current_paras = [" ".join(overlap)]
                current_words = overlap[:]
            else:
                current_paras = []
                current_words = []

        current_paras.append(para)
        current_words.extend(para_words)

    if current_paras:
        chunks.append("\n\n".join(current_paras))

    return chunks


def _quick_summary(text: str, max_chars: int = 600) -> str:
    paras = _split_paragraphs(text)
    summary = ""
    for p in paras:
        if len(summary) + len(p) > max_chars:
            break
        summary += p + "\n\n"
    return summary.strip()


# ── fetch ─────────────────────────────────────────────────────────────────────

def _fetch_texto(url: str) -> str:
    tools_dir = os.path.join(os.path.dirname(__file__), "..", "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)

    try:
        import read_url as _mod
        texto = _mod.run(url)
    except ImportError:
        texto = _fallback_fetch(url)

    if texto.startswith("Erro:"):
        raise RuntimeError(texto)
    if not texto.strip():
        raise ValueError("A URL não retornou conteúdo legível.")

    return texto


def _fallback_fetch(url: str) -> str:
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; PyAgentCLI/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    body = soup.body or soup
    return body.get_text(separator="\n", strip=True)[:20000]


# ── ingestão principal ────────────────────────────────────────────────────────

def ingest_url(
    url: str,
    agent_id: str,
    session_id: str,
    verbose: bool = False,
) -> int:
    """
    Baixa a URL, persiste o texto em cache e indexa no knowledge base.
    Retorna o source_id criado.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"URL inválida: '{url}'")

    # 1. fetch
    texto = _fetch_texto(url)
    if verbose:
        print(f"  → {len(texto)} chars extraídos de {url}")

    # 2. cache local
    cache_file = _save_cache(session_id, url, texto)
    if verbose:
        print(f"  → cache salvo em {cache_file}")

    # 3. chunking
    chunks       = _chunk_text(texto)
    token_counts = [_word_count(c) for c in chunks]
    summary      = _quick_summary(texto)
    filename     = _url_to_display_name(url)

    if verbose:
        print(f"  → {len(chunks)} chunks · resumo: {summary[:60]}…")

    # 4. indexação — importa knowledge.db direto (sem passar por ingest.py)
    from knowledge.db import init_db, insert_source, insert_chunks

    init_db()

    source_id = insert_source(
        agent_id   = agent_id,
        session_id = session_id,
        filename   = filename,
        filepath   = str(cache_file),
        filetype   = "url",
        summary    = summary,
    )

    insert_chunks(source_id=source_id, chunks=chunks, token_counts=token_counts)

    if verbose:
        print(f"  → indexada (id={source_id} · {filename})")

    return source_id
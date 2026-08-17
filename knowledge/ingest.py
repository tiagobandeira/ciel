"""
knowledge/ingest.py
───────────────────
Ingestão de fontes: extração de texto → chunking → indexação no SQLite/FTS5.

Uso direto (CLI separada):
  python -m knowledge.ingest arquivo.pdf --agent csv_manager --session abc123
  python -m knowledge.ingest nota.txt --agent general --global

Formatos suportados:
  .pdf  → pymupdf
  .txt  → leitura direta
  .md   → leitura direta
"""

import re
import json
import argparse
from pathlib import Path

from knowledge.db import init_db, insert_source, insert_chunks

# ── config de chunking ────────────────────────────────────────────────────────
# Unidade: palavras (proxy de tokens — ~1.3 palavras/token em PT/EN)
# CHUNK_SIZE=300 palavras ≈ 400 tokens — bom pra janelas ~8k
CHUNK_SIZE    = 300
CHUNK_OVERLAP = 45


# ── extração de texto ─────────────────────────────────────────────────────────

def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import fitz  # pymupdf
        except ImportError:
            raise ImportError("pymupdf não instalado. Execute: pip install pymupdf")
        doc  = fitz.open(str(path))
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text

    if suffix in (".txt", ".md", ".rst"):
        return path.read_text(encoding="utf-8", errors="replace")

    raise ValueError(f"Formato não suportado: {suffix}")


# ── chunking ──────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _split_paragraphs(text: str) -> list[str]:
    """Divide o texto em parágrafos (blocos separados por linha em branco)."""
    paras = re.split(r"\n{2,}", text)
    return [p.strip() for p in paras if p.strip()]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Estratégia:
      1. Divide em parágrafos
      2. Agrupa parágrafos até atingir chunk_size palavras
      3. Aplica overlap pegando as últimas `overlap` palavras do chunk anterior

    Preserva parágrafos inteiros sempre que possível.
    """
    paragraphs = _split_paragraphs(text)
    chunks: list[str] = []
    current_words: list[str] = []
    current_paras: list[str] = []

    for para in paragraphs:
        para_words = para.split()

        # parágrafo sozinho excede chunk_size → corta em pedaços por palavras
        if len(para_words) > chunk_size:
            if current_paras:
                chunks.append("\n\n".join(current_paras))
                current_paras = []
                current_words = []

            for start in range(0, len(para_words), chunk_size - overlap):
                slice_words = para_words[start: start + chunk_size]
                chunks.append(" ".join(slice_words))
            continue

        # adicionar esse parágrafo estouraria o limite → flush + overlap
        if len(current_words) + len(para_words) > chunk_size:
            if current_paras:
                chunks.append("\n\n".join(current_paras))

            if overlap > 0 and current_words:
                overlap_words = current_words[-overlap:]
                current_paras = [" ".join(overlap_words)]
                current_words = overlap_words[:]
            else:
                current_paras = []
                current_words = []

        current_paras.append(para)
        current_words.extend(para_words)

    if current_paras:
        chunks.append("\n\n".join(current_paras))

    return chunks


# ── ingestão principal ────────────────────────────────────────────────────────

def ingest(
    filepath: str | Path,
    agent_id: str,
    session_id: str,            # '_shared' ou uuid da sessão
    chunk_size: int = CHUNK_SIZE,
    overlap: int    = CHUNK_OVERLAP,
    verbose: bool   = True,
) -> int:
    """
    Extrai, chunka e indexa uma fonte.
    Retorna o source_id criado.
    """
    path = Path(filepath).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    if verbose:
        print(f"  → extraindo texto de '{path.name}'…")

    text = extract_text(path)

    if not text.strip():
        raise ValueError(f"Nenhum texto extraído de '{path.name}'")

    if verbose:
        n_chars = len(text)
        print(f"  → {n_chars:,} caracteres extraídos")

    # chunking
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    token_counts = [_word_count(c) for c in chunks]

    if verbose:
        total_tok = sum(token_counts)
        print(f"  → {len(chunks)} chunks  ({total_tok:,} tokens total)")

    # resumo simples: primeiros 3 parágrafos do texto (sem LLM ainda)
    # pode ser substituído por chamada ao modelo futuramente
    summary = _quick_summary(text)

    # grava no banco
    init_db()
    source_id = insert_source(
        agent_id   = agent_id,
        session_id = session_id,
        filename   = path.name,
        filepath   = str(path),
        filetype   = path.suffix.lstrip(".").lower(),
        summary    = summary,
        topics     = [],   # expansão futura: extração de tópicos via LLM
    )
    insert_chunks(source_id, chunks, token_counts)

    if verbose:
        print(f"  ✓ fonte indexada  (source_id={source_id})")

    return source_id


def _quick_summary(text: str, max_chars: int = 600) -> str:
    """
    Resumo rápido sem LLM: primeiros parágrafos até max_chars.
    Suficiente pra dar contexto ao list_sources sem custo de inferência.
    """
    paras = _split_paragraphs(text)
    summary = ""
    for p in paras:
        if len(summary) + len(p) > max_chars:
            break
        summary += p + "\n\n"
    return summary.strip()


# ── CLI standalone ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Indexa um arquivo no sistema de knowledge do agente."
    )
    parser.add_argument("filepath",              help="Caminho do arquivo a indexar")
    parser.add_argument("--agent",   required=True, help="ID do agente (ex: csv_manager)")
    parser.add_argument("--session", default=None,  help="ID da sessão (omitir usa '_shared')")
    parser.add_argument("--global",  dest="shared", action="store_true",
                        help="Indexar em _shared (permanente para o agente)")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--overlap",    type=int, default=CHUNK_OVERLAP)

    args = parser.parse_args()

    session_id = "_shared" if args.shared or not args.session else args.session

    print(f"\n[ingest] {args.filepath}")
    print(f"  agente:  {args.agent}")
    print(f"  sessão:  {session_id}\n")

    try:
        source_id = ingest(
            filepath   = args.filepath,
            agent_id   = args.agent,
            session_id = session_id,
            chunk_size = args.chunk_size,
            overlap    = args.overlap,
        )
        print(f"\n  source_id: {source_id}")
    except Exception as e:
        print(f"\n  ✗ erro: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

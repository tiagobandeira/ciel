"""Lê o conteúdo completo de uma fonte indexada pelo seu ID."""

from knowledge.db import get_source, get_chunks

MAX_CHARS = 6_000  # limite pra não explodir o contexto do modelo


def run(source_id: int) -> str:
    """
    source_id: ID da fonte a ler (use list_sources para descobrir os IDs)
    """
    try:
        source = get_source(source_id)
        if not source:
            return f"Erro: fonte com id={source_id} não encontrada."

        chunks = get_chunks(source_id)
        if not chunks:
            return f"Erro: fonte '{source['filename']}' não tem chunks indexados."

        texto_completo = "\n\n".join(c["content"] for c in chunks)

        cabecalho = (
            f"[FONTE: {source['filename']} | "
            f"{source['n_chunks']} chunks | "
            f"sessão: {source['session_id']}]\n"
            f"{'─' * 40}\n"
        )

        if len(texto_completo) > MAX_CHARS:
            texto_completo = (
                texto_completo[:MAX_CHARS]
                + f"\n\n[... truncado após {MAX_CHARS} caracteres ...]"
            )

        return cabecalho + texto_completo
    except Exception as e:
        return f"Erro ao ler fonte: {e}"

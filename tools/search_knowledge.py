"""Busca trechos relevantes nas fontes indexadas do agente (RAG)."""

from knowledge.retriever import search_formatted


def run(query: str, agent_id: str = "general", session_id: str = "", top_k: int = 5) -> str:
    """
    query:      o que buscar nas fontes indexadas
    agent_id:   ID do agente atual (vem do system prompt)
    session_id: ID da sessão atual (vem do system prompt)
    top_k:      número máximo de trechos a retornar (padrão: 5)
    """
    try:
        sid = session_id.strip() if session_id.strip() else None
        return search_formatted(
            query      = query,
            agent_id   = agent_id,
            session_id = sid,
            top_k      = max(1, min(top_k, 10)),
        )
    except Exception as e:
        return f"Erro ao buscar nas fontes: {e}"
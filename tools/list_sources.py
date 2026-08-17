"""Lista as fontes indexadas disponíveis para o agente na sessão atual."""

from knowledge.db import list_sources as db_list_sources


def run(agent_id: str = "general", session_id: str = "") -> str:
    """
    agent_id:   ID do agente atual (vem do system prompt)
    session_id: ID da sessão atual (vem do system prompt)
    """
    try:      
        sid = session_id.strip() if session_id.strip() else None
        sources = db_list_sources(agent_id=agent_id, session_id=sid)

        if not sources:
            return "Nenhuma fonte indexada encontrada."

        linhas = [f"{len(sources)} fonte(s) disponível(is):\n"]
        for s in sources:
            escopo = "compartilhada" if s["session_id"] == "_shared" else "desta sessão"
            linhas.append(
                f"[id={s['id']}] {s['filename']}  "
                f"({s['n_chunks']} chunks · {escopo})"
            )
            if s.get("summary"):
                resumo = s["summary"][:120].replace("\n", " ")
                linhas.append(f"  ↳ {resumo}…")

        return "\n".join(linhas)
    except Exception as e:
        return f"Erro ao listar fontes: {e}"
"""
multitask/report.py — mensagem final de uma execução multitask.

A Fase 1 monta o relatório de forma **determinística** a partir do quadro:
o que foi feito, artefatos, decisões, falhas e pendências. Nada inventa
resultado e nada depende de o modelo lembrar do que aconteceu.

O formato vem de `board.entrega["formato"]` (definido no fluxo):

    markdown  → relatório completo (default)
    resumo    → parágrafo + lista curta
    whatsapp  → negrito/bullets, sem headers nem tabelas
    bullets   → lista simples

Um reporter LLM (Fase 3) pode ser plugado depois; o fallback determinístico
continua sendo este.
"""

from __future__ import annotations

from board import (
    RUN_CANCELADA,
    RUN_CONCLUIDA,
    RUN_CRIADA,
    RUN_EM_ANDAMENTO,
    RUN_FALHOU,
    RUN_PAUSADA,
    TASK_BLOQUEADA,
    TASK_CONCLUIDA,
    TASK_EM_ANDAMENTO,
    TASK_FALHOU,
    TASK_PENDENTE,
    TASK_PULADA,
    Board,
)

_FORMATOS = {"markdown", "md", "resumo", "whatsapp", "bullets", "lista"}

_STATUS_LABEL = {
    RUN_CONCLUIDA: "concluída",
    RUN_FALHOU: "falhou",
    RUN_PAUSADA: "pausada",
    RUN_CANCELADA: "cancelada",
    RUN_EM_ANDAMENTO: "em andamento",
    RUN_CRIADA: "criada",
}

_TASK_ICON = {
    TASK_CONCLUIDA: "✅",
    TASK_FALHOU: "✗",
    TASK_PENDENTE: "○",
    TASK_EM_ANDAMENTO: "▶",
    TASK_PULADA: "↷",
    TASK_BLOQUEADA: "⛔",
}

_MAX_WHATSAPP = 3500


# ── helpers ───────────────────────────────────────────────────────────────

def _one_line(text: str, limit: int = 300) -> str:
    text = (text or "").strip().replace("\r", " ").replace("\n", " ")
    while "  " in text:
        text = text.replace("  ", " ")
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _status(board: Board) -> str:
    return _STATUS_LABEL.get(board.status, board.status)


def _progress(board: Board) -> str:
    progress = board.progress()
    parts = [f"{progress['concluidas']}/{progress['total']} tasks"]
    if progress["falhas"]:
        parts.append(f"{progress['falhas']} falha(s)")
    if progress["pendentes"]:
        parts.append(f"{progress['pendentes']} pendente(s)")
    return " · ".join(parts)


def _duration(board: Board) -> str:
    try:
        seconds = float(board.meta.get("duracao_s") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        return ""
    minutes, rest = divmod(int(seconds), 60)
    if minutes:
        return f"{minutes}m {rest:02d}s"
    return f"{rest}s"


def _tokens(board: Board) -> str:
    try:
        tokens_in = int(board.meta.get("tokens_in") or 0)
        tokens_out = int(board.meta.get("tokens_out") or 0)
    except (TypeError, ValueError):
        tokens_in, tokens_out = board.total_tokens()
    if not (tokens_in or tokens_out):
        tokens_in, tokens_out = board.total_tokens()
    total = tokens_in + tokens_out
    if not total:
        return ""
    if total >= 1000:
        return f"{total / 1000:.1f}k tokens"
    return f"{total} tokens"


def _artifacts(task, *, code: bool = True, limit: int = 8) -> str:
    paths = [str(item.get("path", "")) for item in task.artefatos if item.get("path")]
    if not paths:
        return ""
    shown = paths[:limit]
    rest = len(paths) - len(shown)
    if code:
        formatted = ", ".join(f"`{path}`" for path in shown)
    else:
        formatted = ", ".join(shown)
    if rest > 0:
        formatted += f" (+{rest})"
    return formatted


def _decisions(task, limit: int = 4) -> str:
    decisions = [str(item) for item in task.decisoes if str(item).strip()]
    if not decisions:
        return ""
    shown = decisions[:limit]
    suffix = f" (+{len(decisions) - len(shown)})" if len(decisions) > len(shown) else ""
    return "; ".join(shown) + suffix


def _failed_tasks(board: Board) -> list:
    return [t for t in board.tasks() if t.status == TASK_FALHOU]


def _pending_tasks(board: Board) -> list:
    return [
        t for t in board.tasks()
        if t.status in (TASK_PENDENTE, TASK_EM_ANDAMENTO, TASK_BLOQUEADA)
    ]


def _done_tasks(board: Board) -> list:
    return [
        t for t in board.tasks()
        if t.status in (TASK_CONCLUIDA, TASK_PULADA)
    ]


def _header_facts(board: Board) -> str:
    facts = [_status(board), _progress(board)]
    tokens = _tokens(board)
    if tokens:
        facts.append(tokens)
    duration = _duration(board)
    if duration:
        facts.append(duration)
    corrections = sum(int(t.correcoes or 0) for t in board.tasks())
    if corrections:
        label = "correção" if corrections == 1 else "correções"
        facts.append(f"{corrections} {label}")
    return " · ".join(facts)


# ── formatos ──────────────────────────────────────────────────────────────

def _markdown(board: Board) -> str:
    lines = [f"## Multitask — {_one_line(board.objetivo, 200)}", ""]
    lines.append(f"**Status:** {_header_facts(board)}")
    lines.append("")
    if board.fluxo:
        lines.append(
            f"**Fluxo:** {board.fluxo}  ·  **run:** `{board.id}`"
        )
        lines.append("")

    lines.append("### O que foi feito")
    done = _done_tasks(board)
    if not done:
        lines.append("_Nenhuma task concluída._")
    else:
        for phase in board.fases:
            done_phase = [
                t for t in phase.tasks
                if t.status in (TASK_CONCLUIDA, TASK_PULADA)
            ]
            if not done_phase:
                continue
            lines.append(f"**{phase.nome}**")
            for task in done_phase:
                resumo = _one_line(task.resumo) or "(sem resumo)"
                icon = _TASK_ICON.get(task.status, "✅")
                lines.append(f"- {icon} **{task.titulo}** — {resumo}")
                artifacts = _artifacts(task)
                if artifacts:
                    lines.append(f"  - arquivos: {artifacts}")
                decisions = _decisions(task)
                if decisions:
                    lines.append(f"  - decisões: {decisions}")
                if task.checagem_ok is not None:
                    icon = "✓" if task.checagem_ok else "✗"
                    lines.append(
                        f"  - verificação: {icon} {_one_line(task.checagem_resumo, 200)}"
                    )
                if task.correcoes:
                    lines.append(f"  - correções: {task.correcoes}")
            lines.append("")
    lines.append("")

    failed = _failed_tasks(board)
    if failed:
        lines.append("### Falhas")
        for task in failed:
            erro = _one_line(task.erro or task.resumo, 300) or "erro não registrado"
            lines.append(f"- ✗ **{task.titulo}** — {erro}")
        lines.append("")

    pending = _pending_tasks(board)
    if pending:
        lines.append("### Pendências")
        for task in pending:
            lines.append(f"- {_TASK_ICON.get(task.status, '○')} **{task.titulo}** ({task.status})")
        lines.append("")

    como_testar = (board.entrega or {}).get("como_testar", "")
    if como_testar:
        lines.append("### Como testar")
        lines.append(str(como_testar))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _whatsapp(board: Board) -> str:
    lines = [
        f"*Multitask — {_one_line(board.objetivo, 120)}*",
        f"_{_header_facts(board)}_",
        "",
    ]

    done = _done_tasks(board)
    if done:
        for task in done:
            resumo = _one_line(task.resumo, 160) or "(sem resumo)"
            icon = _TASK_ICON.get(task.status, "✅")
            lines.append(f"{icon} *{task.titulo}*: {resumo}")
    else:
        lines.append("_Nenhuma task concluída._")

    failed = _failed_tasks(board)
    for task in failed:
        erro = _one_line(task.erro or task.resumo, 160) or "erro"
        lines.append(f"⚠️ *{task.titulo}*: {erro}")

    pending = _pending_tasks(board)
    if pending:
        lines.append("")
        for task in pending:
            lines.append(f"○ *{task.titulo}* ({task.status})")

    paths = [
        str(item.get("path", ""))
        for task in done for item in task.artefatos
        if item.get("path")
    ]
    if paths:
        lines.append("")
        lines.append("📁 " + ", ".join(paths[:8]))

    como_testar = (board.entrega or {}).get("como_testar", "")
    if como_testar:
        lines.append(f"▶️ {como_testar}")

    text = "\n".join(lines).strip()
    if len(text) > _MAX_WHATSAPP:
        text = text[: _MAX_WHATSAPP - 1].rstrip() + "…"
    return text + "\n"


def _resumo(board: Board) -> str:
    progress = board.progress()
    lines = [
        f'Concluí {progress["concluidas"]} de {progress["total"]} tasks de '
        f'"{_one_line(board.objetivo, 120)}" ({_status(board)}).'
    ]

    for task in _done_tasks(board):
        resumo = _one_line(task.resumo, 160) or "(sem resumo)"
        icon = _TASK_ICON.get(task.status, "✅")
        lines.append(f"- {icon} {task.titulo}: {resumo}")

    for task in _failed_tasks(board):
        erro = _one_line(task.erro or task.resumo, 160) or "erro"
        lines.append(f"- ✗ {task.titulo}: {erro}")

    pending = _pending_tasks(board)
    if pending:
        lines.append(
            "- pendentes: " + ", ".join(task.titulo for task in pending)
        )

    return "\n".join(lines).strip() + "\n"


def _bullets(board: Board) -> str:
    lines = [
        f"- **Status:** {_header_facts(board)}",
    ]
    for task in _done_tasks(board):
        resumo = _one_line(task.resumo, 200) or "(sem resumo)"
        icon = _TASK_ICON.get(task.status, "✅")
        lines.append(f"- {icon} **{task.titulo}** — {resumo}")
        artifacts = _artifacts(task)
        if artifacts:
            lines.append(f"  - arquivos: {artifacts}")
        if task.checagem_ok is not None:
            check_icon = "✓" if task.checagem_ok else "✗"
            lines.append(
                f"  - verificação: {check_icon} {_one_line(task.checagem_resumo, 160)}"
            )
        if task.correcoes:
            lines.append(f"  - correções: {task.correcoes}")
    for task in _failed_tasks(board):
        erro = _one_line(task.erro or task.resumo, 200) or "erro"
        lines.append(f"- ✗ **{task.titulo}** — {erro}")
    for task in _pending_tasks(board):
        lines.append(f"- ○ **{task.titulo}** ({task.status})")

    como_testar = (board.entrega or {}).get("como_testar", "")
    if como_testar:
        lines.append(f"- **Como testar:** {como_testar}")
    return "\n".join(lines).strip() + "\n"


# ── API ───────────────────────────────────────────────────────────────────

def build_report(board: Board, *, formato: str | None = None) -> str:
    """Gera a mensagem final no formato pedido pelo fluxo/usuário."""
    fmt = (formato or (board.entrega or {}).get("formato") or "markdown")
    fmt = str(fmt).strip().lower()
    if fmt not in _FORMATOS:
        fmt = "markdown"

    if fmt in ("whatsapp",):
        return _whatsapp(board)
    if fmt in ("resumo",):
        return _resumo(board)
    if fmt in ("bullets", "lista"):
        return _bullets(board)
    return _markdown(board)


__all__ = ["build_report"]

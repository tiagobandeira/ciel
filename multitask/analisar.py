"""Análise de uma execução do multitask (quadro + métricas)."""

from __future__ import annotations

from dataclasses import dataclass

from board import (
    TASK_CONCLUIDA,
    TASK_FALHOU,
    TASK_PENDENTE,
    TASK_PULADA,
    Board,
)
from llm.client import ChatResult

_SYSTEM = """Você é o analista de execução do Ciel.

Recebe o quadro de uma execução (tasks, status, checks e métricas de custo).
Não execute tools, não altere o quadro. Responda em Markdown curto e direto:

## O que funcionou
## Riscos e falhas
## Próximo passo

Cite nomes de tasks e números de tokens quando ajudarem. Não repita o log
inteiro; foque no que o usuário deve saber.
"""


@dataclass
class AnalysisResult:
    texto: str
    tokens_in: int = 0
    tokens_out: int = 0
    usou_modelo: bool = False


def _status_counts(board: Board) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in board.tasks():
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def _context(board: Board) -> str:
    lines = [
        f"Objetivo: {board.objetivo}",
        f"Status: {board.status}",
        f"Perfil: {board.perfil} · fluxo: {board.fluxo or '-'}",
        f"Tokens: {board.meta.get('tokens_in', 0)} in / "
        f"{board.meta.get('tokens_out', 0)} out",
        "",
    ]
    for phase in board.fases:
        lines.append(f"## {phase.nome}")
        for task in phase.tasks:
            lines.append(
                f"- {task.id} [{task.status}] {task.titulo} | "
                f"resumo: {task.resumo or '-'} | erro: {task.erro or '-'} | "
                f"checks: {task.checagem_resumo or '-'} | "
                f"tokens: {task.tokens_in}/{task.tokens_out}"
            )
    metricas = board.meta.get("metricas") or {}
    if metricas:
        lines.append("")
        lines.append("Métricas por task:")
        for task_id, data in metricas.items():
            lines.append(f"- {task_id}: {data}")
    return "\n".join(lines)


def _fallback(board: Board) -> str:
    counts = _status_counts(board)
    falhas = [t for t in board.tasks() if t.status == TASK_FALHOU]
    pendentes = [t for t in board.tasks() if t.status == TASK_PENDENTE]
    puladas = [t for t in board.tasks() if t.status == TASK_PULADA]
    feitas = [t for t in board.tasks() if t.status == TASK_CONCLUIDA]

    lines = [
        f"# Análise — {board.objetivo}",
        "",
        f"**Status:** {board.status} · "
        f"{counts.get(TASK_CONCLUIDA, 0)} concluída(s), "
        f"{counts.get(TASK_FALHOU, 0)} falha(s), "
        f"{counts.get(TASK_PENDENTE, 0)} pendente(s), "
        f"{counts.get(TASK_PULADA, 0)} pulada(s)",
        "",
        "## O que funcionou",
    ]
    if feitas:
        lines += [f"- {t.id}: {t.titulo} — {t.resumo or 'concluída'}" for t in feitas]
    else:
        lines.append("- Nenhuma task concluída ainda.")
    lines.append("")
    lines.append("## Riscos e falhas")
    if falhas:
        lines += [
            f"- {t.id}: {t.titulo} — {t.erro or t.checagem_resumo or 'falhou'}"
            for t in falhas
        ]
    elif pendentes:
        lines.append("- Nenhuma falha; há tasks pendentes.")
    else:
        lines.append("- Nenhuma falha registrada.")
    lines.append("")
    lines.append("## Próximo passo")
    if falhas:
        lines.append(
            "- Corrigir a primeira falha pelo id e retomar a execução; "
            "o contexto da task está no quadro."
        )
    elif pendentes:
        lines.append("- Retomar/continuar as tasks pendentes.")
    else:
        lines.append("- Revisar a entrega e testar o artefato final.")
    if puladas:
        lines.append(
            "- Conferir se as tasks puladas eram realmente idempotentes."
        )
    return "\n".join(lines)


def analyze_board(
    board: Board,
    client=None,
    *,
    model: str = "",
    max_tokens: int = 1200,
) -> AnalysisResult:
    """Analisa o quadro; usa o modelo se houver cliente, senão é determinístico."""
    if client is None:
        return AnalysisResult(_fallback(board), usou_modelo=False)

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _context(board)},
    ]
    try:
        result: ChatResult = client.chat(
            messages, model=model or None, temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception:
        return AnalysisResult(_fallback(board), usou_modelo=False)

    texto = (result.text or "").strip()
    if not texto:
        return AnalysisResult(
            _fallback(board),
            tokens_in=int(result.tokens_in or 0),
            tokens_out=int(result.tokens_out or 0),
            usou_modelo=False,
        )
    return AnalysisResult(
        texto,
        tokens_in=int(result.tokens_in or 0),
        tokens_out=int(result.tokens_out or 0),
        usou_modelo=True,
    )

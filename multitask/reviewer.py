"""Revisão de fase do multitask: o secundário ajusta tasks pendentes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from board import (
    TASK_PENDENTE,
    TASK_PULADA,
    Board,
)
from llm.client import ChatResult

MAX_CHANGES = 10

_SYSTEM = """Você é o revisor de fase do Ciel.

Recebe o quadro de uma execução, o resultado das tasks concluídas e as tasks
pendentes. Seu papel é ajustar o plano, não executar tools nem reescrever o
que já foi concluído.

Responda APENAS com JSON puro:
{
  "resumo": "frase curta sobre o estado da fase",
  "changes": [
    {"tipo": "adicionar", "titulo": "...", "objetivo": "...",
     "acoes": ["..."], "resultado_esperado": "...", "checagem": [...],
     "agente": "", "tools": [], "max_steps": 5, "depende_de": []},
    {"tipo": "atualizar", "task_id": "t3",
     "campos": {"objetivo": "...", "acoes": ["..."], "checagem": [...]}},
    {"tipo": "pular", "task_id": "t4", "motivo": "já coberta por outra task"},
    {"tipo": "reordenar", "ordem": ["t3", "t4"]}
  ]
}

Regras:
- nunca altere task concluída, falha ou em andamento;
- no máximo 10 mudanças;
- prefira não mudar nada se a fase está coerente;
- `checagem` deve ser verificável (arquivo, comando, http, json);
- não invente caminhos fora do workspace.
"""


@dataclass
class ReviewResult:
    resumo: str = ""
    applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    raw: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _phase_payload(board: Board, phase: str, available_tools: set[str] | None = None) -> str:
    lines = [
        f"Objetivo geral: {board.objetivo}",
        f"Fase em revisão: {phase}",
        "",
        "Quadro completo:",
    ]
    for phase_state in board.fases:
        marker = " (fase atual)" if phase_state.nome == phase else ""
        lines.append(f"## {phase_state.nome}{marker}")
        for task in phase_state.tasks:
            lines.append(
                f"- {task.id} [{task.status}] {task.titulo} | "
                f"objetivo: {task.objetivo or '(sem objetivo)'} | "
                f"check: {task.checagem!r} | resumo: {task.resumo or '-'}"
            )
    if available_tools:
        lines.append("")
        lines.append(
            "Tools reais disponíveis (use só estes nomes): "
            + ", ".join(sorted(available_tools))
        )
    return "\n".join(lines)


def _clean_tools(value, available_tools: set[str] | None):
    incoming = [str(t) for t in value or []]
    if available_tools is None:
        return incoming or None
    valid = [t for t in incoming if t in available_tools]
    return valid or None


def _apply_changes(
    board: Board,
    phase: str,
    changes: list,
    available_tools: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    applied: list[str] = []
    errors: list[str] = []
    if not isinstance(changes, list):
        return [], ["'changes' não é uma lista"]

    for index, change in enumerate(changes[:MAX_CHANGES], start=1):
        if not isinstance(change, dict):
            errors.append(f"mudança {index}: não é objeto")
            continue
        kind = str(change.get("tipo") or "").lower()
        if kind == "adicionar":
            titulo = str(change.get("titulo") or "").strip()
            if not titulo:
                errors.append(f"mudança {index}: titulo vazio")
                continue
            board.add_task(
                phase,
                titulo,
                objetivo=str(change.get("objetivo") or ""),
                acoes=[str(a) for a in change.get("acoes") or []],
                resultado_esperado=str(change.get("resultado_esperado") or ""),
                checagem=change.get("checagem"),
                agente=str(change.get("agente") or ""),
                tools=_clean_tools(change.get("tools"), available_tools),
                max_steps=int(change.get("max_steps") or 0),
                depende_de=[str(d) for d in change.get("depende_de") or []],
            )
            applied.append(f"adicionada: {titulo}")
        elif kind == "atualizar":
            task = board.task(str(change.get("task_id") or ""))
            if task is None or task.status != TASK_PENDENTE:
                errors.append(f"mudança {index}: task pendente não encontrada")
                continue
            fields = change.get("campos") or {}
            if not isinstance(fields, dict):
                errors.append(f"mudança {index}: 'campos' inválido")
                continue
            for field_name in (
                "objetivo", "acoes", "resultado_esperado", "checagem",
                "agente", "tools", "max_steps",
            ):
                if field_name not in fields:
                    continue
                value = fields[field_name]
                if field_name == "acoes":
                    value = [str(a) for a in value or []]
                elif field_name in ("tools",):
                    value = _clean_tools(value, available_tools)
                elif field_name == "max_steps":
                    try:
                        value = int(value or 0)
                    except (TypeError, ValueError):
                        value = 0
                elif field_name == "checagem":
                    value = value
                setattr(task, field_name, value)
            applied.append(f"atualizada: {task.id}")
        elif kind == "pular":
            task = board.task(str(change.get("task_id") or ""))
            if task is None or task.status != TASK_PENDENTE:
                errors.append(f"mudança {index}: task pendente não encontrada")
                continue
            task.status = TASK_PULADA
            task.resumo = str(change.get("motivo") or "pulada pelo revisor")
            applied.append(f"pulada: {task.id}")
        elif kind == "reordenar":
            ordem = change.get("ordem")
            phase_state = board.phase(phase)
            if phase_state is None or not isinstance(ordem, list):
                errors.append(f"mudança {index}: reordenação inválida")
                continue
            ids = [str(x) for x in ordem]
            selected = [
                t for t in phase_state.tasks
                if t.id in ids and t.status == TASK_PENDENTE
            ]
            selected_ids = {t.id for t in selected}
            rest = [t for t in phase_state.tasks if t.id not in selected_ids]
            phase_state.tasks = selected + rest
            applied.append("reordenada: " + ", ".join(ids))
        else:
            errors.append(f"mudança {index}: tipo inválido {kind!r}")

    return applied, errors


def review_phase(
    board: Board,
    phase: str,
    client,
    *,
    model: str = "",
    max_tokens: int = 1200,
    available_tools: set[str] | None = None,
) -> ReviewResult:
    """Pede ao secundário uma revisão da fase e aplica ajustes pendentes."""
    if client is None:
        return ReviewResult(errors=["revisor sem cliente de modelo"])
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": _phase_payload(board, phase, available_tools),
        },
    ]
    try:
        result: ChatResult = client.chat(
            messages, model=model or None, temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        return ReviewResult(errors=[f"falha no revisor: {exc}"])
    raw = result.text or ""
    data = _extract_json(raw)
    if data is None:
        return ReviewResult(
            errors=["resposta do revisor não é JSON válido"],
            tokens_in=int(result.tokens_in or 0),
            tokens_out=int(result.tokens_out or 0),
            raw=raw,
        )

    resumo = str(data.get("resumo") or "")
    applied, errors = _apply_changes(
        board, phase, data.get("changes") or [], available_tools,
    )
    return ReviewResult(
        resumo=resumo,
        applied=applied,
        errors=errors,
        tokens_in=int(result.tokens_in or 0),
        tokens_out=int(result.tokens_out or 0),
        raw=raw,
    )

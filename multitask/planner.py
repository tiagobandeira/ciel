"""
multitask/planner.py — planejador do modo multitask.

Na Fase 3 o objetivo livre (`/multitask <objetivo>`) passa a virar plano:
o modelo do papel `planner` recebe o objetivo, o orçamento, as tools e os
agentes disponíveis, e devolve um JSON de fases/tasks.

O harness **valida por código** antes de executar e, se o plano for
inválido, devolve os erros ao modelo para ele corrigir — até
`orcamento.max_replans + 1` tentativas. O modelo nunca decide sozinho se o
plano está bom.

O plano não roda nada aqui: `generate_board()` devolve um `Board` pronto
para o `multitask.runner` (ou uma lista de erros).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from agent_loader import list_agents, load_agent
from board import Board, BoardError, default_orcamento
from llm.client import ChatResult
from llm.roles import RoleConfig
from multitask.checks import validate_check_spec
from multitask.flow import VALID_FORMATS, detect_format

DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "planejamento.md"
)
MAX_ACTIONS_PER_TASK = 6
MAX_PLAN_ATTEMPTS = 5
DEFAULT_MAX_TOKENS = 8192
MAX_STEPS_PER_TASK = 20

TOOLS_LEITURA = ["read_file", "list_directory", "search_files"]
TOOLS_ESCRITA = [
    "read_file", "write_file", "edit_file", "list_directory", "create_directory",
]
TOOLS_CODIGO = TOOLS_ESCRITA + ["run_script"]

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_EMPTY_AGENT = {"", "none", "nenhum", "-"}
_FOLDER_WORDS = (
    "criar pasta", "criar a pasta", "criar diretório", "criar diretorio",
    "mkdir", "nova pasta", "criar diretórios", "criar diretorios",
)


def _file_check_on_folder(check: Any, task_text: str) -> bool:
    """Heurística: task que cria pasta usando checagem de arquivo sem extensão."""
    text = (task_text or "").lower()
    if not any(word in text for word in _FOLDER_WORDS):
        return False

    def visit(value: Any) -> bool:
        if isinstance(value, list):
            return any(visit(item) for item in value)
        if not isinstance(value, dict):
            return False
        tipo = str(value.get("tipo") or value.get("type") or "").lower()
        if tipo not in ("arquivo", "file", "file_exists", "existe"):
            return False
        path = str(
            value.get("path")
            or value.get("caminho")
            or value.get("arquivo")
            or ""
        )
        return bool(path) and Path(path).suffix == ""

    return visit(check)


class PlannerUnavailable(Exception):
    """Não há modelo de planejamento configurado."""


@dataclass
class PlanResult:
    """Resultado de uma tentativa de planejamento."""

    board: Board | None
    errors: list[str] = field(default_factory=list)
    attempts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    raw: str = ""
    model: str = ""

    @property
    def ok(self) -> bool:
        return self.board is not None and not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "attempts": self.attempts,
            "errors": list(self.errors),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "model": self.model,
        }


# ── helpers ───────────────────────────────────────────────────────────────

def _load_prompt(path: str | Path | None = None) -> str:
    prompt_path = Path(path) if path else DEFAULT_PROMPT_PATH
    if not prompt_path.exists():
        raise PlannerUnavailable(
            f"prompt de planejamento não encontrado: {prompt_path}"
        )
    return prompt_path.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict | None:
    """Extrai o primeiro objeto JSON válido, tolerando fences/prosa."""
    text = (text or "").strip()
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text).strip()

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass

    start = text.find("{")
    if start < 0:
        return None

    for end in sorted(
        (m.start() for m in re.finditer(r"\}", text)), reverse=True
    ):
        if end <= start:
            continue
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _one_line(text: Any, limit: int = 100) -> str:
    value = str(text or "").strip().replace("\n", " ")
    while "  " in value:
        value = value.replace("  ", " ")
    return value[:limit]


def _normalize_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return None
    return [str(item).strip() for item in value if str(item).strip()]


def _default_tools(actions: list[str], check: Any) -> list[str]:
    """Preset de tools quando o planner não declara `tools` explicitamente."""
    text = " ".join(actions).lower()
    check_text = str(check or "").lower()
    if (
        "test" in text or "test" in check_text
        or "script" in text or "comando" in check_text
        or "pytest" in text
    ):
        return list(TOOLS_CODIGO)
    if any(
        word in text
        for word in ("escrev", "criar", "editar", "corrig", "implement", "gerar")
    ):
        return list(TOOLS_ESCRITA)
    return list(TOOLS_LEITURA)


def _format_tools(tools: dict | None, limit: int = 80) -> str:
    if not tools:
        return "(nenhuma tool informada)"
    lines: list[str] = []
    for name in sorted(tools):
        meta = tools.get(name) or {}
        description = _one_line(meta.get("description", ""), 90)
        lines.append(f"- {name}: {description}" if description else f"- {name}")
        if len(lines) >= limit:
            lines.append(f"- … (+{len(tools) - limit} tools)")
            break
    return "\n".join(lines)


def _format_agents(limit: int = 20) -> str:
    lines: list[str] = []
    for name in list_agents():
        try:
            info = load_agent(name)
            description = _one_line(info.get("description", ""), 100)
        except Exception:
            description = ""
        lines.append(f"- {name}: {description}" if description else f"- {name}")
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else "(nenhum agente encontrado)"


def _user_prompt(
    objetivo: str,
    *,
    orcamento: dict,
    tools: dict | None,
    formato_sugerido: str,
    feedback: str,
) -> str:
    max_tasks = orcamento.get("max_tasks", 20)
    max_corr = orcamento.get("max_correcoes_por_task", 3)

    lines = [
        "## Objetivo do usuário",
        objetivo,
        "",
        "## Contexto",
        f"Data/hora: {datetime.now().astimezone().isoformat(timespec='minutes')}",
        f"Formato sugerido pela fala do usuário: {formato_sugerido or 'markdown'}",
        f"Orçamento: no máximo {max_tasks} tasks no total; "
        f"até {max_corr} correções por task.",
        "",
        "## Agentes disponíveis",
        _format_agents(),
        "",
        "## Tools disponíveis no executor",
        _format_tools(tools),
    ]

    if feedback.strip():
        lines += [
            "",
            "## Ajuste pedido na aprovação do plano",
            feedback.strip(),
            "Gere o plano inteiro de novo incorporando esse ajuste.",
        ]

    lines += [
        "",
        "Gere o plano completo agora. Responda somente com o JSON, "
        "sem markdown e sem explicação.",
    ]
    return "\n".join(lines)


# ── validação do plano ────────────────────────────────────────────────────

def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def parse_plan(
    data: dict,
    *,
    objetivo_usuario: str,
    orcamento: dict | None = None,
    formato_sugerido: str = "",
) -> tuple[Board | None, list[str]]:
    """
    Valida o JSON do planejador e monta o `Board`.

    Retorna (board, []) em sucesso ou (None, erros) para o harness devolver
    ao modelo. Nunca executa nada.
    """
    if not isinstance(data, dict):
        return None, ["plano não é um objeto JSON"]

    orcamento = dict(orcamento or default_orcamento())
    objective = str(data.get("objetivo") or objetivo_usuario or "").strip()
    if not objective:
        return None, ["plano sem objetivo"]

    entrega_raw = data.get("entrega")
    if not isinstance(entrega_raw, dict):
        entrega_raw = {}

    formato = str(
        entrega_raw.get("formato")
        or data.get("formato")
        or formato_sugerido
        or "markdown"
    ).strip().lower()
    if formato not in VALID_FORMATS:
        formato = "markdown"

    como_testar = (
        entrega_raw.get("como_testar")
        or entrega_raw.get("como testar")
        or data.get("como_testar")
        or ""
    )

    board = Board.new(
        objective,
        fluxo="plano",
        perfil="",                       # herda local/build do config
        entrega={
            "formato": formato,
            "como_testar": str(como_testar),
        },
        orcamento=orcamento,
        meta={"planner": True},
    )

    phases = data.get("fases") or data.get("phases")
    if not isinstance(phases, list) or not phases:
        return None, ["'fases' deve ser uma lista não vazia"]

    errors: list[str] = []
    seen_ids: set[str] = set()
    title_to_id: dict[str, str] = {}
    next_id = 1

    def _new_id() -> str:
        nonlocal next_id
        while f"t{next_id}" in seen_ids:
            next_id += 1
        value = f"t{next_id}"
        next_id += 1
        return value

    for phase_index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            errors.append(f"fase[{phase_index}] não é um objeto")
            continue

        phase_name = str(
            phase.get("nome") or phase.get("name") or ""
        ).strip() or "geral"

        tasks = phase.get("tasks") or phase.get("tarefas")
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"fase '{phase_name}' sem tasks")
            continue

        for task_index, task in enumerate(tasks):
            task_errors: list[str] = []

            if not isinstance(task, dict):
                errors.append(
                    f"fase '{phase_name}' task[{task_index}] não é um objeto"
                )
                continue

            task_id = str(task.get("id") or "").strip() or _new_id()
            if not _ID_RE.match(task_id):
                errors.append(
                    f"task id inválido: {task_id!r} "
                    f"(use letras/números/_/-, começando por letra)"
                )
                continue
            if task_id in seen_ids:
                errors.append(f"task id duplicado: {task_id}")
                continue

            title = str(
                task.get("titulo") or task.get("nome") or task.get("title") or ""
            ).strip()
            if not title:
                task_errors.append(f"task {task_id}: sem 'titulo'")

            task_objetivo = str(
                task.get("objetivo") or task.get("objective") or ""
            ).strip()

            actions = _normalize_list(task.get("acoes") or task.get("actions"))
            if actions is None:
                task_errors.append(f"task {task_id}: 'acoes' deve ser lista")
                actions = []
            if not actions:
                task_errors.append(f"task {task_id}: sem ações")
            elif len(actions) > MAX_ACTIONS_PER_TASK:
                task_errors.append(
                    f"task {task_id}: {len(actions)} ações "
                    f"(máximo {MAX_ACTIONS_PER_TASK})"
                )

            expected = str(
                task.get("resultado_esperado")
                or task.get("resultado")
                or task.get("expected_result")
                or ""
            ).strip()
            if not expected:
                task_errors.append(
                    f"task {task_id}: sem 'resultado_esperado' verificável"
                )

            if "checagem" in task:
                check = task.get("checagem")
            else:
                check = task.get("check")
            for check_error in validate_check_spec(check):
                task_errors.append(f"task {task_id}: {check_error}")

            task_text = f"{title} {' '.join(actions)}"
            if _file_check_on_folder(check, task_text):
                task_errors.append(
                    f"task {task_id}: task de criar pasta com checagem "
                    f"tipo 'arquivo' — use 'diretorio' para pastas"
                )

            agent = str(task.get("agente") or task.get("agent") or "").strip()
            if agent.lower() in _EMPTY_AGENT:
                agent = ""
            if agent:
                try:
                    load_agent(agent)
                except Exception:
                    task_errors.append(f"task {task_id}: agente '{agent}' não existe")

            deps_raw = _normalize_list(
                task.get("depende_de")
                if "depende_de" in task
                else task.get("depends_on")
            )
            if deps_raw is None:
                task_errors.append(
                    f"task {task_id}: 'depende_de' deve ser lista"
                )
                deps_raw = []

            deps: list[str] = []
            for dep in deps_raw:
                resolved = dep if dep in seen_ids else title_to_id.get(dep)
                if resolved is None or resolved not in seen_ids:
                    task_errors.append(
                        f"task {task_id}: dependência '{dep}' inválida "
                        f"(use o id de uma task anterior)"
                    )
                else:
                    deps.append(resolved)

            tools_raw = _normalize_list(task.get("tools"))
            if tools_raw is None:
                task_errors.append(f"task {task_id}: 'tools' deve ser lista")
                tools_raw = []
            if not tools_raw:
                tools_raw = _default_tools(actions, check)

            max_steps_raw = task.get("max_steps", task.get("steps"))
            try:
                task_max_steps = int(max_steps_raw or 0)
            except (TypeError, ValueError):
                task_errors.append(f"task {task_id}: 'max_steps' deve ser inteiro")
                task_max_steps = 0
            if task_max_steps < 0 or task_max_steps > MAX_STEPS_PER_TASK:
                task_errors.append(
                    f"task {task_id}: max_steps fora de 0..{MAX_STEPS_PER_TASK}"
                )

            pular_se_ok = bool(task.get("pular_se_ok") or False)
            parallel = bool(task.get("parallel") or task.get("paralelo") or False)
            task_model = str(task.get("modelo") or task.get("model") or "")
            read_only = bool(task.get("read_only") or False)

            if task_errors:
                errors.extend(task_errors)
                continue

            try:
                board.add_task(
                    phase_name,
                    title,
                    objetivo=task_objetivo,
                    acoes=actions,
                    resultado_esperado=expected,
                    checagem=check,
                    agente=agent,
                    tools=tools_raw,
                    max_steps=task_max_steps,
                    pular_se_ok=pular_se_ok,
                    parallel=parallel,
                    modelo=task_model,
                    read_only=read_only,
                    depende_de=deps,
                    task_id=task_id,
                )
            except BoardError as exc:
                errors.append(f"task {task_id}: {exc}")
                continue

            seen_ids.add(task_id)
            title_to_id.setdefault(title, task_id)

    try:
        max_tasks = int(board.orcamento.get("max_tasks") or 0)
    except (TypeError, ValueError):
        max_tasks = 0
    if max_tasks > 0 and len(board.tasks()) > max_tasks:
        errors.append(
            f"plano tem {len(board.tasks())} tasks, "
            f"acima do orçamento de {max_tasks}"
        )

    if not board.tasks():
        errors.append("plano sem tasks válidas")

    errors.extend(board.validate())
    errors = _dedupe(errors)
    if errors:
        return None, errors

    board.touch()
    return board, []


# ── chamada ao modelo ─────────────────────────────────────────────────────

def generate_board(
    objetivo: str,
    *,
    roles: RoleConfig,
    tools: dict | None = None,
    agent_info: dict | None = None,
    orcamento: dict | None = None,
    feedback: str = "",
    max_attempts: int | None = None,
    on_attempt: Callable[[int, int], None] | None = None,
    client=None,
    prompt_path: str | Path | None = None,
) -> PlanResult:
    """
    Pede um plano ao papel `planner`, valida e devolve o `Board`.

    Levanta `PlannerUnavailable` se não houver planner configurado. Erros
    de rede/parse/validação voltam em `PlanResult.errors`; o chamador só
    precisa exibir.
    """
    spec = getattr(roles, "planner", None)
    if client is None:
        if spec is None:
            raise PlannerUnavailable(
                "planejador não configurado — use /connect para configurar "
                "o modelo secundário ou /multitask <fluxo>"
            )
        client = spec.client()

    orcamento = dict(orcamento or default_orcamento())
    prompt = _load_prompt(prompt_path)
    formato_sugerido = detect_format(objetivo) or ""

    if max_attempts is None:
        try:
            replans = int(orcamento.get("max_replans", 2) or 0)
        except (TypeError, ValueError):
            replans = 2
        max_attempts = max(1, min(replans + 1, MAX_PLAN_ATTEMPTS))
    else:
        max_attempts = max(1, min(int(max_attempts), MAX_PLAN_ATTEMPTS))

    messages: list[dict] = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": _user_prompt(
                objetivo,
                orcamento=orcamento,
                tools=tools,
                formato_sugerido=formato_sugerido,
                feedback=feedback,
            ),
        },
    ]

    tokens_in = 0
    tokens_out = 0
    errors: list[str] = []
    raw = ""
    attempts = 0
    model_label = getattr(spec, "label", "") if spec is not None else ""

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        if on_attempt is not None:
            on_attempt(attempt, max_attempts)

        try:
            result: ChatResult = client.chat(
                messages,
                temperature=0.2,
                max_tokens=DEFAULT_MAX_TOKENS,
            )
        except Exception as exc:
            return PlanResult(
                None,
                [f"falha ao chamar o planejador: {exc}"],
                attempts=attempt,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model_label,
            )

        raw = result.text or ""
        tokens_in += int(result.tokens_in or 0)
        tokens_out += int(result.tokens_out or 0)

        data = _extract_json(raw)
        if data is None:
            errors = ["resposta do planejador não é um JSON válido"]
        else:
            board, errors = parse_plan(
                data,
                objetivo_usuario=objetivo,
                orcamento=orcamento,
                formato_sugerido=formato_sugerido,
            )
            if board is not None and not errors:
                return PlanResult(
                    board, [], attempts=attempt,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                    raw=raw, model=model_label,
                )

        if attempt >= max_attempts:
            break

        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": (
                "[SISTEMA] O plano anterior foi rejeitado pela validação:\n- "
                + "\n- ".join(errors)
                + "\nCorrija todos os erros e responda novamente apenas com "
                "o JSON completo do plano."
            ),
        })

    return PlanResult(
        None, errors, attempts=attempts,
        tokens_in=tokens_in, tokens_out=tokens_out,
        raw=raw, model=model_label,
    )


__all__ = [
    "PlannerUnavailable",
    "PlanResult",
    "generate_board",
    "parse_plan",
    "MAX_ACTIONS_PER_TASK",
    "DEFAULT_MAX_TOKENS",
]

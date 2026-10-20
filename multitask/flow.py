"""
multitask/flow.py — fluxos predefinidos (`flows/*.md`).

Um fluxo é o "plano escrito à mão" da Fase 1: um arquivo Markdown com um
cabeçalho e várias tasks no formato nativo (`## task:`). Ele vira um
`Board` sem passar pelo planejador (que chega na Fase 3).

Formato:

    ## flow: exemplo_site
    objetivo: criar um site estático mínimo
    perfil: local                 # opcional (local | nuvem)
    formato: markdown             # markdown | resumo | whatsapp | bullets
    como_testar: abra index.html

    ## task: estrutura
    fase: estrutura               # opcional (default: "geral")
    agente: dev_helper            # opcional (persona da task)
    objetivo: criar os arquivos
    ações:
    - criar index.html
    - criar style.css
    resultado esperado: os arquivos existem
    checagem: {"tipo": "arquivo", "path": "index.html"}
    artefatos: index.html, style.css

    ## task: conferir
    depende_de: estrutura
    ...

As dependências podem ser escritas pelo **nome** da task (`estrutura`) ou
pelo id já atribuído (`t1`); o build_board traduz nome → id e valida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from board import Board, BoardError
from llm.roles import normalize_perfil
from task_defs import load_tasks

DEFAULT_FLOWS_DIR = Path("flows")
VALID_FORMATS = {"markdown", "md", "resumo", "whatsapp", "bullets", "lista"}


class FlowError(Exception):
    """Fluxo inválido ou ausente."""


@dataclass
class Flow:
    name: str
    objetivo: str
    path: Path
    perfil: str = ""
    formato: str = "markdown"
    como_testar: str = ""
    tasks: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "objetivo": self.objetivo,
            "path": str(self.path),
            "perfil": self.perfil,
            "formato": self.formato,
            "como_testar": self.como_testar,
            "tasks": len(self.tasks),
        }


# ── parsing ───────────────────────────────────────────────────────────────

def _header(text: str) -> tuple[dict, str]:
    """Separa o cabeçalho do fluxo do bloco de tasks."""
    match = re.search(r"(?m)^##\s+task:", text)
    header_text = text[: match.start()] if match else text
    body = text[match.start():] if match else ""

    meta: dict[str, str] = {}
    for raw_line in header_text.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line or line.startswith("#") and "flow:" not in line.lower():
            continue

        low = line.lower()
        if low.startswith("## flow:") or low.startswith("# flow:"):
            meta["name"] = line.split(":", 1)[1].strip()
        elif low.startswith("objetivo:"):
            meta["objetivo"] = line.split(":", 1)[1].strip()
        elif low.startswith("perfil:"):
            meta["perfil"] = line.split(":", 1)[1].strip().lower()
        elif low.startswith("formato:"):
            meta["formato"] = line.split(":", 1)[1].strip().lower()
        elif low.startswith("como_testar:") or low.startswith("como testar:"):
            meta["como_testar"] = line.split(":", 1)[1].strip()
        elif low.startswith("idioma:"):
            meta["idioma"] = line.split(":", 1)[1].strip()
        elif low.startswith("tom:"):
            meta["tom"] = line.split(":", 1)[1].strip()

    return meta, body


def load_flow(
    source: str | Path,
    flows_dir: str | Path | None = None,
) -> Flow:
    """
    Carrega um fluxo por caminho ou por nome (sem `.md`).

    Levanta FlowError com a lista de fluxos disponíveis quando não acha.
    """
    base = Path(flows_dir) if flows_dir else DEFAULT_FLOWS_DIR
    source = Path(source)

    if source.exists() and source.is_file():
        path = source
    else:
        name = source.stem if source.suffix == ".md" else str(source)
        path = base / f"{name}.md"

    if not path.exists() or not path.is_file():
        available = [f.name for f in sorted(base.glob("*.md"))] if base.exists() else []
        hint = f" disponíveis: {available}" if available else " nenhum fluxo em flows/"
        raise FlowError(f"fluxo '{source}' não encontrado.{hint}")

    text = path.read_text(encoding="utf-8")
    meta, _ = _header(text)
    tasks = load_tasks(path)
    if not tasks:
        raise FlowError(
            f"fluxo '{path.name}' não tem nenhuma task válida "
            f"(formato esperado: '## task: nome' + 'ações:')"
        )

    name = (meta.get("name") or path.stem).strip()
    objetivo = (meta.get("objetivo") or "").strip()
    if not objetivo:
        objetivo = (tasks[0].get("objetivo") or f"executar o fluxo {name}").strip()

    formato = (meta.get("formato") or "markdown").strip().lower()
    if formato not in VALID_FORMATS:
        formato = "markdown"

    perfil_raw = (meta.get("perfil") or "").strip().lower()
    perfil = normalize_perfil(perfil_raw) if perfil_raw else ""

    return Flow(
        name=name,
        objetivo=objetivo,
        path=path,
        perfil=perfil,
        formato=formato,
        como_testar=(meta.get("como_testar") or "").strip(),
        tasks=tasks,
        meta={k: v for k, v in meta.items() if k not in (
            "name", "objetivo", "perfil", "formato", "como_testar"
        )},
    )


def list_flows(flows_dir: str | Path | None = None) -> list[dict]:
    """Lista os fluxos válidos de `flows/` (ignora arquivos quebrados)."""
    base = Path(flows_dir) if flows_dir else DEFAULT_FLOWS_DIR
    if not base.exists():
        return []

    flows: list[dict] = []
    for path in sorted(base.glob("*.md")):
        try:
            flow = load_flow(path, flows_dir=base)
        except FlowError:
            continue
        flows.append(flow.to_dict())
    return flows


def detect_format(text: str) -> str | None:
    """
    Heurística leve para "da maneira que o usuário pediu".

    Ex.: `me manda no whatsapp` → whatsapp; `em tópicos` → bullets;
    `um resumo curto` → resumo. O formato explícito do fluxo vence.
    """
    low = (text or "").lower()
    if "whatsapp" in low or "telegram" in low:
        return "whatsapp"
    if re.search(r"\b(t[óo]picos?|bullets?|lista)\b", low):
        return "bullets"
    if re.search(r"\b(resumo|resumido|curto)\b", low):
        return "resumo"
    return None


def is_trusted_flow_path(
    path: str | Path,
    flows_dir: str | Path | None = None,
) -> bool:
    """True se o fluxo está dentro de `flows/` (o diretório do projeto)."""
    base = (Path(flows_dir) if flows_dir else DEFAULT_FLOWS_DIR).resolve()
    try:
        Path(path).resolve().relative_to(base)
        return True
    except ValueError:
        return False


def command_checks(flow: Flow) -> list[dict]:
    """Lista as checagens que executam comando (para aviso de fluxo externo)."""
    found: list[dict] = []

    def visit(check) -> None:
        if isinstance(check, list):
            for item in check:
                visit(item)
        elif isinstance(check, dict):
            tipo = str(check.get("tipo") or check.get("type") or "").lower()
            if tipo in ("comando", "cmd", "command", "shell", "exit", "exec"):
                found.append(check)

    for task in flow.tasks:
        visit(task.get("checagem"))
    return found


# ── fluxo → quadro ────────────────────────────────────────────────────────

def build_board(
    flow: Flow,
    *,
    objetivo: str | None = None,
    perfil: str | None = None,
    formato: str | None = None,
) -> Board:
    """
    Converte o fluxo em um `Board` pronto para o runner.

    - fase default: "geral"
    - `depende_de` por nome ou id é traduzido para id
    - quadro é validado antes de retornar (ids, fases, dependências)
    """
    objective = (objetivo or flow.objetivo or "").strip()
    if not objective:
        raise FlowError("fluxo sem objetivo — defina 'objetivo:' no cabeçalho")

    # precedência: formato explícito > pedido do usuário > cabeçalho do fluxo
    formato_efetivo = (
        formato or detect_format(objective) or flow.formato or "markdown"
    )

    board = Board.new(
        objective,
        fluxo=flow.name,
        # vazio = herda o perfil do ciel_config.json (local/nuvem)
        perfil=(
            normalize_perfil(perfil) if perfil else (flow.perfil or "")
        ),
        entrega={
            "formato": formato_efetivo,
            "como_testar": flow.como_testar,
        },
        meta={"flow_path": str(flow.path), **flow.meta},
    )

    name_to_id: dict[str, str] = {}
    states = []

    for task in flow.tasks:
        nome = (task.get("nome") or "").strip()
        if not nome:
            raise FlowError("task sem nome no fluxo")
        if nome in name_to_id:
            raise FlowError(f"task duplicada no fluxo: '{nome}'")

        fase = (task.get("fase") or "geral").strip() or "geral"
        try:
            state = board.add_task(
                fase,
                nome,
                objetivo=task.get("objetivo", ""),
                acoes=task.get("acoes", []),
                resultado_esperado=task.get("resultado", ""),
                checagem=task.get("checagem"),
                agente=task.get("agente", ""),
                tools=task.get("tools") or None,
            )
        except BoardError as exc:
            raise FlowError(str(exc)) from exc

        name_to_id[nome] = state.id
        states.append((state, task))

    # segunda passada: dependências por nome → id
    unknown: list[str] = []
    for state, task in states:
        resolved: list[str] = []
        for dep in task.get("depende_de") or []:
            dep = str(dep).strip()
            if dep in name_to_id:
                resolved.append(name_to_id[dep])
            elif board.task(dep) is not None:
                resolved.append(dep)
            else:
                unknown.append(f"task '{task['nome']}' depende de '{dep}', que não existe")
        state.depende_de = resolved

    if unknown:
        raise FlowError("; ".join(unknown))

    errors = board.validate()
    if errors:
        raise FlowError("quadro inválido: " + "; ".join(errors))

    board.touch()
    return board


__all__ = [
    "DEFAULT_FLOWS_DIR",
    "VALID_FORMATS",
    "FlowError",
    "Flow",
    "load_flow",
    "list_flows",
    "detect_format",
    "is_trusted_flow_path",
    "command_checks",
    "build_board",
]

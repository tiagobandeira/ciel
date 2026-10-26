"""
task_defs.py — formato e leitura de tasks (`tasks/*.md`).

Antes este código morava em `cli.py`, e `task_runner.py` importava de lá
dentro de funções para escapar de import circular. Aqui ele fica sem
dependência de UI, para ser usado pelo CLI, pela TUI, pelo headless e
pelo runner do multitask.

Formato mínimo continua o mesmo:

    ## task: nome-em-kebab-case

    objetivo: descrição curta

    ações:
    - passo 1 [tool: calculator]
    - passo 2

    resultado esperado: o que deve ser entregue

Campos opcionais (preparados para o multitask — nada os usa ainda):

    fase: backend
    agente: dev_helper
    depende_de: t1, t2
    checagem: {"tipo": "http", "url": "/", "esperado": 200}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TASKS_DIR_DEFAULT = Path("tasks")

# chaves sempre presentes no dict — o runner novo usa .get(),
# e o formato antigo continua funcionando sem nenhuma mudança.
TASK_KEYS = (
    "nome", "objetivo", "acoes", "resultado", "grupo",
    "fase", "agente", "tools", "max_steps", "pular_se_ok",
    "depende_de", "checagem",
)


def _parse_depende(raw: str) -> list[str]:
    """Aceita `t1, t2` e também `t1 t2` (espaços)."""
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = raw.split(",") if "," in raw else raw.split()
    return [p.strip() for p in parts if p.strip()]


def _parse_checagem(raw: str):
    """JSON inline vira dict/lista; qualquer outra coisa fica string."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw[0] in "{[":
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            pass
    return raw


def parse_task_text(text: str) -> dict | None:
    """
    Interpreta o conteúdo de uma task (sem tocar no disco).

    Usado por `load_task` e pelo parser de fluxos, que precisa dividir um
    único arquivo em várias tasks.
    """
    lines = text.splitlines()

    nome      = ""
    objetivo  = ""
    acoes: list[str] = []
    resultado = ""
    grupo     = ""
    fase      = ""
    agente    = ""
    tools: list[str] = []
    max_steps = 0
    pular_se_ok = False
    depende_de: list[str] = []
    checagem  = None
    section   = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## task:"):
            nome = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("objetivo:"):
            objetivo = stripped.split(":", 1)[1].strip()
            section  = None
        elif stripped.startswith("grupo:"):
            grupo   = stripped.split(":", 1)[1].strip()
            section = None
        elif stripped.startswith("fase:"):
            fase    = stripped.split(":", 1)[1].strip()
            section = None
        elif stripped.startswith("agente:"):
            agente  = stripped.split(":", 1)[1].strip()
            section = None
        elif stripped.startswith("tools:") or stripped.startswith("ferramentas:"):
            tools = _parse_depende(stripped.split(":", 1)[1])
            section = None
        elif stripped.startswith("max_steps:") or stripped.startswith("max passos:"):
            raw = stripped.split(":", 1)[1].strip()
            try:
                max_steps = max(0, int(raw))
            except (TypeError, ValueError):
                max_steps = 0
            section = None
        elif stripped.startswith("pular_se_ok:") or stripped.startswith("pular se ok:"):
            raw = stripped.split(":", 1)[1].strip().lower()
            pular_se_ok = raw in ("1", "true", "sim", "s", "yes", "y")
            section = None
        elif stripped.startswith("depende_de:") or stripped.startswith("depende de:"):
            raw = stripped.split(":", 1)[1]
            depende_de = _parse_depende(raw)
            section = None
        elif stripped.startswith("checagem:"):
            checagem = _parse_checagem(stripped.split(":", 1)[1])
            section  = None
        elif stripped == "ações:" or stripped == "acoes:":
            section = "acoes"
        elif stripped.startswith("resultado esperado:"):
            resultado = stripped.split(":", 1)[1].strip()
            section   = None
        elif section == "acoes" and stripped.startswith("-"):
            acoes.append(stripped[1:].strip())

    if not nome or not acoes:
        return None

    return {
        "nome": nome,
        "objetivo": objetivo,
        "acoes": acoes,
        "resultado": resultado,
        "grupo": grupo,
        "fase": fase,
        "agente": agente,
        "tools": tools,
        "max_steps": max_steps,
        "pular_se_ok": pular_se_ok,
        "depende_de": depende_de,
        "checagem": checagem,
    }


def load_task(path: Path) -> dict | None:
    """
    Lê um arquivo .md de task e retorna dict com:
      { nome, objetivo, acoes, resultado, grupo,
        fase, agente, depende_de, checagem }
    Retorna None se o arquivo não seguir o formato mínimo
    (precisa de `## task:` e pelo menos uma ação).
    """
    path = Path(path)
    if not path.exists():
        return None

    return parse_task_text(path.read_text(encoding="utf-8"))


def load_tasks(path: Path) -> list[dict]:
    """
    Lê um arquivo com VÁRIAS tasks (formato de fluxo) e devolve a lista
    na ordem em que aparecem. Arquivos com uma task só funcionam também.
    """
    path = Path(path)
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"(?m)^##\s+task:", text)]
    if not starts:
        return []

    tasks: list[dict] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        task = parse_task_text(text[start:end])
        if task is not None:
            tasks.append(task)
    return tasks


def find_tasks(query: str, tasks_dir: Path) -> list[Path]:
    """
    Busca tasks cujo nome contenha o query (case-insensitive).
    Retorna lista de paths ordenada por relevância (match exato primeiro).
    """
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.exists():
        return []
    q = query.lower().replace(" ", "-")
    matches = [p for p in tasks_dir.glob("*.md") if q in p.stem.lower()]
    matches.sort(key=lambda p: (0 if p.stem.lower() == q else 1, p.stem))
    return matches


def is_trusted_task_path(
    task_path: Path,
    tasks_dir: Path | None = None,
) -> bool:
    """
    Retorna True se a task está dentro da pasta tasks/ padrão do projeto.
    Tasks externas (path absoluto ou relativo fora de tasks/) são não-confiáveis
    e exigem confirmação do usuário (CLI/TUI) ou autenticação (server).
    No headless (--task) são simplesmente recusadas — automação só roda
    tasks do próprio projeto.
    """
    base = (tasks_dir or TASKS_DIR_DEFAULT).resolve()
    try:
        Path(task_path).resolve().relative_to(base)
        return True
    except ValueError:
        return False


def build_task_prompt(task: dict) -> str:
    """
    Converte a task num prompt direto pro run_agent.
    O agente recebe o plano pronto e age como executor/inspetor.
    """
    acoes_fmt = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(task["acoes"]))
    return (
        f"Execute a seguinte task: {task['nome']}\n\n"
        f"Objetivo: {task['objetivo']}\n\n"
        f"Ações a executar em ordem:\n{acoes_fmt}\n\n"
        f"Resultado esperado: {task['resultado']}\n\n"
        f"Siga as ações na ordem indicada. Se uma ação especificar [tool: nome], "
        f"use essa tool. Caso contrário, escolha a tool mais adequada disponível."
    )


__all__ = [
    "TASKS_DIR_DEFAULT",
    "TASK_KEYS",
    "parse_task_text",
    "load_task",
    "load_tasks",
    "find_tasks",
    "is_trusted_task_path",
    "build_task_prompt",
]

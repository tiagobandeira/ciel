"""Monta um Board do multitask a partir de uma skill absorvida."""

from __future__ import annotations

import json
from pathlib import Path

from board import Board
from task_defs import load_task


class SkillBoardError(Exception):
    """Erro ao converter skill em quadro."""


def load_skill_meta(name: str, skills_dir: str | Path = "skills") -> dict:
    base = Path(skills_dir)
    safe = (name or "").strip().replace("\\", "/").split("/")[-1]
    if safe.endswith("_meta.json"):
        safe = safe[: -len("_meta.json")]
    path = base / f"{safe}_meta.json"
    if not path.exists():
        raise SkillBoardError(f"skill absorvida não encontrada: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SkillBoardError(f"meta inválida em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillBoardError(f"meta inválida em {path}: esperado objeto")
    return data


def build_skill_board(
    name: str,
    *,
    skills_dir: str | Path = "skills",
    tasks_dir: str | Path = "tasks",
    perfil: str = "",
) -> Board:
    """Cria um Board a partir das tasks geradas por `/analisar`."""
    meta = load_skill_meta(name, skills_dir)
    filenames = [str(x) for x in meta.get("tasks") or []]
    if not filenames:
        raise SkillBoardError(
            f"skill '{name}' é do tipo '{meta.get('type', '?')}' e não tem "
            "tasks executáveis; use as tools/instruções diretamente."
        )

    board = Board.new(
        str(meta.get("description") or f"executar skill {name}"),
        fluxo=f"skill:{name}",
        perfil=perfil,
        meta={"skill": name, "skill_type": meta.get("type", "")},
    )
    name_to_id: dict[str, str] = {}
    last_id = ""
    for filename in filenames:
        task_path = Path(tasks_dir) / Path(filename).name
        task = load_task(task_path)
        if not task:
            raise SkillBoardError(
                f"task gerada inválida ou ausente: {task_path}"
            )
        fase = (task.get("fase") or "Execução").strip() or "Execução"
        deps: list[str] = []
        for dep in task.get("depende_de") or []:
            if dep in name_to_id:
                deps.append(name_to_id[dep])
        if not deps and meta.get("type") == "pipeline" and last_id:
            deps = [last_id]
        state = board.add_task(
            fase,
            task["nome"],
            objetivo=task.get("objetivo", ""),
            acoes=task.get("acoes", []),
            resultado_esperado=task.get("resultado", ""),
            checagem=task.get("checagem"),
            agente=task.get("agente", ""),
            tools=task.get("tools") or None,
            max_steps=task.get("max_steps", 0),
            pular_se_ok=bool(task.get("pular_se_ok")),
            depende_de=deps,
        )
        name_to_id[task["nome"]] = state.id
        last_id = state.id

    errors = board.validate()
    if errors:
        raise SkillBoardError("quadro inválido: " + "; ".join(errors))
    return board

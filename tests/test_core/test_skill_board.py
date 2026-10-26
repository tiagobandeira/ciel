"""Converter skill absorvida em board do multitask."""

import json
from pathlib import Path

import pytest

from multitask.skill_board import SkillBoardError, build_skill_board


def _write_skill(tmp_path, name="demo", tasks=("a", "b"), kind="pipeline"):
    skills = tmp_path / "skills"
    tasks_dir = tmp_path / "tasks"
    skills.mkdir()
    tasks_dir.mkdir()
    filenames = []
    for index, task_name in enumerate(tasks, start=1):
        filename = f"{name}_{task_name}.md"
        (tasks_dir / filename).write_text(
            f"## task: {task_name}\n\n"
            f"objetivo: etapa {index}\n\n"
            "ações:\n- executar etapa\n\n"
            "resultado esperado: etapa concluída\n",
            encoding="utf-8",
        )
        filenames.append(filename)
    (skills / f"{name}_meta.json").write_text(json.dumps({
        "skill_name": name,
        "type": kind,
        "description": "skill de teste",
        "tasks": filenames,
    }), encoding="utf-8")
    return skills, tasks_dir


def test_monta_board_em_ordem(tmp_path):
    skills, tasks_dir = _write_skill(tmp_path)
    board = build_skill_board(
        "demo", skills_dir=skills, tasks_dir=tasks_dir, perfil="nuvem",
    )
    assert len(board.tasks()) == 2
    assert board.task("t1").titulo == "a"
    assert board.task("t2").depende_de == ["t1"]


def test_skill_plugin_sem_tasks_falha(tmp_path):
    skills, tasks_dir = _write_skill(tmp_path, kind="plugin", tasks=())
    with pytest.raises(SkillBoardError, match="não tem tasks"):
        build_skill_board("demo", skills_dir=skills, tasks_dir=tasks_dir)

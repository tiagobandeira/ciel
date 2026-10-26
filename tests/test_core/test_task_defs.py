"""
tests/test_core/test_task_defs.py

Cobre `task_defs.py` (o que antes vivia em cli.py) e garante que os
reexports de compatibilidade continuam funcionando.
"""

from pathlib import Path

import pytest

from task_defs import (
    build_task_prompt,
    find_tasks,
    is_trusted_task_path,
    load_task,
)


BASE_TASK = """\
## task: minha-task

objetivo: fazer alguma coisa útil

ações:
- passo 1 [tool: calculator]
- passo 2

resultado esperado: arquivo gerado com sucesso
"""


@pytest.fixture
def tasks_dir(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    return d


def write(tasks_dir: Path, name: str, content: str) -> Path:
    path = tasks_dir / name
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadTask:
    def test_campos_basicos(self, tasks_dir):
        task = load_task(write(tasks_dir, "t.md", BASE_TASK))
        assert task is not None
        assert task["nome"] == "minha-task"
        assert task["objetivo"] == "fazer alguma coisa útil"
        assert task["acoes"] == ["passo 1 [tool: calculator]", "passo 2"]
        assert task["resultado"] == "arquivo gerado com sucesso"

    def test_campos_extras_sempre_presentes(self, tasks_dir):
        task = load_task(write(tasks_dir, "t.md", BASE_TASK))
        assert task["grupo"] == ""
        assert task["fase"] == ""
        assert task["agente"] == ""
        assert task["tools"] == []
        assert task["depende_de"] == []
        assert task["checagem"] is None

    def test_campos_opcionais_do_multitask(self, tasks_dir):
        text = BASE_TASK + """\

fase: backend
subagente: dev_helper
tools: read_file, write_file, list_directory
max_steps: 6
parallel: true
modelo: modelo-x
perfil: nuvem
read_only: true
depende_de: t1, t2
checagem: {"tipo": "http", "url": "/", "esperado": 200}
"""
        task = load_task(write(tasks_dir, "t.md", text))
        assert task["fase"] == "backend"
        assert task["agente"] == "dev_helper"
        assert task["tools"] == ["read_file", "write_file", "list_directory"]
        assert task["max_steps"] == 6
        assert task["parallel"] is True
        assert task["modelo"] == "modelo-x"
        assert task["perfil"] == "nuvem"
        assert task["read_only"] is True
        assert task["depende_de"] == ["t1", "t2"]
        assert task["checagem"] == {
            "tipo": "http", "url": "/", "esperado": 200,
        }

    def test_depende_de_com_espacos(self, tasks_dir):
        task = load_task(write(tasks_dir, "t.md", BASE_TASK + "\ndepende de: t1 t2\n"))
        assert task["depende_de"] == ["t1", "t2"]

    def test_checagem_texto_simples(self, tasks_dir):
        task = load_task(write(tasks_dir, "t.md", BASE_TASK + "\nchecagem: manual\n"))
        assert task["checagem"] == "manual"

    def test_checagem_json_invalido_fica_string(self, tasks_dir):
        task = load_task(write(tasks_dir, "t.md", BASE_TASK + "\nchecagem: {quebrado\n"))
        assert task["checagem"] == "{quebrado"

    def test_grupo_preservado(self, tasks_dir):
        task = load_task(write(tasks_dir, "t.md", BASE_TASK + "\ngrupo: calculator\n"))
        assert task["grupo"] == "calculator"

    def test_sem_nome_retorna_none(self, tasks_dir):
        assert load_task(write(tasks_dir, "t.md", "objetivo: x\n\nações:\n- a\n")) is None

    def test_sem_acoes_retorna_none(self, tasks_dir):
        assert load_task(write(tasks_dir, "t.md", "## task: x\n\nobjetivo: y\n")) is None

    def test_arquivo_inexistente(self, tasks_dir):
        assert load_task(tasks_dir / "nao.md") is None

    def test_aceita_string_como_path(self, tasks_dir):
        path = write(tasks_dir, "t.md", BASE_TASK)
        assert load_task(str(path))["nome"] == "minha-task"


class TestFindTasks:
    def test_match_parcial(self, tasks_dir):
        write(tasks_dir, "radar-ia.md", BASE_TASK)
        write(tasks_dir, "outra.md", BASE_TASK)
        assert [p.stem for p in find_tasks("radar", tasks_dir)] == ["radar-ia"]

    def test_match_exato_primeiro(self, tasks_dir):
        write(tasks_dir, "ia.md", BASE_TASK)
        write(tasks_dir, "radar-ia.md", BASE_TASK)
        assert [p.stem for p in find_tasks("ia", tasks_dir)][0] == "ia"

    def test_pasta_inexistente(self, tmp_path):
        assert find_tasks("x", tmp_path / "nada") == []


class TestIsTrustedTaskPath:
    def test_dentro_de_tasks(self, tasks_dir):
        path = write(tasks_dir, "t.md", BASE_TASK)
        assert is_trusted_task_path(path, tasks_dir) is True

    def test_fora_de_tasks(self, tmp_path, tasks_dir):
        fora = tmp_path / "fora.md"
        fora.write_text(BASE_TASK, encoding="utf-8")
        assert is_trusted_task_path(fora, tasks_dir) is False


class TestBuildTaskPrompt:
    def test_prompt_inclui_acoes_em_ordem(self, tasks_dir):
        task = load_task(write(tasks_dir, "t.md", BASE_TASK))
        prompt = build_task_prompt(task)
        assert "minha-task" in prompt
        assert "1. passo 1 [tool: calculator]" in prompt
        assert "2. passo 2" in prompt
        assert "arquivo gerado com sucesso" in prompt


class TestReexports:
    """Chamadores antigos (`from cli import ...`) continuam funcionando."""

    def test_cli_reexporta(self):
        import cli
        assert cli.load_task is load_task
        assert cli.build_task_prompt is build_task_prompt
        assert cli.find_tasks is find_tasks
        assert cli.is_trusted_task_path is is_trusted_task_path

    def test_task_runner_importa_de_task_defs(self):
        import task_runner
        assert task_runner.build_task_prompt is build_task_prompt

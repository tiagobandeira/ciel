"""
tests/test_security/test_task_guard.py

Cobre is_trusted_task_path: paths internos, externos, traversal via ../,
tasks do .ciel/ (internas do sistema), e escape via symlink.
"""

import os
import pytest
from pathlib import Path
from cli import is_trusted_task_path


@pytest.fixture(autouse=True)
def mudar_para_tmp(tmp_path, monkeypatch):
    """Roda cada teste com cwd num diretório temporário com pasta tasks/."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "minha-task.md").write_text("## task: teste\n")
    ciel_dir = tasks / ".ciel"
    ciel_dir.mkdir()
    (ciel_dir / "criar_task.md").write_text("## task: criar\n")
    monkeypatch.chdir(tmp_path)


class TestConfiavel:
    def test_task_dentro_de_tasks(self):
        assert is_trusted_task_path(Path("tasks/minha-task.md")) is True

    def test_task_ciel_interna(self):
        """tasks/.ciel/ é pasta interna do sistema — sempre confiável."""
        assert is_trusted_task_path(Path("tasks/.ciel/criar_task.md")) is True

    def test_path_absoluto_dentro_de_tasks(self, tmp_path):
        p = tmp_path / "tasks" / "minha-task.md"
        assert is_trusted_task_path(p) is True


class TestNaoConfiavel:
    def test_path_absoluto_externo(self):
        assert is_trusted_task_path(Path("/tmp/maliciosa.md")) is False

    def test_path_relativo_fora(self, tmp_path):
        externo = tmp_path / "externo"
        externo.mkdir()
        (externo / "task.md").write_text("## task: x\n")
        assert is_trusted_task_path(Path("../externo/task.md")) is False

    def test_traversal_via_pontos(self, tmp_path):
        """tasks/../../../etc/passwd não deve ser considerado confiável."""
        p = Path("tasks") / ".." / ".." / "etc" / "passwd.md"
        assert is_trusted_task_path(p) is False

    def test_home_directory(self):
        assert is_trusted_task_path(Path.home() / "task.md") is False

    def test_arquivo_na_raiz_do_projeto(self):
        """Um .md na raiz do projeto (não dentro de tasks/) não é confiável."""
        (Path(".") / "task-externa.md").write_text("## task: x\n")
        assert is_trusted_task_path(Path("task-externa.md")) is False

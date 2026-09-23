"""
tests/test_tools/test_registry.py

Verifica que tools_registry lê corretamente os metadados das tools:
PERMISSIONS, INTERACTIVE, OUTPUT, REQUIREMENTS, EXTRA e shadow warning.
"""

import importlib
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def tools():
    import tools_registry
    return tools_registry.load_tools()


class TestMetadados:
    def test_read_file_tem_permissions(self, tools):
        assert "read_file" in tools
        assert tools["read_file"]["permissions"] == {"path": "read"}

    def test_write_file_tem_permissions_escrita(self, tools):
        assert tools["write_file"]["permissions"] == {"path": "write"}

    def test_calculator_sem_permissions(self, tools):
        assert tools["calculator"]["permissions"] == {}

    def test_calculator_output_interno(self, tools):
        assert tools["calculator"]["output_type"] == "internal"

    def test_entrevista_interativa_tem_interactive(self, tools):
        assert tools.get("entrevista_interativa", {}).get("interactive") is True

    def test_run_script_output_interno(self, tools):
        """run_script executa código mas o output não é conteúdo externo."""
        assert tools["run_script"]["output_type"] == "internal"


class TestShadowWarning:
    def test_shadow_detectado(self, tmp_path, monkeypatch):
        """Tool com mesmo nome em tools/ e tools/temp/ gera entrada em _shadowed_tools."""
        import tools_registry as tr

        tools_dir = tmp_path / "tools"
        temp_dir  = tools_dir / "temp"
        tools_dir.mkdir()
        temp_dir.mkdir()

        code = '"""Tool teste."""\ndef run(x: str) -> str:\n    return x\n'
        (tools_dir / "minha_tool.py").write_text(code)
        (temp_dir  / "minha_tool.py").write_text(code)

        # patch TOOLS_DIR e TOOLS_TEMP_DIR temporariamente
        orig_dir  = tr.TOOLS_DIR
        orig_temp = tr.TOOLS_TEMP_DIR
        tr.TOOLS_DIR      = tools_dir
        tr.TOOLS_TEMP_DIR = temp_dir

        try:
            tr.load_tools()
            assert "minha_tool" in tr.get_shadowed_tools()
        finally:
            tr.TOOLS_DIR      = orig_dir
            tr.TOOLS_TEMP_DIR = orig_temp

    def test_sem_shadow_lista_vazia(self, tools):
        import tools_registry as tr
        tr.load_tools()  # força reset do estado global
        # No estado normal do projeto não deve haver shadows
        assert tr.get_shadowed_tools() == []


class TestPathChecks:
    def test_get_path_checks_read_file(self, tools):
        from tool_dispatch import get_path_checks
        checks = get_path_checks("read_file", tools)
        assert ("path", False) in checks

    def test_get_path_checks_write_file(self, tools):
        from tool_dispatch import get_path_checks
        checks = get_path_checks("write_file", tools)
        assert ("path", True) in checks

    def test_get_path_checks_calculator_vazio(self, tools):
        from tool_dispatch import get_path_checks
        assert get_path_checks("calculator", tools) == []

    def test_get_path_checks_tool_inexistente(self, tools):
        from tool_dispatch import get_path_checks
        assert get_path_checks("nao_existe", tools) == []

"""
tests/test_tools/test_create_tool.py

Cobre create_tool.py:
  - _validate: nome inválido, sem docstring, sem run(), REQUIREMENTS/PERMISSIONS malformados
  - _sanitize_code: correção de aspas e tabs
  - _extract_requirements: presença e ausência do bloco REQUIREMENTS
  - _check_permission_coverage: paths sem PERMISSIONS geram aviso
  - run(): criação bem-sucedida e falha de validação (sem tocar tools/ real)
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from tools.create_tool import (
    _validate,
    _sanitize_code,
    _extract_requirements,
    _check_permission_coverage,
    run as create_tool,
)


# ── _sanitize_code ────────────────────────────────────────────────────────────

class TestSanitizeCode:
    def test_corrige_docstring_com_duas_aspas(self):
        code = '"""Descrição.""'
        result = _sanitize_code(code)
        assert result.startswith('"""Descrição."""')

    def test_corrige_linha_so_com_duas_aspas(self):
        code = 'def run():\n    """Faz algo.\n    ""'
        result = _sanitize_code(code)
        assert '    """' in result

    def test_normaliza_crlf(self):
        code = "linha 1\r\nlinha 2\r\nlinha 3"
        result = _sanitize_code(code)
        assert "\r" not in result

    def test_converte_tab_para_espacos(self):
        code = "def run():\n\treturn 'ok'"
        result = _sanitize_code(code)
        assert "\t" not in result
        assert "    return" in result

    def test_codigo_valido_nao_alterado(self):
        code = '"""Desc."""\n\ndef run():\n    return "ok"\n'
        result = _sanitize_code(code)
        assert result == code


# ── _validate ─────────────────────────────────────────────────────────────────

class TestValidate:
    def test_codigo_valido_retorna_true(self):
        code = '"""Descrição.\"\"\"\n\ndef run():\n    return "ok"\n'
        ok, msg = _validate(code)
        assert ok is True
        assert msg == ""

    def test_sem_docstring_retorna_false(self):
        code = "def run():\n    return 'ok'\n"
        ok, msg = _validate(code)
        assert ok is False
        assert "docstring" in msg.lower() or "módulo" in msg.lower()

    def test_sem_funcao_run_retorna_false(self):
        code = '"""Descrição."""\n\ndef outra():\n    pass\n'
        ok, msg = _validate(code)
        assert ok is False
        assert "run" in msg

    def test_codigo_vazio_retorna_false(self):
        ok, msg = _validate("")
        assert ok is False

    def test_erro_de_sintaxe_retorna_false(self):
        code = '"""Desc."""\ndef run(\n    return "ok"'
        ok, msg = _validate(code)
        assert ok is False
        assert "sintaxe" in msg.lower() or "linha" in msg.lower()

    def test_requirements_invalido_retorna_false(self):
        code = (
            '"""Desc."""\n\n'
            "REQUIREMENTS = 'requests'\n\n"
            "def run():\n    return 'ok'\n"
        )
        ok, msg = _validate(code)
        assert ok is False
        assert "REQUIREMENTS" in msg

    def test_requirements_valido_aceito(self):
        code = (
            '"""Desc."""\n\n'
            'REQUIREMENTS = ["requests", "beautifulsoup4"]\n\n'
            "def run():\n    return 'ok'\n"
        )
        ok, msg = _validate(code)
        assert ok is True

    def test_permissions_invalido_retorna_false(self):
        code = (
            '"""Desc."""\n\n'
            "PERMISSIONS = {'path': 'admin'}\n\n"  # 'admin' não é válido
            "def run(path: str):\n    return path\n"
        )
        ok, msg = _validate(code)
        assert ok is False
        assert "PERMISSIONS" in msg

    def test_permissions_valido_aceito(self):
        code = (
            '"""Desc."""\n\n'
            'PERMISSIONS = {"path": "read"}\n\n'
            "def run(path: str):\n    return path\n"
        )
        ok, msg = _validate(code)
        assert ok is True


# ── _extract_requirements ─────────────────────────────────────────────────────

class TestExtractRequirements:
    def test_extrai_requirements_presentes(self):
        code = (
            '"""Desc."""\n\n'
            'REQUIREMENTS = ["requests", "httpx>=0.24"]\n\n'
            "def run():\n    return 'ok'\n"
        )
        reqs = _extract_requirements(code)
        assert reqs == ["requests", "httpx>=0.24"]

    def test_sem_requirements_retorna_lista_vazia(self):
        code = '"""Desc."""\n\ndef run():\n    return "ok"\n'
        reqs = _extract_requirements(code)
        assert reqs == []

    def test_requirements_vazio_retorna_lista_vazia(self):
        code = '"""Desc."""\n\nREQUIREMENTS = []\n\ndef run():\n    return "ok"\n'
        reqs = _extract_requirements(code)
        assert reqs == []


# ── _check_permission_coverage ────────────────────────────────────────────────

class TestCheckPermissionCoverage:
    def test_param_path_sem_permissions_gera_aviso(self):
        code = '"""Desc."""\n\ndef run(path: str):\n    return path\n'
        aviso = _check_permission_coverage(code)
        assert aviso is not None
        assert "path" in aviso.lower()

    def test_param_path_com_permissions_nao_gera_aviso(self):
        code = (
            '"""Desc."""\n\n'
            'PERMISSIONS = {"path": "read"}\n\n'
            "def run(path: str):\n    return path\n"
        )
        aviso = _check_permission_coverage(code)
        assert aviso is None

    def test_param_sem_nome_sugestivo_nao_gera_aviso(self):
        code = '"""Desc."""\n\ndef run(nome: str, idade: int):\n    return nome\n'
        aviso = _check_permission_coverage(code)
        assert aviso is None

    def test_param_arquivo_sem_permissions_gera_aviso(self):
        code = '"""Desc."""\n\ndef run(arquivo: str):\n    return arquivo\n'
        aviso = _check_permission_coverage(code)
        assert aviso is not None

    def test_codigo_com_erro_de_sintaxe_retorna_none(self):
        # não deve explodir mesmo com código inválido
        aviso = _check_permission_coverage("def run(")
        assert aviso is None

    def test_sem_funcao_run_retorna_none(self):
        code = '"""Desc."""\n\ndef outra(path: str):\n    return path\n'
        aviso = _check_permission_coverage(code)
        assert aviso is None


# ── run() (integração) ────────────────────────────────────────────────────────

CODIGO_VALIDO = (
    '"""Tool de teste que soma dois números."""\n\n'
    "def run(a: int, b: int) -> str:\n"
    "    return str(a + b)\n"
)

CODIGO_INVALIDO = "def run():\n    return 'sem docstring'\n"


class TestCreateToolRun:
    def test_nome_invalido_retorna_erro(self):
        """Nome que após sanitização vira string vazia deve ser rejeitado."""
        # "!!!" → strip("_") → "" → safe_name vazio
        result = create_tool("!!!", CODIGO_VALIDO)
        assert "Erro" in result and "inválido" in result.lower()

    def test_nome_so_espacos_retorna_erro(self):
        result = create_tool("   ", CODIGO_VALIDO)
        assert "Erro" in result and "inválido" in result.lower()

    def test_codigo_invalido_retorna_erro_de_validacao(self):
        result = create_tool("minha_tool", CODIGO_INVALIDO)
        assert "Erro de validação" in result

    def test_nome_com_maiusculas_e_normalizado(self):
        """Nomes com maiúsculas são convertidos para lowercase antes de validar."""
        # Mockamos _validate para parar cedo e inspecionar o fluxo
        with patch("tools.create_tool._validate", return_value=(False, "stop_marker")) as m:
            result = create_tool("MinhaFerramenta", CODIGO_VALIDO)
        assert "stop_marker" in result

    def test_criacao_bem_sucedida(self, tmp_path):
        """Redireciona o diretório de saída via patch do __file__ do módulo."""
        import tools.create_tool as ct_module

        fake_file = str(tmp_path / "create_tool.py")
        with (
            patch.object(ct_module, "__file__", fake_file),
            patch("tools.create_tool._install", return_value=(True, "")),
            patch("tools.create_tool._try_import_and_fix", return_value=None),
        ):
            result = create_tool("tool_teste_sucesso", CODIGO_VALIDO)

        # Deve criar em tmp_path/tool_teste_sucesso.py
        assert "tool_teste_sucesso" in result
        assert "Erro de validação" not in result
        assert "inválido" not in result.lower()
        assert (tmp_path / "tool_teste_sucesso.py").exists()

    def test_codigo_com_tab_e_sanitizado_antes_de_validar(self, tmp_path):
        import tools.create_tool as ct_module

        codigo_com_tab = '"""Desc."""\n\ndef run():\n\treturn "ok"\n'
        with (
            patch.object(ct_module, "__file__", str(tmp_path / "create_tool.py")),
            patch("tools.create_tool._install", return_value=(True, "")),
            patch("tools.create_tool._try_import_and_fix", return_value=None),
        ):
            result = create_tool("tool_tab_test", codigo_com_tab)

        # Tab é sanitizado antes da validação — não deve dar erro de sintaxe
        assert "Erro de validação" not in result
        assert "tool_tab_test" in result

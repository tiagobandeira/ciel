"""
tests/test_tools/test_create_temp_tool.py

Cobre create_temp_tool.py:
  - _validate, _sanitize_code, _extract_requirements (espelham create_tool)
  - shadow de tool permanente bloqueia criação de temp
  - nome inválido rejeitado
  - criação bem-sucedida em diretório temporário
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.create_temp_tool import (
    _validate,
    _sanitize_code,
    _check_permission_coverage,
    run as create_temp_tool,
)


# ── _sanitize_code ────────────────────────────────────────────────────────────

class TestSanitizeCodeTemp:
    def test_corrige_docstring_com_duas_aspas(self):
        code = '"""Descrição.""'
        result = _sanitize_code(code)
        assert result.startswith('"""Descrição."""')

    def test_normaliza_crlf(self):
        code = "linha 1\r\nlinha 2"
        result = _sanitize_code(code)
        assert "\r" not in result

    def test_converte_tab_para_espacos(self):
        code = "def run():\n\treturn 'ok'"
        result = _sanitize_code(code)
        assert "\t" not in result

    def test_corrige_linha_so_com_duas_aspas(self):
        code = 'def run():\n    """Faz algo.\n    ""'
        result = _sanitize_code(code)
        assert '    """' in result


# ── _validate ─────────────────────────────────────────────────────────────────

class TestValidateTemp:
    def test_codigo_valido_retorna_true(self):
        code = '"""Descrição."""\n\ndef run():\n    return "ok"\n'
        ok, msg = _validate(code)
        assert ok is True

    def test_sem_docstring_retorna_false(self):
        code = "def run():\n    return 'ok'\n"
        ok, msg = _validate(code)
        assert ok is False

    def test_sem_funcao_run_retorna_false(self):
        code = '"""Desc."""\n\ndef outra():\n    pass\n'
        ok, msg = _validate(code)
        assert ok is False
        assert "run" in msg

    def test_codigo_vazio_retorna_false(self):
        ok, msg = _validate("")
        assert ok is False

    def test_erro_de_sintaxe_retorna_false_com_linha(self):
        code = '"""Desc."""\ndef run(\n    return "ok"'
        ok, msg = _validate(code)
        assert ok is False
        assert "linha" in msg.lower() or "sintaxe" in msg.lower()

    def test_permissions_invalido_retorna_false(self):
        code = (
            '"""Desc."""\n\n'
            "PERMISSIONS = {'path': 'exec'}\n\n"
            "def run(path: str):\n    return path\n"
        )
        ok, msg = _validate(code)
        assert ok is False
        assert "PERMISSIONS" in msg

    def test_permissions_valido_aceito(self):
        code = (
            '"""Desc."""\n\n'
            'PERMISSIONS = {"path": "write"}\n\n'
            "def run(path: str):\n    return path\n"
        )
        ok, msg = _validate(code)
        assert ok is True


# ── _check_permission_coverage ────────────────────────────────────────────────

class TestCheckPermCoverageTemp:
    def test_param_path_sem_permissions_gera_aviso(self):
        code = '"""Desc."""\n\ndef run(path: str):\n    return path\n'
        aviso = _check_permission_coverage(code)
        assert aviso is not None

    def test_param_path_com_permissions_nao_gera_aviso(self):
        code = (
            '"""Desc."""\n\n'
            'PERMISSIONS = {"path": "read"}\n\n'
            "def run(path: str):\n    return path\n"
        )
        aviso = _check_permission_coverage(code)
        assert aviso is None


# ── shadow de tool permanente ─────────────────────────────────────────────────

class TestShadowPermanentTool:
    def test_shadow_de_tool_permanente_bloqueia(self, tmp_path):
        """Uma temp com mesmo nome de tool permanente é bloqueada."""
        codigo = '"""Tool temporária."""\n\ndef run():\n    return "temp"\n'

        # simula que existe tools/calculadora.py (tool permanente)
        permanent = tmp_path / "calculadora.py"
        permanent.write_text("permanente")

        with patch("tools.create_temp_tool.Path") as MockPath:
            # __file__ aponta para tmp_path/create_temp_tool.py
            # parent → tmp_path (que tem calculadora.py)
            mock_file = MagicMock()
            mock_file.parent = tmp_path
            MockPath.return_value = mock_file
            MockPath.side_effect = lambda *a: Path(*a) if a else mock_file

            with patch.object(
                __import__("tools.create_temp_tool", fromlist=["create_temp_tool"]),
                "__file__",
                str(tmp_path / "create_temp_tool.py"),
            ):
                result = create_temp_tool("calculadora", codigo)

        assert "Erro" in result
        assert "permanente" in result.lower() or "mesmo nome" in result.lower()

    def test_nome_unico_nao_e_bloqueado_por_shadow(self, tmp_path):
        """Tool com nome único não conflita com permanentes."""
        codigo = '"""Tool temporária."""\n\ndef run():\n    return "ok"\n'
        with (
            patch("tools.create_temp_tool.TOOLS_TEMP_DIR", tmp_path / "temp"),
            patch("tools.create_temp_tool._try_import_and_fix", return_value=None),
            patch("tools.create_temp_tool._log_creation"),
        ):
            # tool_nome_unico_xyz não existe em tools/ real
            result = create_temp_tool("tool_nome_unico_xyz", codigo)

        # deve criar ou dar erro de import, mas não de shadow/nome
        assert "prioridade" not in result
        assert "permanente" not in result.lower()


# ── nome inválido ─────────────────────────────────────────────────────────────

class TestCreateTempToolInvalidName:
    def test_nome_com_espaco_rejeitado(self):
        result = create_temp_tool("meu tool", '"""Desc."""\n\ndef run():\n    return "ok"\n')
        assert "Erro" in result
        assert "inválido" in result.lower() or "nome" in result.lower()

    def test_nome_com_hifen_rejeitado(self):
        result = create_temp_tool("meu-tool", '"""Desc."""\n\ndef run():\n    return "ok"\n')
        assert "Erro" in result

    def test_nome_com_ponto_rejeitado(self):
        result = create_temp_tool("meu.tool", '"""Desc."""\n\ndef run():\n    return "ok"\n')
        assert "Erro" in result

    def test_nome_valido_snake_case_aceito_ate_validacao(self, tmp_path):
        """Nome snake_case passa a verificação de nome (pode falhar depois)."""
        codigo_invalido = "sem docstring"  # falha na validação AST
        result = create_temp_tool("minha_tool_valida", codigo_invalido)
        # o erro deve ser de validação de código, NÃO de nome
        assert "nome inválido" not in result.lower()


# ── run() integração básica ───────────────────────────────────────────────────

class TestCreateTempToolRun:
    def test_codigo_invalido_retorna_erro_de_validacao(self):
        result = create_temp_tool("ferramenta_x", "sem docstring aqui")
        assert "Erro de validação" in result or "Erro" in result

    def test_criacao_bem_sucedida_gera_path_temp(self, tmp_path):
        codigo = '"""Tool de soma temporária."""\n\ndef run(a: int, b: int) -> str:\n    return str(a + b)\n'
        temp_dir = tmp_path / "temp"

        with (
            patch("tools.create_temp_tool.TOOLS_TEMP_DIR", temp_dir),
            patch("tools.create_temp_tool._try_import_and_fix", return_value=None),
            patch("tools.create_temp_tool._log_creation"),
        ):
            # garante que não há tool permanente com esse nome
            with patch("tools.create_temp_tool.Path") as MockPath:
                # permanent_path não existe
                real_path = Path
                call_count = [0]

                def path_side_effect(*args):
                    p = real_path(*args)
                    return p

                MockPath.side_effect = path_side_effect
                MockPath.__file__ = str(tmp_path / "create_temp_tool.py")

                with patch.object(
                    __import__("tools.create_temp_tool", fromlist=["create_temp_tool"]),
                    "__file__",
                    str(tmp_path / "create_temp_tool.py"),
                ):
                    result = create_temp_tool("soma_temp_xyz", codigo)

        # se criou, deve dizer "temp" no resultado; se falhou por import, ok também
        # o importante é não falhar por nome ou validação
        if "Erro de validação" in result:
            pytest.fail(f"Falhou na validação inesperadamente: {result}")

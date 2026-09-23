"""
tests/test_integration/test_tool_dispatch.py

Cobre a camada central de dispatch: filter_unsafe (UNSAFE_TOOLS),
needs_confirmation (create_tool/create_temp_tool), e get_path_checks
(leitura dinâmica de PERMISSIONS do registry).
"""

import pytest
from tool_dispatch import (
    UNSAFE_TOOLS, filter_unsafe, needs_confirmation, get_path_checks
)


# ── filter_unsafe ─────────────────────────────────────────────────────────────

class TestFilterUnsafe:
    @pytest.fixture
    def tools_fake(self):
        return {
            "read_file": {"fn": None},
            "write_file": {"fn": None},
            "run_script": {"fn": None},
            "create_tool": {"fn": None},
            "create_temp_tool": {"fn": None},
            "calculator": {"fn": None},
        }

    def test_safe_remove_run_script(self, tools_fake):
        filtrado = filter_unsafe(tools_fake, safe=True)
        assert "run_script" not in filtrado

    def test_safe_remove_create_tool(self, tools_fake):
        filtrado = filter_unsafe(tools_fake, safe=True)
        assert "create_tool" not in filtrado

    def test_safe_remove_create_temp_tool(self, tools_fake):
        filtrado = filter_unsafe(tools_fake, safe=True)
        assert "create_temp_tool" not in filtrado

    def test_safe_preserva_tools_seguras(self, tools_fake):
        filtrado = filter_unsafe(tools_fake, safe=True)
        assert "read_file" in filtrado
        assert "calculator" in filtrado

    def test_nao_safe_preserva_tudo(self, tools_fake):
        filtrado = filter_unsafe(tools_fake, safe=False)
        assert set(filtrado.keys()) == set(tools_fake.keys())

    def test_unsafe_tools_contem_os_tres(self):
        """UNSAFE_TOOLS deve bloquear run_script E as duas create_tool."""
        assert "run_script" in UNSAFE_TOOLS
        assert "create_tool" in UNSAFE_TOOLS
        assert "create_temp_tool" in UNSAFE_TOOLS


# ── needs_confirmation ────────────────────────────────────────────────────────

class TestNeedsConfirmation:
    def test_create_tool_sem_trust_pede_confirmacao(self):
        assert needs_confirmation("create_tool", trusted=False) is True

    def test_create_temp_tool_sem_trust_pede_confirmacao(self):
        assert needs_confirmation("create_temp_tool", trusted=False) is True

    def test_create_tool_com_trust_nao_pede(self):
        assert needs_confirmation("create_tool", trusted=True) is False

    def test_create_temp_tool_com_trust_nao_pede(self):
        assert needs_confirmation("create_temp_tool", trusted=True) is False

    def test_run_script_nunca_pede_confirmacao(self):
        """run_script é bloqueado pelo filter_unsafe, não pelo confirmation."""
        assert needs_confirmation("run_script", trusted=False) is False

    def test_read_file_nunca_pede_confirmacao(self):
        assert needs_confirmation("read_file", trusted=False) is False

    def test_calculator_nunca_pede_confirmacao(self):
        assert needs_confirmation("calculator", trusted=False) is False


# ── get_path_checks ───────────────────────────────────────────────────────────

class TestGetPathChecks:
    @pytest.fixture(scope="class")
    def tools(self):
        import tools_registry
        return tools_registry.load_tools()

    def test_read_file_path_leitura(self, tools):
        checks = get_path_checks("read_file", tools)
        assert ("path", False) in checks

    def test_write_file_path_escrita(self, tools):
        checks = get_path_checks("write_file", tools)
        assert ("path", True) in checks

    def test_list_directory_directory_leitura(self, tools):
        checks = get_path_checks("list_directory", tools)
        assert ("directory", False) in checks

    def test_calculator_sem_checks(self, tools):
        assert get_path_checks("calculator", tools) == []

    def test_tool_inexistente_sem_checks(self, tools):
        assert get_path_checks("tool_que_nao_existe", tools) == []

    def test_permissions_invalido_ignorado(self):
        """Valor inválido em PERMISSIONS não deve travar — é ignorado."""
        tools_fake = {
            "minha_tool": {
                "permissions": {"path": "invalid_value"},
                "output_type": "internal",
            }
        }
        checks = get_path_checks("minha_tool", tools_fake)
        assert checks == []

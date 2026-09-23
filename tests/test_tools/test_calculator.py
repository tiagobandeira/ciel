"""
tests/test_tools/test_calculator.py

Cobre: operações básicas, funções científicas, modo rad/deg,
proteção MAX_POWER (bomba de exponenciação), cap de tamanho e erros.
"""

import pytest
import importlib.util
from pathlib import Path

@pytest.fixture(scope="module")
def calc():
    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "calculator", ROOT / "tools" / "calculator.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestOperacoesBasicas:
    def test_soma(self, calc):
        assert "12" in calc.run("2 + 2 * 5")

    def test_divisao(self, calc):
        r = calc.run("10 / 4")
        assert "2.5" in r

    def test_potencia(self, calc):
        r = calc.run("2 ** 10")
        assert "1024" in r

    def test_resultado_inteiro(self, calc):
        """Float que é inteiro deve aparecer sem casa decimal."""
        r = calc.run("9.0 ** 2")
        assert "81" in r
        assert "81.0" not in r


class TestFuncoesMatematicas:
    def test_sqrt(self, calc):
        r = calc.run("sqrt(144)")
        assert "12" in r

    def test_log10(self, calc):
        r = calc.run("log10(1000)")
        assert "3" in r

    def test_abs(self, calc):
        r = calc.run("abs(-42)")
        assert "42" in r

    def test_floor(self, calc):
        r = calc.run("floor(3.9)")
        assert "3" in r

    def test_factorial(self, calc):
        r = calc.run("factorial(5)")
        assert "120" in r

    def test_constante_pi(self, calc):
        r = calc.run("round(pi, 4)")
        assert "3.1416" in r


class TestModoAngular:
    def test_sin_90_graus(self, calc):
        r = calc.run("round(sin(90), 6)", mode="deg")
        assert "1" in r

    def test_cos_0_graus(self, calc):
        r = calc.run("round(cos(0), 6)", mode="deg")
        assert "1" in r

    def test_modo_rad_padrao(self, calc):
        """Sem especificar mode, deve usar radianos."""
        r = calc.run("round(sin(0), 6)")
        assert "0" in r

    def test_modo_invalido(self, calc):
        r = calc.run("sin(90)", mode="grau")
        assert "Erro" in r


class TestProtecoes:
    def test_max_power_bloqueado(self, calc):
        """9**9**9**9 travaria o processo — simpleeval deve bloquear."""
        r = calc.run("9**9**9**9")
        assert "Erro" in r

    def test_expressao_muito_longa(self, calc):
        r = calc.run("x" * 600)
        assert "Erro" in r
        assert "longa" in r

    def test_expressao_invalida(self, calc):
        r = calc.run("2 +")
        assert "Erro" in r

    def test_acesso_builtins_bloqueado(self, calc):
        """Tentativa de acesso a __builtins__ deve falhar."""
        r = calc.run("__builtins__")
        assert "Erro" in r or "REDACTED" in r or "não" in r.lower()

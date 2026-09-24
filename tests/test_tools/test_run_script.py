"""
tests/test_tools/test_run_script.py

Cobre run_script.py:
  - script existente executa e retorna stdout
  - script inexistente retorna erro gracioso
  - arquivo não-.py é rejeitado
  - timeout estourado retorna status adequado
  - exit code != 0 propagado corretamente
  - separação entre stdout e stderr
  - sem saída retorna "(sem saída)"
"""

import pytest
import textwrap
from pathlib import Path

from tools.run_script import run as run_script


# ── fixture: fábrica de scripts ───────────────────────────────────────────────

@pytest.fixture
def script(tmp_path):
    """Retorna função que cria um .py no tmp_path e devolve seu path str."""
    def _make(code: str, name: str = "script.py") -> str:
        p = tmp_path / name
        p.write_text(textwrap.dedent(code), encoding="utf-8")
        return str(p)
    return _make


# ── execução bem-sucedida ─────────────────────────────────────────────────────

class TestRunScriptSuccess:
    def test_retorna_stdout(self, script):
        path = script('print("olá mundo")')
        result = run_script(path)
        assert "olá mundo" in result

    def test_retorna_stdout_multiline(self, script):
        path = script('print("linha 1")\nprint("linha 2")')
        result = run_script(path)
        assert "linha 1" in result
        assert "linha 2" in result

    def test_sem_saida_retorna_placeholder(self, script):
        path = script("x = 1 + 1")
        result = run_script(path)
        assert result == "(sem saída)"

    def test_args_passados_ao_script(self, script):
        path = script(
            "import sys\n"
            'print(" ".join(sys.argv[1:]))'
        )
        result = run_script(path, args=["hello", "world"])
        assert "hello world" in result

    def test_exit_code_0_nao_indica_erro(self, script):
        path = script('print("ok")')
        result = run_script(path)
        assert "falhou" not in result.lower()
        assert "exit" not in result.lower()


# ── erros graciosos ───────────────────────────────────────────────────────────

class TestRunScriptErrors:
    def test_arquivo_inexistente_retorna_erro(self, tmp_path):
        result = run_script(str(tmp_path / "nao_existe.py"))
        assert "Erro" in result
        assert "não encontrado" in result

    def test_extensao_nao_py_rejeitada(self, tmp_path):
        f = tmp_path / "script.sh"
        f.write_text("echo hello")
        result = run_script(str(f))
        assert "Erro" in result
        assert ".py" in result or "Python" in result

    def test_extensao_txt_rejeitada(self, tmp_path):
        f = tmp_path / "script.txt"
        f.write_text('print("x")')
        result = run_script(str(f))
        assert "Erro" in result

    def test_extensao_sem_sufixo_rejeitada(self, tmp_path):
        f = tmp_path / "script"
        f.write_text('print("x")')
        result = run_script(str(f))
        assert "Erro" in result


# ── exit code != 0 ────────────────────────────────────────────────────────────

class TestRunScriptExitCode:
    def test_exit_code_diferente_de_zero(self, script):
        path = script("import sys\nsys.exit(42)")
        result = run_script(path)
        assert "falhou" in result.lower() or "exit" in result.lower()
        assert "42" in result

    def test_erro_de_execucao_python(self, script):
        path = script("raise ValueError('erro intencional')")
        result = run_script(path)
        assert "falhou" in result.lower() or "exit" in result.lower()

    def test_stderr_incluido_na_falha(self, script):
        path = script(
            "import sys\n"
            "sys.stderr.write('mensagem de erro\\n')\n"
            "sys.exit(1)"
        )
        result = run_script(path)
        assert "mensagem de erro" in result or "falhou" in result.lower()


# ── separação stdout / stderr ─────────────────────────────────────────────────

class TestRunScriptOutputSeparation:
    def test_saida_normal_sem_stderr(self, script):
        path = script('print("saída limpa")')
        result = run_script(path)
        assert "saída limpa" in result

    def test_script_que_imprime_em_stderr_mas_exit_0(self, script):
        # Quando exit code é 0, retorna stdout mesmo com stderr presente
        path = script(
            "import sys\n"
            "sys.stderr.write('aviso\\n')\n"
            'print("resultado")'
        )
        result = run_script(path)
        assert "resultado" in result


# ── timeout ───────────────────────────────────────────────────────────────────

class TestRunScriptTimeout:
    def test_timeout_estourado_retorna_mensagem(self, script):
        path = script("import time\ntime.sleep(60)")
        result = run_script(path, timeout=1)
        assert "Erro" in result
        assert "tempo" in result.lower() or "timeout" in result.lower() or "limite" in result.lower()

    def test_timeout_padrao_e_aceito(self, script):
        # garante que timeout padrão (120s) não quebra a assinatura
        path = script('print("rápido")')
        result = run_script(path)
        assert "rápido" in result

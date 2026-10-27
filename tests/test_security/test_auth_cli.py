"""Testes do comando de reset de senha (auth/cli.py e o atalho em ciel.py).

O `tty` é injetável justamente para os testes não dependerem de um terminal
de verdade; `--sim` é o caminho de automação.
"""

import json
import sys
from pathlib import Path

import pytest

import auth.cli as cli
import auth.manager as am


@pytest.fixture
def secrets_path(tmp_path, monkeypatch):
    path = tmp_path / "secrets.json"
    monkeypatch.setattr(am, "SECRETS_PATH", path)
    return path


class TestConfirmacao:
    def test_sem_tty_e_sem_sim_recusa(self, secrets_path, capsys):
        assert cli.main([], tty=False) == 2

        assert not secrets_path.exists()
        assert "sem terminal interativo" in capsys.readouterr().err

    def test_tty_recusando_nao_altera(self, secrets_path, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda *a: "nao")

        assert cli.main([], tty=True) == 1

        assert not secrets_path.exists()
        assert "cancelado" in capsys.readouterr().out

    def test_tty_confirmando_reseta(self, secrets_path, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda *a: "resetar")

        assert cli.main([], tty=True) == 0

        assert "senha padrão ativa" in capsys.readouterr().out
        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert guardado["ciel_auth"]["is_default"] is True

    def test_resposta_diferente_cancela(self, secrets_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *a: "sim")

        assert cli.main([], tty=True) == 1
        assert not secrets_path.exists()


class TestSim:
    def test_nao_pede_confirmacao(self, secrets_path, monkeypatch):
        def explode(*a):
            raise AssertionError("não deveria pedir confirmação")

        monkeypatch.setattr("builtins.input", explode)

        assert cli.main(["--sim"], tty=False) == 0

    def test_funciona_com_arquivo_ausente(self, secrets_path):
        assert cli.main(["--sim"]) == 0
        assert secrets_path.is_file()

    def test_preserva_providers(self, secrets_path):
        secrets_path.write_text(
            json.dumps({"providers": {"x": {"api_key": "KEEP"}}}),
            encoding="utf-8",
        )

        assert cli.main(["--sim"]) == 0

        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert guardado["providers"]["x"]["api_key"] == "KEEP"


class TestFalhaDeGravacao:
    def test_sem_permissao_sai_1_e_nao_altera(self, secrets_path, monkeypatch, capsys):
        secrets_path.write_text(json.dumps({"providers": {}}), encoding="utf-8")
        antes = secrets_path.read_text(encoding="utf-8")

        def nega(*args, **kwargs):
            raise PermissionError(13, "Permission denied", "secrets")

        monkeypatch.setattr(Path, "write_text", nega)

        assert cli.main(["--sim"]) == 1

        assert "sem permissão" in capsys.readouterr().err
        assert secrets_path.read_text(encoding="utf-8") == antes


class TestAtalhoNoCielPy:
    def test_ciel_delega_para_o_comando_de_reset(self, secrets_path, monkeypatch):
        import ciel

        monkeypatch.setattr(
            sys, "argv", ["ciel.py", "--reset-password", "--sim"],
        )

        with pytest.raises(SystemExit) as exc:
            ciel.main()

        assert exc.value.code == 0
        assert secrets_path.is_file()

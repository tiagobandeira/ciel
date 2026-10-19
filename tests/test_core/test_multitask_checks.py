"""
tests/test_core/test_multitask_checks.py

Cobre `multitask/checks.py`: arquivo, comando, http, json, listas,
segurança de path/cwd e contexto de correção.
"""

import json
import sys
from pathlib import Path

import pytest

from multitask.checks import (
    CheckResult,
    build_correction_context,
    run_check,
    run_checks,
)


@pytest.fixture
def ws(tmp_path):
    path = tmp_path / "ws"
    path.mkdir()
    (path / "index.html").write_text(
        "<!doctype html><html><body>ok</body></html>", encoding="utf-8"
    )
    (path / "dados.json").write_text(
        json.dumps({"itens": [1, 2], "nome": "teste"}), encoding="utf-8"
    )
    (path / "quebrado.json").write_text("{nao é json", encoding="utf-8")
    (path / "vazio.txt").write_text("", encoding="utf-8")
    sub = path / "sub"
    sub.mkdir()
    (sub / "arquivo.txt").write_text("dentro", encoding="utf-8")
    return path


# ── casos base ────────────────────────────────────────────────────────────

class TestBase:
    def test_none_significa_sem_checagem(self, ws):
        result = run_checks(None, workspace_root=ws)
        assert result.ok is True
        assert result.verificado is False

    def test_string_e_manual(self, ws):
        result = run_checks("conferir visualmente", workspace_root=ws)
        assert result.ok is True
        assert result.verificado is False
        assert "visualmente" in result.mensagem

    def test_tipo_desconhecido_falha(self, ws):
        result = run_check({"tipo": "magia"}, workspace_root=ws)
        assert result.ok is False
        assert "desconhecido" in result.mensagem


# ── arquivo ───────────────────────────────────────────────────────────────

class TestArquivo:
    def test_existe(self, ws):
        result = run_check(
            {"tipo": "arquivo", "path": "index.html"}, workspace_root=ws
        )
        assert result.ok is True
        assert result.detalhes["path"] == "index.html"

    def test_ausente(self, ws):
        result = run_check(
            {"tipo": "arquivo", "path": "nao.md"}, workspace_root=ws
        )
        assert result.ok is False
        assert "não existe" in result.mensagem

    def test_existe_false(self, ws):
        result = run_check(
            {"tipo": "arquivo", "path": "nao.md", "existe": False},
            workspace_root=ws,
        )
        assert result.ok is True

    def test_existe_false_quando_existe(self, ws):
        result = run_check(
            {"tipo": "arquivo", "path": "index.html", "existe": False},
            workspace_root=ws,
        )
        assert result.ok is False

    def test_contem(self, ws):
        ok = run_check(
            {"tipo": "arquivo", "path": "index.html", "contem": "<html"},
            workspace_root=ws,
        )
        assert ok.ok is True

        fail = run_check(
            {"tipo": "arquivo", "path": "index.html", "contem": "python"},
            workspace_root=ws,
        )
        assert fail.ok is False
        assert "não contém" in fail.mensagem

    def test_nao_contem(self, ws):
        ok = run_check(
            {"tipo": "arquivo", "path": "index.html", "nao_contem": "TODO"},
            workspace_root=ws,
        )
        assert ok.ok is True

        fail = run_check(
            {"tipo": "arquivo", "path": "index.html", "nao_contem": "html"},
            workspace_root=ws,
        )
        assert fail.ok is False
        assert "proibido" in fail.mensagem

    def test_tamanho_min(self, ws):
        result = run_check(
            {"tipo": "arquivo", "path": "vazio.txt", "tamanho_min": 10},
            workspace_root=ws,
        )
        assert result.ok is False

    def test_path_fora_do_workspace(self, ws):
        result = run_check(
            {"tipo": "arquivo", "path": "../segredo.txt"}, workspace_root=ws
        )
        assert result.ok is False
        assert "fora do workspace" in result.mensagem

    def test_absoluto_fora_do_workspace(self, ws, tmp_path):
        result = run_check(
            {"tipo": "arquivo", "path": str(tmp_path / "fora.txt")},
            workspace_root=ws,
        )
        assert result.ok is False

    def test_diretorio_em_vez_de_arquivo(self, ws):
        result = run_check(
            {"tipo": "arquivo", "path": "sub"}, workspace_root=ws
        )
        assert result.ok is False


# ── comando ───────────────────────────────────────────────────────────────

class TestComando:
    def test_exit_zero(self, ws):
        result = run_check(
            {"tipo": "comando", "cmd": [sys.executable, "-c", "print('ok')"]},
            workspace_root=ws,
        )
        assert result.ok is True
        assert "retornou 0" in result.mensagem
        assert "ok" in result.detalhes["stdout"]

    def test_exit_esperado(self, ws):
        result = run_check(
            {
                "tipo": "comando",
                "cmd": [sys.executable, "-c", "raise SystemExit(3)"],
                "esperado": 3,
            },
            workspace_root=ws,
        )
        assert result.ok is True

    def test_exit_diferente(self, ws):
        result = run_check(
            {
                "tipo": "comando",
                "cmd": [sys.executable, "-c", "raise SystemExit(2)"],
            },
            workspace_root=ws,
        )
        assert result.ok is False
        assert result.detalhes["exit_code"] == 2

    def test_cwd(self, ws):
        result = run_check(
            {
                "tipo": "comando",
                "cmd": [sys.executable, "-c", "print('x')"],
                "cwd": "sub",
            },
            workspace_root=ws,
        )
        assert result.ok is True
        assert result.detalhes["cwd"] == "sub"

    def test_cwd_fora_do_workspace(self, ws):
        result = run_check(
            {
                "tipo": "comando",
                "cmd": [sys.executable, "-c", "print('x')"],
                "cwd": "..",
            },
            workspace_root=ws,
        )
        assert result.ok is False
        assert "fora do workspace" in result.mensagem

    def test_timeout(self, ws):
        result = run_check(
            {
                "tipo": "comando",
                "cmd": [sys.executable, "-c", "import time; time.sleep(2)"],
                "timeout": 1,
            },
            workspace_root=ws,
        )
        assert result.ok is False
        assert "excedeu" in result.mensagem

    def test_comando_string_shell(self, ws):
        result = run_check(
            {"tipo": "comando", "cmd": f'"{sys.executable}" -c "print(1)"'},
            workspace_root=ws,
        )
        assert result.ok is True

    def test_cmd_ausente(self, ws):
        result = run_check({"tipo": "comando"}, workspace_root=ws)
        assert result.ok is False


# ── http ──────────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class TestHttp:
    def test_status_esperado(self, ws, monkeypatch):
        calls = []

        def fake_request(method, url, timeout, allow_redirects):
            calls.append((method, url, timeout))
            return FakeResponse(200, "ok")

        monkeypatch.setattr("multitask.checks.requests.request", fake_request)
        result = run_check(
            {"tipo": "http", "url": "http://127.0.0.1:8000/"}, workspace_root=ws
        )
        assert result.ok is True
        assert result.detalhes["status"] == 200
        assert calls[0][0] == "GET"

    def test_status_diferente(self, ws, monkeypatch):
        monkeypatch.setattr(
            "multitask.checks.requests.request",
            lambda *a, **k: FakeResponse(500, "erro"),
        )
        result = run_check(
            {"tipo": "http", "url": "http://127.0.0.1:8000/", "esperado": 200},
            workspace_root=ws,
        )
        assert result.ok is False
        assert "HTTP 500" in result.mensagem

    def test_corpo_contem(self, ws, monkeypatch):
        monkeypatch.setattr(
            "multitask.checks.requests.request",
            lambda *a, **k: FakeResponse(200, "hello world"),
        )
        result = run_check(
            {
                "tipo": "http",
                "url": "http://127.0.0.1:8000/",
                "corpo_contem": "world",
            },
            workspace_root=ws,
        )
        assert result.ok is True

        fail = run_check(
            {
                "tipo": "http",
                "url": "http://127.0.0.1:8000/",
                "corpo_contem": "ausente",
            },
            workspace_root=ws,
        )
        assert fail.ok is False

    def test_erro_de_rede(self, ws, monkeypatch):
        import requests

        def fake_request(*a, **k):
            raise requests.ConnectionError("recusada")

        monkeypatch.setattr("multitask.checks.requests.request", fake_request)
        result = run_check(
            {"tipo": "http", "url": "http://127.0.0.1:9/"}, workspace_root=ws
        )
        assert result.ok is False
        assert "requisição" in result.mensagem

    def test_url_invalida(self, ws):
        result = run_check(
            {"tipo": "http", "url": "ftp://x"}, workspace_root=ws
        )
        assert result.ok is False


# ── json ──────────────────────────────────────────────────────────────────

class TestJson:
    def test_json_valido(self, ws):
        result = run_check(
            {"tipo": "json", "path": "dados.json"}, workspace_root=ws
        )
        assert result.ok is True
        assert "itens" in result.detalhes["chaves"]

    def test_json_invalido(self, ws):
        result = run_check(
            {"tipo": "json", "path": "quebrado.json"}, workspace_root=ws
        )
        assert result.ok is False
        assert "inválido" in result.mensagem

    def test_chaves_obrigatorias(self, ws):
        result = run_check(
            {
                "tipo": "json",
                "path": "dados.json",
                "chaves": ["itens", "ausente"],
            },
            workspace_root=ws,
        )
        assert result.ok is False
        assert "ausente" in result.mensagem

    def test_arquivo_ausente(self, ws):
        result = run_check(
            {"tipo": "json", "path": "nao.json"}, workspace_root=ws
        )
        assert result.ok is False


# ── lista ─────────────────────────────────────────────────────────────────

class TestLista:
    def test_todas_passam(self, ws):
        result = run_checks(
            [
                {"tipo": "arquivo", "path": "index.html"},
                {"tipo": "json", "path": "dados.json"},
            ],
            workspace_root=ws,
        )
        assert result.ok is True
        assert result.tipo == "lista"
        assert len(result.detalhes["checks"]) == 2

    def test_para_na_primeira_falha(self, ws):
        result = run_checks(
            [
                {"tipo": "arquivo", "path": "nao.md"},
                {"tipo": "json", "path": "dados.json"},
            ],
            workspace_root=ws,
        )
        assert result.ok is False
        assert len(result.detalhes["checks"]) == 1


# ── contexto de correção ──────────────────────────────────────────────────

class TestCorrecao:
    def test_inclui_erro_e_arquivo(self, ws):
        check = run_check(
            {"tipo": "arquivo", "path": "index.html", "contem": "python"},
            workspace_root=ws,
        )
        context = build_correction_context(check, workspace_root=ws)
        assert "Correção automática" in context
        assert "não contém" in context
        assert "index.html" in context
        assert "<!doctype html>" in context

    def test_inclui_artefatos_da_task(self, ws):
        check = CheckResult(
            ok=False, tipo="arquivo", mensagem="falhou",
            detalhes={"path": "index.html"},
        )

        class Task:
            artefatos = [{"path": "vazio.txt"}, "../segredo.txt"]

        context = build_correction_context(check, task=Task(), workspace_root=ws)
        assert "vazio.txt" in context
        assert "../segredo.txt" not in context

    def test_respeita_max_chars(self, ws):
        check = run_check(
            {"tipo": "arquivo", "path": "index.html", "contem": "x"},
            workspace_root=ws,
        )
        context = build_correction_context(
            check, workspace_root=ws, max_chars=80
        )
        assert len(context) <= 80

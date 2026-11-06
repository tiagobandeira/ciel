"""
tests/test_core/test_consumo_api.py

Contrato de GET /api/consumo (Ajustes → consumo e painel da sessão), uso
persistido por sessão e bloqueio quando a cota da sessão é atingida.
"""

import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def amb(monkeypatch, tmp_path):
    import contexto
    import server

    monkeypatch.setattr(server, "_is_authenticated", lambda: True)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "CONFIG_PATH", tmp_path / "ciel_config.json")
    monkeypatch.setattr(server, "USO_PATH", tmp_path / "data" / "session_usage.json")
    monkeypatch.setattr(contexto, "CONFIG_PATH", tmp_path / "ciel_config.json")
    monkeypatch.setattr(server, "state", SimpleNamespace(
        perfil="local", model="gemma4:cloud", model_label="local · gemma4:cloud",
        session_id=12, tokens_in=100, tokens_out=20,
        reload_tools_for_request=lambda: None,
    ))
    (tmp_path / "data").mkdir(parents=True)
    server.app.config.update(TESTING=True)
    return server, server.app.test_client(), tmp_path


def _gravar_uso(raiz, dados):
    (raiz / "data" / "session_usage.json").write_text(
        json.dumps(dados), encoding="utf-8")


class TestConsumo:
    def test_contrato(self, amb):
        _, cliente, raiz = amb
        (raiz / "data" / "secondary_quota.json").write_text(
            json.dumps({"12": {"tokens": 1_000, "chars": 3_000}}), encoding="utf-8")
        (raiz / "data" / "secondary_limite.json").write_text(
            json.dumps({"origem": "provedor", "subtipo": "rate_limit",
                        "detalhe": "HTTP 429"}), encoding="utf-8")

        r = cliente.get("/api/consumo")
        dados = r.get_json()

        assert r.status_code == 200
        assert dados["perfil"] == "local"
        assert dados["contexto"]["teto_tokens"] == 32_000
        assert dados["contexto"]["teto_perfil"] == 32_000
        assert dados["contexto"]["anexo"]["previa_chars"] == 2_000
        assert dados["contexto"]["avisos"] == [0.8, 0.95]
        assert dados["sessao"]["id"] == 12
        assert dados["sessao"]["entrada"] == 0
        assert dados["sessao"]["cota_tokens"] == 1_000_000
        assert dados["sessao"]["pct_cota"] == 0
        assert dados["secundario"]["cota_tokens"] == 1_000_000
        assert dados["secundario"]["usado_tokens"] == 1_000
        assert dados["secundario"]["restante"] == 999_000
        assert dados["secundario"]["pct"] == 0.1
        assert dados["limite"]["origem"] == "provedor"

    def test_quota_secundaria_legada_em_chars(self, amb):
        _, cliente, raiz = amb
        (raiz / "data" / "secondary_quota.json").write_text(
            json.dumps({"12": 9_000}), encoding="utf-8")

        dados = cliente.get("/api/consumo").get_json()

        assert dados["secundario"]["usado_tokens"] == 3_000

    def test_sem_limite_registrado(self, amb):
        _, cliente, _ = amb

        assert cliente.get("/api/consumo").get_json()["limite"] is None

    def test_exige_login(self, amb, monkeypatch):
        servidor, cliente, _ = amb
        monkeypatch.setattr(servidor, "_is_authenticated", lambda: False)

        assert cliente.get("/api/consumo").status_code == 401


class TestUsoDaSessao:
    def test_acumula_e_persiste(self, amb):
        servidor, cliente, _ = amb

        servidor._registrar_uso(12, 1_000, 50)
        servidor._registrar_uso(12, 2_000, 100)

        uso = servidor._uso_da_sessao(12)
        assert uso["entrada"] == 3_000
        assert uso["saida"] == 150
        assert uso["ultimo_entrada"] == 2_000

        dados = cliente.get("/api/consumo").get_json()["sessao"]
        assert dados["entrada"] == 3_000
        assert dados["ultimo_entrada"] == 2_000
        assert dados["pct_cota"] == 0.3
        assert dados["pct_contexto"] == round(2_000 / 32_000 * 100, 1)

    def test_sessao_diferente_nao_soma(self, amb):
        servidor, _, _ = amb
        servidor._registrar_uso(12, 1_000, 10)
        servidor._registrar_uso(13, 5_000, 10)

        assert servidor._uso_da_sessao(12)["entrada"] == 1_000
        assert servidor._uso_da_sessao(13)["entrada"] == 5_000

    def test_arquivo_corrompido_nao_quebra(self, amb):
        servidor, _, raiz = amb
        (raiz / "data" / "session_usage.json").write_text("{nao é json", encoding="utf-8")

        assert servidor._uso_da_sessao(12)["entrada"] == 0

    def test_aviso_publicado_uma_vez_por_faixa(self, amb, monkeypatch):
        servidor, _, _ = amb
        publicados = []
        monkeypatch.setattr(servidor.ui_bus, "publish",
                            lambda tipo, **d: publicados.append((tipo, d)))
        servidor._registrar_uso(12, 800_000, 0)

        uso = servidor._uso_da_sessao(12)
        servidor._avisar_cota_sessao(12, uso, 1_000_000)
        servidor._avisar_cota_sessao(12, servidor._uso_da_sessao(12), 1_000_000)

        assert len(publicados) == 1
        assert publicados[0][0] == "cota"
        assert publicados[0][1]["aviso"] == 0.8
        assert publicados[0][1]["pct"] == 80.0
        assert servidor._uso_da_sessao(12)["aviso"] == 0.8


class TestBloqueioDaSessao:
    def test_cota_atingida_bloqueia_o_turno(self, amb):
        _, cliente, raiz = amb
        _gravar_uso(raiz, {"12": {"entrada": 1_000_000, "saida": 0}})

        r = cliente.post("/api/chat", json={
            "message": "oi", "session_id": 12, "turn_id": "t1",
        })
        dados = r.get_json()

        assert r.status_code == 429
        assert "cota da sessão" in dados["error"]
        assert dados["limite"] == {
            "origem": "sessao", "usado": 1_000_000, "teto": 1_000_000,
        }

    def test_comando_continua_liberado(self, amb, monkeypatch):
        servidor, cliente, raiz = amb
        _gravar_uso(raiz, {"12": {"entrada": 1_000_000, "saida": 0}})
        chamado = {}

        def fake_handle(user_input, **kwargs):
            chamado["cmd"] = user_input
            return "sessão salva", False

        monkeypatch.setattr(servidor, "handle_command", fake_handle)

        r = cliente.post("/api/chat", json={
            "message": "/history salvar", "session_id": 12, "turn_id": "t2",
        })

        assert r.status_code == 200
        assert chamado["cmd"].startswith("/history")

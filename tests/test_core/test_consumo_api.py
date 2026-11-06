"""
tests/test_core/test_consumo_api.py

Contrato de GET /api/consumo, que alimenta Ajustes → consumo no site.
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
    monkeypatch.setattr(contexto, "CONFIG_PATH", tmp_path / "ciel_config.json")
    monkeypatch.setattr(server, "state", SimpleNamespace(
        perfil="local", model="gemma4:cloud", model_label="local · gemma4:cloud",
        session_id=12, tokens_in=100, tokens_out=20,
    ))
    (tmp_path / "data").mkdir(parents=True)
    server.app.config.update(TESTING=True)
    return server, server.app.test_client(), tmp_path


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
        assert dados["sessao"] == {"id": 12, "tokens_in": 100, "tokens_out": 20}
        assert dados["secundario"] == {
            "cota_tokens": 12_000, "usado_tokens": 1_000, "restante": 11_000,
        }
        assert dados["limite"]["origem"] == "provedor"

    def test_quota_legada_em_chars(self, amb):
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

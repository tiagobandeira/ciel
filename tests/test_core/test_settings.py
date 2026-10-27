"""Testes dos ajustes (/api/settings): leitura sem segredo, escrita com allowlist.

Não sobe servidor: usa o test client do Flask com um `state` falso e um
secrets.json temporário — nada toca a configuração real da máquina.
"""

import json

import pytest

import server


class EstadoFalso:
    model       = "modelo-teste"
    model_label = "modelo-teste"
    perfil      = "local"
    agent_id    = "general"
    agent_info  = {"name": "General Assistant", "description": "teste"}
    tools       = {"read_file": {}, "write_file": {}}
    force_safe  = False

    def aplicar_perfil(self, perfil):
        # dublê do AppState: sem provider configurado, nuvem falha como na vida real
        if perfil == "nuvem":
            raise RuntimeError("perfil nuvem exige um provider configurado")
        self.perfil = "local"
        self.model_label = self.model

    def reload_tools_for_request(self):
        pass


@pytest.fixture
def secrets_tmp(tmp_path, monkeypatch):
    import trust.secrets as ts
    caminho = tmp_path / "secrets.json"
    monkeypatch.setattr(ts, "_SECRETS_FILE", caminho)
    return caminho


@pytest.fixture
def cliente(tmp_path, monkeypatch, secrets_tmp):
    monkeypatch.setattr(server, "state", EstadoFalso())
    monkeypatch.setattr(server, "CONFIG_PATH", tmp_path / "ciel_config.json")
    monkeypatch.setattr(server, "PROVIDERS_PATH", tmp_path / "providers.json")
    monkeypatch.setattr(server, "_modelos_ollama", lambda: ["gemma4:cloud"])
    monkeypatch.setattr(server, "_nuvem_disponivel", lambda modelo: False)
    monkeypatch.setattr(server, "_is_authenticated", lambda: True)
    (tmp_path / "providers.json").write_text(
        json.dumps({"providers": [
            {"id": "nvidia", "name": "NVIDIA", "base_url": "https://x/v1",
             "model": "m", "needs_key": True, "key_url": "https://k"},
            {"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434/v1",
             "model": "llama3.2", "needs_key": False},
        ]}),
        encoding="utf-8",
    )
    return server.app.test_client()


class TestLeitura:
    def test_nao_devolve_nenhuma_chave(self, cliente):
        with cliente.get("/api/settings") as r:
            assert r.status_code == 200
            corpo = r.get_data(as_text=True)

        assert "api_key" not in corpo
        assert '"tem_chave"' in corpo

    def test_provider_comeca_sem_chave(self, cliente):
        d = cliente.get("/api/settings").get_json()

        nvidia = next(p for p in d["providers"] if p["id"] == "nvidia")
        assert nvidia["tem_chave"] is False
        assert nvidia["needs_key"] is True
        assert d["configurados"] == []

    def test_devolve_modelos_e_caminhos(self, cliente):
        d = cliente.get("/api/settings").get_json()

        assert d["model"] == "modelo-teste"
        assert d["ollama"] == ["gemma4:cloud"]
        assert set(d["caminhos"]) == {"workspace", "historico", "segredos"}
        assert d["repo"].startswith("https://")


class TestModelo:
    def test_sem_login_da_401(self, cliente, monkeypatch):
        monkeypatch.setattr(server, "_is_authenticated", lambda: False)

        r = cliente.put("/api/settings", json={"model": "outro"})

        assert r.status_code == 401

    def test_troca_o_modelo_e_persiste(self, cliente, tmp_path):
        r = cliente.put("/api/settings", json={"model": "qwen3:8b"})

        assert r.status_code == 200
        assert r.get_json()["model"] == "qwen3:8b"
        assert server.state.model == "qwen3:8b"
        salvo = json.loads((tmp_path / "ciel_config.json").read_text(encoding="utf-8"))
        assert salvo["web"]["model"] == "qwen3:8b"

    def test_modelo_vazio_da_400(self, cliente):
        assert cliente.put("/api/settings", json={"model": "  "}).status_code == 400

    def test_chave_fora_da_allowlist_da_400(self, cliente):
        r = cliente.put("/api/settings", json={"model": "x", "api_key": "segredo"})

        assert r.status_code == 400
        assert "api_key" in r.get_json()["error"]

    def test_preserva_o_resto_do_config(self, cliente, tmp_path):
        (tmp_path / "ciel_config.json").write_text(
            json.dumps({"base_url": "https://api.deepseek.com", "web": {"outra": 1}}),
            encoding="utf-8",
        )

        cliente.put("/api/settings", json={"model": "m2"})

        salvo = json.loads((tmp_path / "ciel_config.json").read_text(encoding="utf-8"))
        assert salvo["base_url"] == "https://api.deepseek.com"
        assert salvo["web"] == {"outra": 1, "model": "m2"}


class TestPerfil:
    def test_leitura_traz_perfil_e_disponibilidade(self, cliente):
        d = cliente.get("/api/settings").get_json()

        assert d["perfil"] == "local"
        assert d["perfil_label"] == "modelo-teste"
        assert d["nuvem_disponivel"] is False

    def test_perfil_invalido_da_400(self, cliente):
        r = cliente.put("/api/settings", json={"perfil": "build"})

        assert r.status_code == 400
        assert "perfil inválido" in r.get_json()["error"]

    def test_nuvem_sem_provider_da_400(self, cliente):
        r = cliente.put("/api/settings", json={"perfil": "nuvem"})

        assert r.status_code == 400
        assert "provider" in r.get_json()["error"]
        assert server.state.perfil == "local"

    def test_local_persiste_no_config(self, cliente, tmp_path):
        r = cliente.put("/api/settings", json={"perfil": "local"})

        assert r.status_code == 200
        assert r.get_json()["perfil"] == "local"
        salvo = json.loads((tmp_path / "ciel_config.json").read_text(encoding="utf-8"))
        assert salvo["web"]["perfil"] == "local"


class TestProvedor:
    def test_sem_login_da_401(self, cliente, monkeypatch):
        monkeypatch.setattr(server, "_is_authenticated", lambda: False)

        r = cliente.post("/api/settings/provider",
                         json={"provider": "nvidia", "api_key": "k"})

        assert r.status_code == 401


class TestProvedorAtivo:
    def _salva(self, cliente):
        return cliente.post("/api/settings/provider", json={
            "provider": "nvidia", "base_url": "https://x/v1",
            "model": "m", "api_key": "chave",
        })

    def test_lista_vazia_no_comeco(self, cliente):
        d = cliente.get("/api/settings").get_json()

        assert d["provedores_configurados"] == []
        assert d["secundario_ativo"] is None

    def test_entrada_salva_aparece_na_lista(self, cliente):
        self._salva(cliente)

        d = cliente.get("/api/settings").get_json()

        assert [p["chave"] for p in d["provedores_configurados"]] == ["nvidia:m"]
        entrada = d["provedores_configurados"][0]
        assert entrada["base_url"] == "https://x/v1"
        assert entrada["model"] == "m"

    def test_escolher_provedor_grava_no_config(self, cliente, tmp_path):
        self._salva(cliente)

        r = cliente.put("/api/settings", json={"provedor": "nvidia:m"})

        assert r.status_code == 200
        cfg = json.loads((tmp_path / "ciel_config.json").read_text(encoding="utf-8"))
        assert cfg["provider_id"] == "nvidia"
        assert cfg["model"] == "m"
        assert cfg["base_url"] == "https://x/v1"

        d = cliente.get("/api/settings").get_json()
        assert d["secundario_ativo"]["provider"] == "nvidia"
        assert d["secundario_ativo"]["model"] == "m"

    def test_provedor_desconhecido_da_400(self, cliente):
        r = cliente.put("/api/settings", json={"provedor": "foo:bar"})

        assert r.status_code == 400
        assert "não configurado" in r.get_json()["error"]

    def test_salva_e_marca_tem_chave(self, cliente, secrets_tmp):
        r = cliente.post("/api/settings/provider", json={
            "provider": "nvidia", "base_url": "https://x/v1",
            "model": "m", "api_key": "chave-de-teste",
        })

        assert r.status_code == 200
        assert r.get_json()["tem_chave"] is True
        d = cliente.get("/api/settings").get_json()
        nvidia = next(p for p in d["providers"] if p["id"] == "nvidia")
        assert nvidia["tem_chave"] is True

    def test_a_chave_vai_para_o_arquivo_e_nao_para_a_resposta(self, cliente, secrets_tmp):
        r = cliente.post("/api/settings/provider", json={
            "provider": "nvidia", "model": "m", "api_key": "chave-de-teste",
        })

        assert "chave-de-teste" not in r.get_data(as_text=True)
        guardado = json.loads(secrets_tmp.read_text(encoding="utf-8"))
        assert guardado["providers"]["nvidia:m"]["api_key"] == "chave-de-teste"

    def test_chave_vazia_em_provider_que_exige_da_400(self, cliente):
        r = cliente.post("/api/settings/provider", json={"provider": "nvidia", "api_key": ""})

        assert r.status_code == 400

    def test_provider_sem_chave_aceita_vazio(self, cliente):
        r = cliente.post("/api/settings/provider", json={"provider": "ollama", "api_key": ""})

        assert r.status_code == 200

    def test_provider_invalido_da_400(self, cliente):
        r = cliente.post("/api/settings/provider",
                         json={"provider": "../../etc", "api_key": "k"})

        assert r.status_code == 400

    def test_base_url_invalida_da_400(self, cliente):
        r = cliente.post("/api/settings/provider", json={
            "provider": "nvidia", "base_url": "javascript:alert(1)", "api_key": "k",
        })

        assert r.status_code == 400

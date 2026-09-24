"""
tests/test_security/test_model_manager.py

Cobre trust/model_manager.py — 0% cobertura, 98 stmts.
Testa: parse_secret_key, load_active_config, list_configured_providers,
get_secondary_status, activate_provider, save_provider_credentials.
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from trust.model_manager import (
    parse_secret_key,
    load_active_config,
    list_configured_providers,
    get_secondary_status,
    activate_provider,
    save_provider_credentials,
    ProviderEntry,
    SecondaryStatus,
)
from trust.secrets import SecretsManager


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sm(tmp_path):
    """SecretsManager isolado no tmp_path."""
    return SecretsManager(path=tmp_path / "secrets.json")


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """
    Redireciona _CONFIG_PATH do model_manager para um arquivo no tmp_path
    e muda o cwd para o tmp_path.
    """
    monkeypatch.chdir(tmp_path)
    import trust.model_manager as mm
    monkeypatch.setattr(mm, "_CONFIG_PATH", tmp_path / "ciel_config.json")
    return tmp_path / "ciel_config.json"


# ── parse_secret_key ─────────────────────────────────────────────────────────

class TestParseSecretKey:
    def test_formato_pid_model(self):
        pid, mdl = parse_secret_key("nvidia:deepseek-v4")
        assert pid == "nvidia"
        assert mdl == "deepseek-v4"

    def test_formato_somente_pid_sem_entry_no_secrets(self):
        """Provider sem model no secrets.json deve retornar string vazia pro model."""
        with patch("trust.model_manager.secrets") as mock_secrets:
            mock_secrets.load_provider.return_value = {}
            pid, mdl = parse_secret_key("groq")
        assert pid == "groq"
        assert mdl == ""

    def test_formato_somente_pid_com_model_no_secrets(self):
        """Provider com model em secrets.json deve retornar esse model."""
        with patch("trust.model_manager.secrets") as mock_secrets:
            mock_secrets.load_provider.return_value = {"model": "llama-3.3-70b"}
            pid, mdl = parse_secret_key("groq")
        assert pid == "groq"
        assert mdl == "llama-3.3-70b"

    def test_dois_pontos_separa_na_primeira_ocorrencia(self):
        """'pid:model:extra' → só o primeiro ':' separa."""
        pid, mdl = parse_secret_key("nvidia:deepseek:extra")
        assert pid == "nvidia"
        assert mdl == "deepseek:extra"

    def test_formato_pid_model_com_barra(self):
        """Modelos com barra (ex: 'org/modelo') são preservados."""
        pid, mdl = parse_secret_key("nvidia:deepseek-ai/deepseek-v4")
        assert pid == "nvidia"
        assert mdl == "deepseek-ai/deepseek-v4"


# ── load_active_config ────────────────────────────────────────────────────────

class TestLoadActiveConfig:
    def test_retorna_dict_vazio_sem_arquivo(self, config_path):
        """Sem ciel_config.json deve retornar dict vazio."""
        assert load_active_config() == {}

    def test_le_arquivo_valido(self, config_path):
        cfg = {"provider_id": "groq", "model": "llama-3.3"}
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        result = load_active_config()
        assert result["provider_id"] == "groq"
        assert result["model"] == "llama-3.3"

    def test_retorna_dict_vazio_com_json_invalido(self, config_path):
        config_path.write_text("{json inválido!!!", encoding="utf-8")
        assert load_active_config() == {}

    def test_preserva_campos_extras(self, config_path):
        cfg = {"provider_id": "x", "model": "y", "timeout": 60, "max_tokens": 4096}
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        result = load_active_config()
        assert result["timeout"] == 60
        assert result["max_tokens"] == 4096


# ── list_configured_providers ─────────────────────────────────────────────────

class TestListConfiguredProviders:
    def test_retorna_lista_vazia_sem_providers(self, config_path, sm):
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert result == []

    def test_lista_um_provider(self, config_path, sm):
        sm.save_provider("groq", base_url="https://api.groq.com/openai/v1",
                         model="llama-3.3-70b", api_key="gsk-fake")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert len(result) == 1
        assert result[0].provider_id == "groq"

    def test_provider_sem_chave_has_key_false(self, config_path, sm):
        sm.save_provider("openai", base_url="https://api.openai.com/v1",
                         model="gpt-4o", api_key="")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert result[0].has_key is False

    def test_provider_com_chave_has_key_true(self, config_path, sm):
        sm.save_provider("openai", base_url="https://api.openai.com/v1",
                         model="gpt-4o", api_key="sk-real-key")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert result[0].has_key is True

    def test_short_model_e_ultima_parte_do_nome(self, config_path, sm):
        sm.save_provider("nvidia", base_url="https://integrate.api.nvidia.com/v1",
                         model="deepseek-ai/deepseek-v4-flash", api_key="nvapi-x")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert result[0].short_model == "deepseek-v4-flash"

    def test_is_active_marca_provider_do_config(self, config_path, sm):
        sm.save_provider("groq", base_url="https://api.groq.com/openai/v1",
                         model="llama-3.3-70b", api_key="gsk-fake")
        config_path.write_text(json.dumps({
            "provider_id": "groq",
            "model": "llama-3.3-70b",
        }), encoding="utf-8")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert result[0].is_active is True

    def test_is_active_false_quando_nao_e_o_ativo(self, config_path, sm):
        sm.save_provider("groq", base_url="https://api.groq.com/openai/v1",
                         model="llama-3.3-70b", api_key="gsk-fake")
        # config aponta para provider diferente
        config_path.write_text(json.dumps({
            "provider_id": "openai",
            "model": "gpt-4o",
        }), encoding="utf-8")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert result[0].is_active is False

    def test_retorna_instancias_provider_entry(self, config_path, sm):
        sm.save_provider("x", base_url="https://x.com", model="m", api_key="k")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert all(isinstance(e, ProviderEntry) for e in result)

    def test_secret_key_formato_pid_model(self, config_path, sm):
        """A secret_key deve ser 'pid:model' quando model está presente."""
        sm.save_provider("groq", base_url="https://api.groq.com/openai/v1",
                         model="llama-3.3-70b", api_key="k")
        with patch("trust.model_manager.secrets", sm):
            result = list_configured_providers()
        assert result[0].secret_key == "groq:llama-3.3-70b"


# ── get_secondary_status ─────────────────────────────────────────────────────

class TestGetSecondaryStatus:
    def test_nao_configurado_quando_sem_config_e_sem_env(self, config_path, sm, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        with patch("trust.model_manager.secrets", sm):
            status = get_secondary_status()
        assert status.configured is False
        assert status.has_key is False
        assert "não configurado" in status.label

    def test_via_env_tem_prioridade(self, config_path, sm, monkeypatch):
        monkeypatch.setenv("SECONDARY_MODEL_API_KEY", "env-key-fake")
        with patch("trust.model_manager.secrets", sm):
            status = get_secondary_status()
        assert status.configured is True
        assert status.has_key is True
        assert status.via_env is True
        assert "variável de ambiente" in status.label

    def test_configurado_via_secrets_com_chave(self, config_path, sm, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        sm.save_provider("groq", base_url="https://api.groq.com/openai/v1",
                         model="llama-3.3-70b", api_key="gsk-fake")
        config_path.write_text(json.dumps({
            "provider_id": "groq",
            "model": "groq:llama-3.3-70b",
        }), encoding="utf-8")
        with patch("trust.model_manager.secrets", sm):
            status = get_secondary_status()
        assert status.configured is True

    def test_label_sem_chave_sugere_connect(self, config_path, sm, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        # config tem provider+model mas sem chave nos secrets
        sm_vazio = SecretsManager(path=config_path.parent / "secrets_vazio.json")
        config_path.write_text(json.dumps({
            "provider_id": "groq",
            "model": "llama-3.3-70b",
        }), encoding="utf-8")
        with patch("trust.model_manager.secrets", sm_vazio):
            status = get_secondary_status()
        # sem chave: label deve mencionar o problema
        assert "chave não encontrada" in status.label or not status.has_key

    def test_legacy_config_inline(self, config_path, sm, monkeypatch):
        """ciel_config.json com api_key inline → legacy=True."""
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        config_path.write_text(json.dumps({
            "model": "deepseek-v4",
            "api_key": "sk-legada-real",
            "base_url": "https://api.x.com/v1",
        }), encoding="utf-8")
        with patch("trust.model_manager.secrets", sm):
            status = get_secondary_status()
        assert status.legacy is True
        assert status.configured is True
        assert status.has_key is True
        assert "config legada" in status.label

    def test_api_key_placeholder_nao_e_legacy(self, config_path, sm, monkeypatch):
        """api_key = 'SUA_CHAVE_AQUI' não deve ser tratada como legacy."""
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        config_path.write_text(json.dumps({
            "model": "deepseek-v4",
            "api_key": "SUA_CHAVE_AQUI",
        }), encoding="utf-8")
        with patch("trust.model_manager.secrets", sm):
            status = get_secondary_status()
        assert status.legacy is False

    def test_retorna_instancia_secondary_status(self, config_path, sm, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        with patch("trust.model_manager.secrets", sm):
            status = get_secondary_status()
        assert isinstance(status, SecondaryStatus)

    def test_short_model_vazio_quando_sem_modelo(self, config_path, sm, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        with patch("trust.model_manager.secrets", sm):
            status = get_secondary_status()
        assert status.short_model == ""

    def test_short_model_parte_final_do_nome(self, config_path, sm, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        sm_vazio = SecretsManager(path=config_path.parent / "s.json")
        config_path.write_text(json.dumps({
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash",
        }), encoding="utf-8")
        with patch("trust.model_manager.secrets", sm_vazio):
            status = get_secondary_status()
        assert status.short_model == "deepseek-v4-flash"


# ── activate_provider ─────────────────────────────────────────────────────────

class TestActivateProvider:
    def test_cria_config_novo(self, config_path):
        err = activate_provider("groq", "llama-3.3-70b", "https://api.groq.com/openai/v1")
        assert err is None
        data = json.loads(config_path.read_text())
        assert data["provider_id"] == "groq"
        assert data["model"] == "llama-3.3-70b"
        assert data["base_url"] == "https://api.groq.com/openai/v1"

    def test_remove_api_key_inline(self, config_path):
        """api_key não deve ser persistida em ciel_config.json."""
        config_path.write_text(json.dumps({"api_key": "sk-antiga"}), encoding="utf-8")
        activate_provider("groq", "llama", "https://x.com")
        data = json.loads(config_path.read_text())
        assert "api_key" not in data

    def test_preserva_campos_extras_existentes(self, config_path):
        """timeout e max_tokens existentes não devem ser apagados."""
        config_path.write_text(json.dumps({
            "timeout": 120,
            "max_tokens": 8192,
        }), encoding="utf-8")
        activate_provider("groq", "llama", "https://x.com")
        data = json.loads(config_path.read_text())
        assert data["timeout"] == 120
        assert data["max_tokens"] == 8192

    def test_sobrescreve_provider_anterior(self, config_path):
        config_path.write_text(json.dumps({
            "provider_id": "openai",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
        }), encoding="utf-8")
        activate_provider("groq", "llama-3.3", "https://api.groq.com/openai/v1")
        data = json.loads(config_path.read_text())
        assert data["provider_id"] == "groq"
        assert data["model"] == "llama-3.3"

    def test_retorna_none_em_sucesso(self, config_path):
        result = activate_provider("groq", "llama", "https://x.com")
        assert result is None

    def test_retorna_erro_quando_path_invalido(self):
        import trust.model_manager as mm
        original = mm._CONFIG_PATH
        try:
            mm._CONFIG_PATH = Path("/caminho/inexistente/impossivel/ciel_config.json")
            result = activate_provider("groq", "llama", "https://x.com")
            assert result is not None  # deve retornar string de erro
        finally:
            mm._CONFIG_PATH = original

    def test_arquivo_escrito_com_utf8(self, config_path):
        activate_provider("groq", "llama", "https://api.groq.com/openai/v1")
        # deve ser legível como UTF-8 sem erro
        content = config_path.read_text(encoding="utf-8")
        assert "groq" in content


# ── save_provider_credentials ─────────────────────────────────────────────────

class TestSaveProviderCredentials:
    def test_salva_com_secrets_manager_fornecido(self, tmp_path):
        sm = SecretsManager(path=tmp_path / "secrets.json")
        save_provider_credentials(
            "groq", "llama-3.3-70b",
            "https://api.groq.com/openai/v1", "gsk-fake",
            sm=sm,
        )
        cfg = sm.load_provider("groq", "llama-3.3-70b")
        assert cfg is not None
        assert cfg["api_key"] == "gsk-fake"
        assert cfg["base_url"] == "https://api.groq.com/openai/v1"

    def test_usa_secrets_global_quando_sm_e_none(self, tmp_path):
        """Sem sm= fornecido, usa o secrets global."""
        sm_global = SecretsManager(path=tmp_path / "global_secrets.json")
        with patch("trust.model_manager.secrets", sm_global):
            save_provider_credentials(
                "nvidia", "deepseek-v4",
                "https://integrate.api.nvidia.com/v1", "nvapi-x",
                sm=None,
            )
        cfg = sm_global.load_provider("nvidia", "deepseek-v4")
        assert cfg is not None
        assert cfg["api_key"] == "nvapi-x"

    def test_salva_base_url_corretamente(self, tmp_path):
        sm = SecretsManager(path=tmp_path / "s.json")
        save_provider_credentials(
            "openai", "gpt-4o",
            "https://api.openai.com/v1", "sk-fake",
            sm=sm,
        )
        cfg = sm.load_provider("openai", "gpt-4o")
        assert cfg["base_url"] == "https://api.openai.com/v1"
        assert cfg["model"] == "gpt-4o"

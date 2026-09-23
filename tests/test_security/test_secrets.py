"""
tests/test_tools/test_secrets.py

Cobre SecretsManager: save/load/delete de providers, chave composta
provider:model (múltiplos modelos do mesmo provedor), resolve_api_key
com prioridade env var → secrets.json → ciel_config.json.

Este teste foi motivado pelo bug do /analisar onde skill_import._call_secondary
não achava a chave depois de migrar as credenciais pro SecretsManager.
"""

import json
import os
import tempfile
import pytest
from pathlib import Path
from trust.secrets import SecretsManager


@pytest.fixture
def sm(tmp_path):
    """SecretsManager isolado em arquivo temporário."""
    return SecretsManager(path=tmp_path / "secrets.json")


class TestSaveLoad:
    def test_salva_e_recupera(self, sm):
        sm.save_provider("groq", base_url="https://api.groq.com/v1",
                         model="llama-3", api_key="gsk-fake")
        cfg = sm.load_provider("groq")
        assert cfg is not None
        assert cfg["api_key"] == "gsk-fake"
        assert cfg["model"] == "llama-3"

    def test_varios_modelos_mesmo_provedor(self, sm):
        """NVIDIA gera chave por modelo — cada par provider:model é independente."""
        sm.save_provider("nvidia", base_url="https://integrate.api.nvidia.com/v1",
                         model="deepseek-v4", api_key="nvapi-key-deepseek")
        sm.save_provider("nvidia", base_url="https://integrate.api.nvidia.com/v1",
                         model="llama-3.1-70b", api_key="nvapi-key-llama")

        k1 = sm.get_api_key("nvidia", "deepseek-v4")
        k2 = sm.get_api_key("nvidia", "llama-3.1-70b")
        assert k1 == "nvapi-key-deepseek"
        assert k2 == "nvapi-key-llama"
        assert k1 != k2

    def test_lista_providers(self, sm):
        sm.save_provider("groq", base_url="https://api.groq.com/v1",
                         model="llama-3", api_key="gsk-fake")
        sm.save_provider("nvidia", base_url="https://integrate.api.nvidia.com/v1",
                         model="deepseek-v4", api_key="nvapi-fake")
        providers = sm.list_providers()
        assert len(providers) == 2

    def test_delete_provider(self, sm):
        sm.save_provider("groq", base_url="https://api.groq.com/v1",
                         model="llama-3", api_key="gsk-fake")
        sm.delete_provider("groq")
        assert sm.load_provider("groq") is None

    def test_arquivo_chmod_600(self, sm, tmp_path):
        """Arquivo de secrets deve ter permissão restrita (só dono lê)."""
        sm.save_provider("groq", base_url="x", model="y", api_key="z")
        path = tmp_path / "secrets.json"
        if os.name != "nt":  # chmod não existe no Windows
            assert (path.stat().st_mode & 0o177) == 0

    def test_persiste_entre_instancias(self, tmp_path):
        path = tmp_path / "secrets.json"
        sm1 = SecretsManager(path=path)
        sm1.save_provider("groq", base_url="https://api.groq.com/v1",
                          model="llama-3", api_key="gsk-fake-123")

        sm2 = SecretsManager(path=path)
        cfg = sm2.load_provider("groq")
        assert cfg is not None
        assert cfg["api_key"] == "gsk-fake-123"


class TestResolveApiKey:
    """
    resolve_api_key deve seguir a prioridade:
    1. env var  2. secrets.json por provider:model  3. secrets por provider  4. ciel_config.json
    """

    def test_env_var_tem_prioridade(self, sm, monkeypatch):
        sm.save_provider("groq", base_url="https://api.groq.com/v1",
                         model="llama-3", api_key="gsk-do-secrets")
        monkeypatch.setenv("TEST_KEY", "from-env-var")
        key = sm.resolve_api_key("groq", env_var="TEST_KEY")
        assert key == "from-env-var"

    def test_secrets_quando_sem_env(self, sm):
        sm.save_provider("groq", base_url="https://api.groq.com/v1",
                         model="llama-3", api_key="gsk-do-secrets")
        key = sm.resolve_api_key("groq", model="llama-3", env_var="VAR_INEXISTENTE")
        assert key == "gsk-do-secrets"

    def test_chave_especifica_modelo(self, sm):
        """Deve retornar a chave do modelo específico, não uma chave genérica."""
        sm.save_provider("nvidia", base_url="x", model="deepseek-v4",
                         api_key="nvapi-deepseek")
        sm.save_provider("nvidia", base_url="x", model="llama-3.1-70b",
                         api_key="nvapi-llama")
        key = sm.resolve_api_key("nvidia", model="deepseek-v4")
        assert key == "nvapi-deepseek"

    def test_fallback_ciel_config(self, sm, tmp_path, monkeypatch):
        """Retrocompatibilidade: usa api_key do ciel_config.json se não tiver em secrets."""
        cfg_path = tmp_path / "ciel_config.json"
        cfg_path.write_text(json.dumps({"api_key": "chave-do-config-antigo"}))
        monkeypatch.chdir(tmp_path)
        key = sm.resolve_api_key("provedor_sem_secrets", env_var="VAR_INEXISTENTE")
        assert key == "chave-do-config-antigo"

    def test_vazio_quando_nada_configurado(self, sm):
        key = sm.resolve_api_key("provedor_inexistente", env_var="VAR_INEXISTENTE")
        assert key == ""

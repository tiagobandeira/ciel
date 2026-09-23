"""
tests/test_tools/test_skill_import.py

Cobre a função _call_secondary do skill_import — especificamente
a resolução de api_key via SecretsManager (o bug que encontramos
onde /analisar quebrava depois de migrar credenciais via /connect).
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture(scope="module")
def skill_import_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "skill_import", Path("tools/skill_import.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def config_basico(tmp_path, monkeypatch):
    """Cria um ciel_config.json mínimo e muda o cwd pro tmp."""
    monkeypatch.chdir(tmp_path)
    cfg = {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "provider_id": "groq",
    }
    (tmp_path / "ciel_config.json").write_text(json.dumps(cfg))
    return tmp_path


class TestResolucaoApiKey:
    def test_resolve_via_secrets(self, skill_import_mod, config_basico, tmp_path):
        """
        Bug original: _call_secondary não achava a chave depois de migrar
        as credenciais pro SecretsManager via /connect.
        Agora deve resolver via secrets.resolve_api_key.
        """
        from trust.secrets import SecretsManager
        sm = SecretsManager(path=tmp_path / "secrets.json")
        sm.save_provider("groq", base_url="https://api.groq.com/openai/v1",
                         model="llama-3.3-70b-versatile", api_key="gsk-fake-key-123")

        cfg_mock = {
            "base_url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile",
            "provider_id": "groq",
        }

        # mock do requests pra não fazer chamada real
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "resposta mock"}}]
        }
        mock_response.raise_for_status = MagicMock()

        # patch em trust.secrets.secrets (onde _call_secondary faz o import a cada chamada)
        # + patch em _load_config para isolar do ciel_config.json real do projeto
        with patch("trust.secrets.secrets", sm), \
             patch.object(skill_import_mod, "_load_config", return_value=cfg_mock), \
             patch("requests.post", return_value=mock_response) as mock_post:
            resultado = skill_import_mod._call_secondary("teste de prompt")

        # deve ter chamado a API (encontrou a chave)
        assert mock_post.called
        # a chave deve estar no header de autorização
        auth_header = str(mock_post.call_args)
        assert "gsk-fake-key-123" in auth_header

    def test_retorna_none_sem_chave(self, skill_import_mod, config_basico, tmp_path, monkeypatch):
        """Sem api_key em lugar nenhum, _call_secondary deve retornar None graciosamente."""
        from trust.secrets import SecretsManager
        sm_vazio = SecretsManager(path=tmp_path / "secrets_vazio.json")
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)

        with patch("trust.secrets.secrets", sm_vazio):
            resultado = skill_import_mod._call_secondary("teste")
        assert resultado is None

    def test_env_var_tem_prioridade(self, skill_import_mod, config_basico, tmp_path, monkeypatch):
        """Env var deve ser usada mesmo se secrets.json tiver uma chave diferente."""
        monkeypatch.setenv("SECONDARY_MODEL_API_KEY", "from-env-var-fake")
        from trust.secrets import SecretsManager
        sm = SecretsManager(path=tmp_path / "secrets.json")
        sm.save_provider("groq", base_url="https://api.groq.com/openai/v1",
                         model="llama-3.3-70b-versatile", api_key="gsk-do-secrets")

        with patch("trust.secrets.secrets", sm):
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "ok"}}]
            }
            mock_response.raise_for_status = MagicMock()

            with patch("requests.post", return_value=mock_response) as mock_post:
                skill_import_mod._call_secondary("prompt teste")

            auth_header = str(mock_post.call_args)
            assert "from-env-var-fake" in auth_header


class TestConfigInvalida:
    def test_sem_ciel_config(self, skill_import_mod, tmp_path, monkeypatch):
        """Sem ciel_config.json, _call_secondary deve retornar None sem travar."""
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)

        # _load_config usa _ROOT hardcoded (ignora chdir), então patchamos direto
        with patch.object(skill_import_mod, "_load_config", return_value={}), \
             patch("trust.secrets.secrets") as mock_secrets:
            mock_secrets.resolve_api_key.return_value = ""
            resultado = skill_import_mod._call_secondary("teste")

        assert resultado is None

    def test_config_sem_base_url(self, skill_import_mod, tmp_path, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)

        # config sem base_url: _call_secondary deve retornar None antes de chamar a API
        with patch.object(skill_import_mod, "_load_config", return_value={"model": "x"}), \
             patch("trust.secrets.secrets") as mock_secrets:
            mock_secrets.resolve_api_key.return_value = ""
            resultado = skill_import_mod._call_secondary("teste")

        assert resultado is None
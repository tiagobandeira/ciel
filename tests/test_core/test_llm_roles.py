"""
tests/test_core/test_llm_roles.py

Cobre `llm/roles.py` sem tocar em ~/.ciel/secrets.json nem no config real.
Todos os testes usam config temporário + SecretsManager falso.
"""

import json
from pathlib import Path

import pytest

from llm.client import OllamaClient, OpenAICompatClient
from llm.roles import (
    ModelSpec,
    RoleConfig,
    load_roles,
    secondary_spec,
)


# ── dublês ────────────────────────────────────────────────────────────────

class FakeSecrets:
    def __init__(self, providers: dict | None = None):
        self.providers = providers or {}

    def load_provider(self, name: str, model: str = "") -> dict | None:
        key = f"{name}:{model}" if model else name
        if key in self.providers:
            return self.providers[key]
        if name in self.providers:
            return self.providers[name]
        for k, v in self.providers.items():
            if k.startswith(f"{name}:"):
                return v
        return None

    def get_api_key(self, name: str, model: str = "") -> str:
        cfg = self.load_provider(name, model) or {}
        return cfg.get("api_key", "")


def write_config(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "ciel_config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


NV_SECRETS = FakeSecrets({
    "nvidia:deepseek-ai/deepseek-v4-flash-0731": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "deepseek-ai/deepseek-v4-flash-0731",
        "api_key": "nvapi-segredo",
    },
})


# ── defaults preservam o comportamento atual ──────────────────────────────

class TestDefaults:
    def test_sem_config_so_local(self, tmp_path):
        roles = load_roles(
            "gemma4:cloud",
            config_path=tmp_path / "nao_existe.json",
            secrets_manager=FakeSecrets(),
        )
        assert roles.orchestrator is not None
        assert roles.orchestrator.provider == "ollama"
        assert roles.orchestrator.model == "gemma4:cloud"
        assert roles.worker.model == "gemma4:cloud"
        assert roles.planner is None
        assert roles.secondary_available is False
        assert roles.perfil == "local"

    def test_secundario_vira_planner_reviewer_reporter(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
        })
        roles = load_roles(
            "gemma4:cloud", config_path=cfg, secrets_manager=NV_SECRETS,
        )
        assert roles.secondary_available is True
        assert roles.orchestrator.provider == "ollama"       # perfil local
        assert roles.planner.provider == "nvidia"
        assert roles.reviewer.provider == "nvidia"
        assert roles.reporter.provider == "nvidia"
        assert roles.planner.model == "deepseek-ai/deepseek-v4-flash-0731"

    def test_legacy_api_key_inline(self, tmp_path):
        cfg = write_config(tmp_path, {
            "base_url": "https://api.exemplo.test/v1",
            "model": "modelo-x",
            "api_key": "chave-inline",
        })
        roles = load_roles("m", config_path=cfg, secrets_manager=FakeSecrets())
        assert roles.planner is not None
        assert roles.planner.provider == "custom"
        assert roles.planner.api_key == "chave-inline"

    def test_placeholder_nao_configura(self, tmp_path):
        cfg = write_config(tmp_path, {
            "base_url": "https://api.exemplo.test/v1",
            "model": "modelo-x",
            "api_key": "SUA_CHAVE_AQUI",
        })
        roles = load_roles("m", config_path=cfg, secrets_manager=FakeSecrets())
        assert roles.planner is None

    def test_provider_sem_chave_nao_configura(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
        })
        roles = load_roles("m", config_path=cfg, secrets_manager=FakeSecrets())
        assert roles.planner is None

    def test_provider_local_dispensa_chave(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "9router",
            "model": "kr/claude-sonnet-4.5",
            "base_url": "http://localhost:20128/v1",
        })
        roles = load_roles("m", config_path=cfg, secrets_manager=FakeSecrets())
        assert roles.planner is not None
        assert roles.planner.provider == "9router"


# ── perfil build ──────────────────────────────────────────────────────────

class TestPerfilBuild:
    def test_build_promove_secundario_a_orquestrador(self, tmp_path):
        cfg = write_config(tmp_path, {
            "perfil": "build",
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
        })
        roles = load_roles("gemma4:cloud", config_path=cfg, secrets_manager=NV_SECRETS)
        assert roles.perfil == "build"
        assert roles.orchestrator.provider == "nvidia"
        assert roles.worker.provider == "nvidia"
        assert roles.planner.provider == "nvidia"

    def test_build_sem_secundario_cai_no_local(self, tmp_path):
        cfg = write_config(tmp_path, {"perfil": "build"})
        roles = load_roles("gemma4:cloud", config_path=cfg, secrets_manager=FakeSecrets())
        assert roles.orchestrator.provider == "ollama"
        assert roles.worker.provider == "ollama"

    def test_perfil_invalido_vira_local(self, tmp_path):
        cfg = write_config(tmp_path, {"perfil": "turbo"})
        roles = load_roles("m", config_path=cfg, secrets_manager=FakeSecrets())
        assert roles.perfil == "local"

    def test_parametro_build_vence_config_local(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
        })
        roles = load_roles(
            "gemma4:cloud", config_path=cfg, secrets_manager=NV_SECRETS,
            perfil="build",
        )
        assert roles.perfil == "build"
        assert roles.worker.provider == "nvidia"

    def test_parametro_local_vence_config_build(self, tmp_path):
        cfg = write_config(tmp_path, {
            "perfil": "build",
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
        })
        roles = load_roles(
            "gemma4:cloud", config_path=cfg, secrets_manager=NV_SECRETS,
            perfil="local",
        )
        assert roles.perfil == "local"
        assert roles.worker.provider == "ollama"


# ── overrides de roles ────────────────────────────────────────────────────

class TestOverrides:
    def test_worker_em_outro_provider(self, tmp_path):
        cfg = write_config(tmp_path, {
            "roles": {
                "worker": {
                    "provider": "groq",
                    "base_url": "https://api.groq.com/openai/v1",
                    "model": "llama-3.3-70b-versatile",
                }
            }
        })
        sm = FakeSecrets({"groq": {"api_key": "gsk-x"}})
        roles = load_roles("local-model", config_path=cfg, secrets_manager=sm)

        assert roles.worker.provider == "groq"
        assert roles.worker.model == "llama-3.3-70b-versatile"
        assert roles.worker.api_key == "gsk-x"
        assert roles.orchestrator.provider == "ollama"  # não mudou

    def test_override_ollama_usa_modelo_local(self, tmp_path):
        cfg = write_config(tmp_path, {
            "roles": {"planner": {"provider": "ollama", "model": "qwen3:8b"}}
        })
        roles = load_roles("gemma4:cloud", config_path=cfg, secrets_manager=FakeSecrets())
        assert roles.planner.provider == "ollama"
        assert roles.planner.model == "qwen3:8b"
        assert roles.planner.base_url == "http://localhost:11434"

    def test_override_invalido_e_ignorado(self, tmp_path):
        cfg = write_config(tmp_path, {
            "roles": {"planner": {"provider": "openrouter"}}
        })
        roles = load_roles("m", config_path=cfg, secrets_manager=FakeSecrets())
        # sem base_url utilizável nem chave → cai no default (secundário ausente)
        assert roles.planner is None

    def test_env_var_do_provider_ativo(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "api_key_env": "MINHA_CHAVE",
        })
        roles = load_roles(
            "m", config_path=cfg, secrets_manager=FakeSecrets(),
            env={"MINHA_CHAVE": "chave-do-ambiente"},
        )
        assert roles.planner.api_key == "chave-do-ambiente"

    def test_env_var_nao_vaza_para_outro_provider(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "api_key_env": "MINHA_CHAVE",
            "roles": {
                "worker": {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "model": "x/y",
                }
            },
        })
        roles = load_roles(
            "m", config_path=cfg, secrets_manager=FakeSecrets(),
            env={"MINHA_CHAVE": "chave-nvidia"},
        )
        # openrouter não herdou a chave da nvidia; override inválido é
        # ignorado e o papel cai no default local (nunca fica sem worker)
        assert roles.worker.provider == "ollama"
        assert roles.worker.api_key == ""


# ── segurança e utilitários ───────────────────────────────────────────────

class TestSecurity:
    def test_api_key_fora_do_repr_e_do_dict(self):
        spec = ModelSpec(
            role="planner", provider="x", model="m",
            base_url="https://x", api_key="segredo-123",
        )
        assert "segredo-123" not in repr(spec)
        assert "api_key" not in spec.to_dict()

    def test_to_dict_da_role_config_e_seguro(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
        })
        roles = load_roles("m", config_path=cfg, secrets_manager=NV_SECRETS)
        dumped = json.dumps(roles.to_dict())
        assert "nvapi-segredo" not in dumped

    def test_client_do_spec(self, tmp_path):
        local = ModelSpec(role="w", provider="ollama", model="m", base_url="http://localhost:11434")
        cloud = ModelSpec(role="w", provider="nvidia", model="m", base_url="https://x/v1", api_key="k")
        assert isinstance(local.client(), OllamaClient)
        assert isinstance(cloud.client(), OpenAICompatClient)

    def test_require_levanta_quando_ausente(self):
        roles = RoleConfig()
        with pytest.raises(Exception):
            roles.require("planner")

    def test_secondary_spec_atalho(self, tmp_path):
        cfg = write_config(tmp_path, {
            "provider_id": "nvidia",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "base_url": "https://integrate.api.nvidia.com/v1",
        })
        spec = secondary_spec(config_path=cfg, secrets_manager=NV_SECRETS)
        assert spec is not None
        assert spec.provider == "nvidia"
        assert spec.client().model == "deepseek-ai/deepseek-v4-flash-0731"

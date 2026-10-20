"""
llm/roles.py — resolução de papéis de modelo do Ciel.

Um "papel" responde à pergunta "quem pensa o quê":

    orchestrator → conduz o turno de chat (tools, respostas)
    worker       → executa uma task do multitask
    planner      → gera o plano/quadro
    reviewer     → revisa uma fase (opcional)
    reporter     → escreve a mensagem final (opcional)
    escalation   → modelo mais forte sob demanda (opcional)

O comportamento padrão é idêntico ao de hoje: orquestrador/worker no Ollama
(argumento `--model`) e papéis de julgamento no provider secundário já
configurado via `/connect`. Nada muda sem configuração explícita.

Configuração opcional em `ciel_config.json`:

    "perfil": "nuvem",          // "local" (default) | "nuvem" (antes "build")
    "roles": {
      "worker":  {"provider": "nvidia", "model": "deepseek-ai/..."},
      "planner": {"provider": "nvidia", "model": "nvidia/nemotron-..."}
    }

"perfil": "nuvem" usa o provider secundário também como orquestrador/worker;
qualquer override em `roles` vence o perfil. Chaves nunca entram em repr,
log ou `to_dict()`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

PERFIL_LOCAL = "local"
PERFIL_NUVEM = "nuvem"


def normalize_perfil(value) -> str:
    """Canoniza o perfil: `build`/`cloud` são aliases antigos de `nuvem`."""
    raw = str(value or os.environ.get("CIEL_PERFIL", "") or "local").strip().lower()
    if raw in ("nuvem", "cloud", "build"):
        return PERFIL_NUVEM
    return PERFIL_LOCAL

from typing import Any
from urllib.parse import urlparse

from llm.client import (
    DEFAULT_OLLAMA_BASE,
    DEFAULT_OLLAMA_TIMEOUT,
    DEFAULT_OPENAI_TIMEOUT,
    BaseClient,
    LLMError,
    make_client,
)

ROLE_NAMES = (
    "orchestrator",
    "worker",
    "planner",
    "reviewer",
    "reporter",
    "escalation",
)

_LOCAL_PROVIDERS = {"ollama", "local", ""}
_NO_KEY_PROVIDERS = {"ollama", "local", "9router"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}
_PLACEHOLDER_KEYS = {"", "SUA_CHAVE_AQUI", "SUA_CHAVE", "sua_chave_aqui"}

DEFAULT_LOCAL_MODEL = "gemma4:cloud"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "ciel_config.json"
DEFAULT_PROVIDERS_PATH = Path(__file__).resolve().parent.parent / "providers.json"


# ── especificação de um modelo ────────────────────────────────────────────

@dataclass
class ModelSpec:
    """Um modelo concreto que um papel pode usar."""

    role: str
    provider: str
    model: str
    base_url: str = ""
    # repr=False: a chave não pode vazar em log/traceback/print de debug.
    api_key: str = field(default="", repr=False)
    timeout: float | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    source: str = ""          # local | secondary | config

    @property
    def is_local(self) -> bool:
        return self.provider.strip().lower() in ("ollama", "local")

    @property
    def short_model(self) -> str:
        return (self.model or "").split("/")[-1]

    @property
    def label(self) -> str:
        prefix = "local" if self.is_local else (self.provider or "cloud")
        return f"{prefix} · {self.short_model}" if self.short_model else prefix

    def client(self) -> BaseClient:
        """Instancia o cliente HTTP correspondente (sem imprimir nada)."""
        return make_client(
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            timeout=self.timeout,
            max_tokens=self.max_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        """Versão segura para log/UI — nunca inclui api_key."""
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "source": self.source,
        }


@dataclass
class RoleConfig:
    """Mapa papel → ModelSpec resolvido para a sessão."""

    roles: dict[str, ModelSpec] = field(default_factory=dict)
    perfil: str = "local"
    secondary_available: bool = False
    config_path: str = ""

    # acesso ─────────────────────────────────────────────────────────────
    def get(self, role: str, default: ModelSpec | None = None) -> ModelSpec | None:
        return self.roles.get(role, default)

    def require(self, role: str) -> ModelSpec:
        spec = self.roles.get(role)
        if spec is None:
            raise LLMError(
                f"papel '{role}' não configurado — use /connect ou defina "
                f"'roles.{role}' em ciel_config.json"
            )
        return spec

    def __contains__(self, role: str) -> bool:
        return role in self.roles

    def __getitem__(self, role: str) -> ModelSpec:
        return self.require(role)

    @property
    def orchestrator(self) -> ModelSpec | None:
        return self.roles.get("orchestrator")

    @property
    def worker(self) -> ModelSpec | None:
        return self.roles.get("worker")

    @property
    def planner(self) -> ModelSpec | None:
        return self.roles.get("planner")

    @property
    def reviewer(self) -> ModelSpec | None:
        return self.roles.get("reviewer")

    @property
    def reporter(self) -> ModelSpec | None:
        return self.roles.get("reporter")

    def available(self) -> dict[str, ModelSpec]:
        return dict(self.roles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "perfil": self.perfil,
            "secondary_available": self.secondary_available,
            "config_path": self.config_path,
            "roles": {name: spec.to_dict() for name, spec in self.roles.items()},
        }


# ── leitura de config/providers/secrets ───────────────────────────────────

def _read_config(config_path: str | Path | None) -> dict:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists() and not config_path:
        # fallback: respeita quem roda de outro diretório (testes, server)
        path = Path("ciel_config.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _default_secrets():
    try:
        from trust.secrets import secrets
        return secrets
    except Exception:
        return None


def _provider_defaults(provider_id: str) -> dict:
    """Lê base_url/model default de providers.json (sem credencial)."""
    if not provider_id:
        return {}
    try:
        data = json.loads(DEFAULT_PROVIDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    for entry in data.get("providers", []):
        if entry.get("id") == provider_id:
            return {
                "base_url": entry.get("base_url", ""),
                "model": entry.get("model", ""),
                "needs_key": bool(entry.get("needs_key", True)),
            }
    return {}


def _needs_key(provider: str, base_url: str) -> bool:
    pid = (provider or "").strip().lower()
    if pid in _NO_KEY_PROVIDERS:
        return False
    try:
        host = (urlparse(base_url or "").hostname or "").lower()
    except Exception:
        host = ""
    if host in _LOCAL_HOSTS:
        return False
    return True


def _resolve_key(
    provider: str,
    model: str,
    *,
    cfg: dict,
    secrets_manager,
    env: dict | None = None,
) -> str:
    """
    Mesma ordem de prioridade de `secondary_model`:
    env → secrets por provider:model → secrets por provider → config legada.
    """
    env = os.environ if env is None else env
    env_var = (cfg.get("api_key_env") or "").strip()
    active_provider = (cfg.get("provider_id") or "").strip()

    # a env só vale para o provider ativo (não vaza a chave do secundário
    # para um provider diferente configurado em `roles`)
    if env_var and provider == active_provider:
        value = (env.get(env_var) or "").strip()
        if value:
            return value

    if secrets_manager is not None:
        try:
            key = secrets_manager.get_api_key(provider, model)
            if key:
                return key
            key = secrets_manager.get_api_key(provider)
            if key:
                return key
        except Exception:
            pass

    inline = (cfg.get("api_key") or "").strip()
    if inline and inline not in _PLACEHOLDER_KEYS:
        return inline
    return ""


def _secondary_spec(
    cfg: dict,
    secrets_manager,
    env: dict | None = None,
) -> ModelSpec | None:
    """
    Deriva o provider secundário ativo (o mesmo que `/connect` + `/model`
    salvam). Retorna None se não houver base_url/model utilizáveis.
    """
    provider = (cfg.get("provider_id") or "").strip()
    model    = (cfg.get("model") or "").strip()
    base_url = (cfg.get("base_url") or "").strip()

    if not provider and base_url and model:
        provider = "custom"          # config legada: só base_url/model/api_key

    defaults = _provider_defaults(provider)
    if secrets_manager is not None and provider:
        try:
            stored = secrets_manager.load_provider(provider, model) or {}
        except Exception:
            stored = {}
        base_url = base_url or (stored.get("base_url") or "")
        model    = model    or (stored.get("model") or "")

    base_url = base_url or defaults.get("base_url", "")
    model    = model    or defaults.get("model", "")

    if not base_url or not model:
        return None

    key = _resolve_key(
        provider, model,
        cfg=cfg, secrets_manager=secrets_manager, env=env,
    )
    if _needs_key(provider, base_url) and not key:
        return None

    return ModelSpec(
        role="",
        provider=provider or "custom",
        model=model,
        base_url=base_url,
        api_key=key,
        timeout=float(cfg.get("timeout") or DEFAULT_OPENAI_TIMEOUT),
        max_tokens=cfg.get("max_tokens"),
        temperature=cfg.get("temperature"),
        source="secondary",
    )


def _spec_from_entry(
    role: str,
    entry: Any,
    *,
    cfg: dict,
    local: ModelSpec,
    secrets_manager,
    env: dict | None = None,
) -> ModelSpec | None:
    """Converte uma entrada de `roles` em ModelSpec; None se inválida."""
    if isinstance(entry, str):
        entry = {"provider": entry}
    if not isinstance(entry, dict):
        return None

    provider = str(
        entry.get("provider") or entry.get("provider_id") or "ollama"
    ).strip()
    model    = str(entry.get("model") or "").strip()
    base_url = str(entry.get("base_url") or "").strip()

    if provider.lower() in _LOCAL_PROVIDERS:
        return ModelSpec(
            role=role,
            provider="ollama",
            model=model or local.model,
            base_url=base_url or local.base_url,
            timeout=entry.get("timeout", local.timeout),
            max_tokens=entry.get("max_tokens"),
            temperature=entry.get("temperature"),
            source="config",
        )

    defaults = _provider_defaults(provider)
    stored: dict = {}
    if secrets_manager is not None:
        try:
            stored = secrets_manager.load_provider(provider, model) or {}
        except Exception:
            stored = {}

    base_url = base_url or (stored.get("base_url") or "") or defaults.get("base_url", "")
    model    = model or (stored.get("model") or "") or defaults.get("model", "")
    if not base_url or not model:
        return None

    key = _resolve_key(
        provider, model,
        cfg=cfg, secrets_manager=secrets_manager, env=env,
    )
    if _needs_key(provider, base_url) and not key:
        return None

    return ModelSpec(
        role=role,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=key,
        timeout=float(entry.get("timeout") or cfg.get("timeout") or DEFAULT_OPENAI_TIMEOUT),
        max_tokens=entry.get("max_tokens", cfg.get("max_tokens")),
        temperature=entry.get("temperature"),
        source="config",
    )


# ── API principal ─────────────────────────────────────────────────────────

def load_roles(
    local_model: str = DEFAULT_LOCAL_MODEL,
    *,
    config_path: str | Path | None = None,
    secrets_manager=None,
    ollama_url: str | None = None,
    env: dict | None = None,
    perfil: str | None = None,
) -> RoleConfig:
    """
    Resolve todos os papéis para a sessão.

    `perfil` sobrescreve o `perfil` do config (usado por um fluxo que declara
    `perfil: nuvem` sem exigir mudar o `ciel_config.json`).

    Nunca levanta por config ausente/inválida: no pior caso devolve só o
    orquestrador local, que é o comportamento histórico do Ciel.
    """
    cfg = _read_config(config_path)
    sm  = secrets_manager if secrets_manager is not None else _default_secrets()

    local = ModelSpec(
        role="orchestrator",
        provider="ollama",
        model=(local_model or cfg.get("local_model") or DEFAULT_LOCAL_MODEL).strip(),
        base_url=ollama_url or cfg.get("ollama_url") or DEFAULT_OLLAMA_BASE,
        timeout=float(cfg.get("local_timeout") or DEFAULT_OLLAMA_TIMEOUT),
        source="local",
    )

    secondary = _secondary_spec(cfg, sm, env=env)
    perfil_raw = perfil if perfil is not None else cfg.get("perfil")
    perfil = normalize_perfil(perfil_raw)

    overrides = cfg.get("roles")
    if not isinstance(overrides, dict):
        overrides = {}

    roles: dict[str, ModelSpec] = {}
    for role in ROLE_NAMES:
        spec: ModelSpec | None = None

        if role in overrides and not str(role).startswith("_"):
            spec = _spec_from_entry(
                role, overrides[role],
                cfg=cfg, local=local, secrets_manager=sm, env=env,
            )

        if spec is None:
            if role in ("orchestrator", "worker"):
                if perfil == PERFIL_NUVEM and secondary is not None:
                    spec = replace(secondary, role=role)
                else:
                    spec = replace(local, role=role)
            elif role in ("planner", "reviewer", "reporter", "escalation"):
                if secondary is not None:
                    spec = replace(secondary, role=role)

        if spec is not None:
            roles[role] = spec

    return RoleConfig(
        roles=roles,
        perfil=perfil,
        secondary_available=secondary is not None,
        config_path=str(Path(config_path) if config_path else DEFAULT_CONFIG_PATH),
    )


def secondary_spec(
    *,
    config_path: str | Path | None = None,
    secrets_manager=None,
    env: dict | None = None,
) -> ModelSpec | None:
    """Atalho para o provider secundário ativo (usado por /connect, planejador)."""
    return _secondary_spec(
        _read_config(config_path),
        secrets_manager if secrets_manager is not None else _default_secrets(),
        env=env,
    )


__all__ = [
    "ROLE_NAMES",
    "ModelSpec",
    "RoleConfig",
    "PERFIL_LOCAL",
    "PERFIL_NUVEM",
    "normalize_perfil",
    "load_roles",
    "secondary_spec",
    "DEFAULT_LOCAL_MODEL",
]

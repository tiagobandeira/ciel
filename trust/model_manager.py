"""
trust/model_manager.py — lógica de modelo secundário compartilhada entre
CLI, TUI e futuramente o server.

Não importa nada de Rich, prompt_toolkit ou Textual — só stdlib + trust/.
Cada harness importa as funções daqui e cuida da apresentação sozinho.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from trust.secrets import SecretsManager, secrets

_CONFIG_PATH = Path("ciel_config.json")


# ── tipos de dados ─────────────────────────────────────────────────────────

@dataclass
class ProviderEntry:
    """Um provider configurado em secrets.json."""
    secret_key: str       # chave interna: "pid:model" ou "pid"
    provider_id: str
    model: str
    base_url: str
    has_key: bool         # se api_key está preenchida
    is_active: bool       # se é o secundário atual em ciel_config.json
    short_model: str      # só a parte final do nome (ex: "deepseek-v4")


@dataclass
class SecondaryStatus:
    """Estado atual do modelo secundário."""
    configured: bool
    provider_id: str
    model: str
    base_url: str
    short_model: str
    has_key: bool
    via_env: bool         # True se veio de variável de ambiente
    legacy: bool          # True se api_key ainda está inline em ciel_config.json
    label: str            # string legível pro harness exibir


# ── leitura ────────────────────────────────────────────────────────────────

def parse_secret_key(key: str) -> tuple[str, str]:
    """Separa 'pid:model' → (pid, model); 'pid' → (pid, model_do_secrets)."""
    if ":" in key:
        pid, mdl = key.split(":", 1)
        return pid, mdl
    fallback = secrets.load_provider(key, "") or {}
    return key, fallback.get("model", "")


def load_active_config() -> dict:
    """Lê ciel_config.json. Retorna dict vazio se não existir."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def list_configured_providers() -> list[ProviderEntry]:
    """
    Lista todos os providers configurados em secrets.json,
    marcando qual está ativo em ciel_config.json.
    """
    active_cfg   = load_active_config()
    active_pid   = active_cfg.get("provider_id", "")
    active_model = active_cfg.get("model", "")

    entries: list[ProviderEntry] = []
    for sk in secrets.list_providers():
        pid, mdl = parse_secret_key(sk)
        cfg      = secrets.load_provider(pid, mdl) or {}
        has_key  = bool(cfg.get("api_key", "").strip())
        is_active = (active_pid == pid and active_model == mdl)
        entries.append(ProviderEntry(
            secret_key=sk,
            provider_id=pid,
            model=mdl,
            base_url=cfg.get("base_url", ""),
            has_key=has_key,
            is_active=is_active,
            short_model=mdl.split("/")[-1] if mdl else "",
        ))
    return entries


def get_secondary_status() -> SecondaryStatus:
    """Estado atual do modelo secundário — o harness só precisa exibir."""
    active_cfg   = load_active_config()
    active_pid   = active_cfg.get("provider_id", "")
    active_model = active_cfg.get("model", "")
    via_env      = bool(os.environ.get("SECONDARY_MODEL_API_KEY", "").strip())
    legacy       = False
    configured   = False
    has_key      = False
    label        = "não configurado"

    if via_env:
        configured = True
        has_key    = True
        label      = "configurado via variável de ambiente"
    elif active_pid and active_model:
        has_key = bool(
            secrets.get_api_key(active_pid, active_model)
            or secrets.get_api_key(active_pid)
        )
        configured = True
        short = active_model.split("/")[-1]
        if has_key:
            label = f"{active_pid} · {short}"
        else:
            label = f"{active_pid} · {short} (chave não encontrada — rode /connect)"
    elif active_cfg.get("api_key", "").strip() not in ("", "SUA_CHAVE_AQUI"):
        legacy     = True
        configured = True
        has_key    = True
        short      = active_cfg.get("model", "").split("/")[-1]
        label      = f"{short} (config legada — ciel_config.json)"

    return SecondaryStatus(
        configured=configured,
        provider_id=active_pid,
        model=active_model,
        base_url=active_cfg.get("base_url", ""),
        short_model=active_model.split("/")[-1] if active_model else "",
        has_key=has_key,
        via_env=via_env,
        legacy=legacy,
        label=label,
    )


# ── escrita ────────────────────────────────────────────────────────────────

def activate_provider(provider_id: str, model: str, base_url: str) -> str | None:
    """
    Persiste o provider escolhido em ciel_config.json.
    Preserva campos extras (timeout, max_tokens…); remove api_key inline.
    Retorna None em sucesso, ou mensagem de erro.
    """
    try:
        cfg: dict = {}
        if _CONFIG_PATH.exists():
            try:
                cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        cfg["provider_id"] = provider_id
        cfg["base_url"]    = base_url
        cfg["model"]       = model
        cfg.pop("api_key", None)   # chave fica só em secrets.json

        _CONFIG_PATH.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return None
    except Exception as e:
        return str(e)


def save_provider_credentials(
    provider_id: str,
    model: str,
    base_url: str,
    api_key: str,
    sm: SecretsManager | None = None,
) -> None:
    """Salva credenciais em secrets.json via SecretsManager."""
    mgr = sm or secrets
    mgr.save_provider(provider_id, base_url=base_url, model=model, api_key=api_key)

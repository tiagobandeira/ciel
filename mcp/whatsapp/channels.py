"""
mcp/whatsapp/channels.py
========================
Config e allowlist do WhatsApp.

Persiste em whatsapp_channels.json na raiz do projeto:

{
  "bridge_url": "http://127.0.0.1:8765",
  "bot": {
    "enabled": true,
    "agent": "general",
    "allow_from": ["+55 11 99999-9999"],
    "groups": {
      "policy": "allowlist",
      "allow_from": []
    },
    "dm_policy": "allowlist"
  },
  "mcp": {
    "enabled": true
  }
}

Funções públicas:
  load()          → dict com a config completa (ou defaults se não existir)
  save(config)    → persiste a config no arquivo
  is_allowed(sender, chat_type)  → bool — decide se o roteador deve processar
  bridge_url()    → str — URL do bridge (usada pelo bot e pelo MCP)
  bot_agent()     → str — nome do agente configurado pro modo bot
  bot_enabled()   → bool
  mcp_enabled()   → bool
"""

import json
from pathlib import Path

# raiz do projeto = 3 níveis acima de mcp/whatsapp/channels.py
CONFIG_FILE = Path(__file__).parent.parent.parent / "whatsapp_channels.json"

# ── defaults ──────────────────────────────────────────────────────────────────

_DEFAULTS: dict = {
    "bridge_url": "http://127.0.0.1:8765",
    "bot": {
        "enabled": False,
        "agent": "general",
        "allow_from": [],          # fail-closed: sem allowlist = ninguém entra
        "groups": {
            "policy": "allowlist", # "allowlist" | "mention_only"
            "allow_from": [],
        },
        "dm_policy": "allowlist",  # "allowlist" | "pairing"
    },
    "mcp": {
        "enabled": False,
    },
}


# ── I/O ───────────────────────────────────────────────────────────────────────

def load() -> dict:
    """Carrega a config do arquivo. Retorna defaults se não existir."""
    if not CONFIG_FILE.exists():
        return _deep_copy(_DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return _merge(_DEFAULTS, data)
    except Exception:
        return _deep_copy(_DEFAULTS)


def save(config: dict) -> None:
    """Persiste a config no arquivo."""
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── accessors ─────────────────────────────────────────────────────────────────

def bridge_url() -> str:
    return load().get("bridge_url", _DEFAULTS["bridge_url"])


def bot_enabled() -> bool:
    return bool(load().get("bot", {}).get("enabled", False))


def mcp_enabled() -> bool:
    return bool(load().get("mcp", {}).get("enabled", False))


def bot_agent() -> str:
    """Nome do agente configurado pro modo bot."""
    return load().get("bot", {}).get("agent", "general")


def bot_allow_from() -> list[str]:
    """Lista de números permitidos no modo bot (DMs)."""
    return load().get("bot", {}).get("allow_from", [])


def group_policy() -> str:
    """Política de grupos: 'allowlist' ou 'mention_only'."""
    return load().get("bot", {}).get("groups", {}).get("policy", "allowlist")


def group_allow_from() -> list[str]:
    """Lista de JIDs de grupos permitidos."""
    return load().get("bot", {}).get("groups", {}).get("allow_from", [])


def dm_policy() -> str:
    """Política de DMs: 'allowlist' ou 'pairing'."""
    return load().get("bot", {}).get("dm_policy", "allowlist")


# ── roteador ─────────────────────────────────────────────────────────────────

def is_allowed(sender: str, chat_type: str) -> bool:
    """
    Decide se uma mensagem deve ser processada pelo modo bot.

    sender    : número do remetente normalizado (ex: "+55 11 99999-9999")
    chat_type : "direct" | "group"

    Regras:
    - Fail-closed: allowlist vazia bloqueia tudo.
    - DM "allowlist": sender deve estar em allow_from.
    - DM "pairing": qualquer sender é aceito (aprovação manual no primeiro contato).
    - Grupo "allowlist": chat_id deve estar em groups.allow_from.
    - Grupo "mention_only": qualquer grupo é aceito, mas o bot só responde
      quando mencionado — essa filtragem é feita no bot.py, não aqui.
    """
    cfg = load().get("bot", {})

    if chat_type == "direct":
        policy = cfg.get("dm_policy", "allowlist")
        if policy == "pairing":
            return True
        allowed = cfg.get("allow_from", [])
        if not allowed:
            return False  # fail-closed
        return _normalize(sender) in [_normalize(n) for n in allowed]

    if chat_type == "group":
        policy = cfg.get("groups", {}).get("policy", "allowlist")
        if policy == "mention_only":
            return True  # filtragem de menção fica no bot.py
        allowed = cfg.get("groups", {}).get("allow_from", [])
        if not allowed:
            return False  # fail-closed
        return _normalize(sender) in [_normalize(n) for n in allowed]

    return False


# ── setup interativo (usado pelo /canal whatsapp) ─────────────────────────────

def configure_interactive(agent_name: str, allow_from: list[str],
                          bot: bool = True, mcp: bool = False,
                          bridge_url_override: str | None = None) -> dict:
    """
    Gera e salva uma config a partir dos dados coletados pela entrevista.
    Retorna a config salva.
    """
    cfg = load()
    if bridge_url_override:
        cfg["bridge_url"] = bridge_url_override
    cfg["bot"]["enabled"]    = bot
    cfg["bot"]["agent"]      = agent_name
    cfg["bot"]["allow_from"] = allow_from
    cfg["mcp"]["enabled"]    = mcp
    save(cfg)
    return cfg


# ── helpers ───────────────────────────────────────────────────────────────────

# def _normalize(number: str) -> str:
#     """Remove espaços, traços e parênteses de um número de telefone."""
#     return "".join(c for c in number if c.isdigit() or c == "+")
def _normalize(number: str) -> str:
    """Só dígitos, com '+' na frente. Celular BR sem o 9 ganha o 9."""
    digits = "".join(c for c in number if c.isdigit())
    if digits.startswith("55") and len(digits) == 12 and digits[4] in "6789":
        digits = digits[:4] + "9" + digits[4:]
    return "+" + digits


def _deep_copy(d: dict) -> dict:
    return json.loads(json.dumps(d))


def _merge(base: dict, override: dict) -> dict:
    """Merge recursivo: override sobrescreve base, mantendo chaves ausentes."""
    result = _deep_copy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result

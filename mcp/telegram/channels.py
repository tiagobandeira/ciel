"""
mcp/telegram/channels.py
========================
Cache local de canais Telegram.

Persiste em telegram_channels.json (na mesma pasta do server.py) com:
    {
        "channels": [
            {"title": "Ciel", "id": "-1001234567890", "username": ""},
            {"title": "Dev",  "id": "-1009876543210", "username": "@devcanal"}
        ]
    }

Lookup por title (case-insensitive), id numérico ou @username.
Se não encontrar no cache, retorna None — o server.py decide o que fazer.
"""

import json
from pathlib import Path

# raiz do projeto = 3 níveis acima de mcp/telegram/channels.py
# mesmo diretório do mcp_servers.json e cli.py
CACHE_FILE = Path(__file__).parent.parent.parent / "telegram_channels.json"


def _load() -> list[dict]:
    if not CACHE_FILE.exists():
        return []
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8")).get("channels", [])
    except Exception:
        return []


def _save(channels: list[dict]) -> None:
    CACHE_FILE.write_text(
        json.dumps({"channels": channels}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find(query: str) -> dict | None:
    """
    Busca um canal pelo título (parcial, case-insensitive), id numérico ou @username.
    Retorna o dict do canal ou None se não encontrar.
    """
    q = query.strip().lower().lstrip("@")
    for ch in _load():
        if (
            q == str(ch.get("id", "")).lower()
            or q == ch.get("username", "").lower().lstrip("@")
            or q in ch.get("title", "").lower()
        ):
            return ch
    return None


def upsert(channel: dict) -> None:
    """
    Salva ou atualiza um canal no cache.
    Identifica pelo id — atualiza se já existir, insere se for novo.
    Campos esperados: id (str), title (str), username (str).
    """
    channels = _load()
    cid = str(channel.get("id", ""))
    for i, ch in enumerate(channels):
        if str(ch.get("id", "")) == cid:
            channels[i] = channel
            _save(channels)
            return
    channels.append(channel)
    _save(channels)


def list_all() -> list[dict]:
    """Retorna todos os canais do cache."""
    return _load()
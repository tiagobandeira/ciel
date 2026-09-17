"""
Registro de fontes autorizadas de input.

Cada fonte tem:
  - type:         categoria da origem (terminal, web, mobile, mcp...)
  - enabled:      se está ativa
  - capabilities: o que ela pode fazer (ver trust/capabilities.py)

Regra importante: source_type NÃO é prova de autenticidade.
O runtime confia numa fonte porque ela está registrada aqui,
não porque o campo source_type diz "terminal".
O componente que cria o InputEnvelope é responsável por atribuir
a origem correta — o conteúdo do payload nunca pode influenciar isso.

v0: só o terminal local está registrado.
Futuro: web_client, mobile, webhook, mcp_server...
"""

from __future__ import annotations
from trust.capabilities import CONVERSATION, USER_INSTRUCTION

# ── tipos de fonte conhecidos ──────────────────────────────────────────────
class SourceType:
    TERMINAL = "terminal"
    # futuro:
    # WEB      = "web"
    # MOBILE   = "mobile"
    # WEBHOOK  = "webhook"
    # MCP      = "mcp"
    # FILE     = "file"
    # BROWSER  = "browser"
    # TOOL     = "tool"
    # SYSTEM   = "system"
    # TASK     = "task"


# ── registro de fontes autorizadas ────────────────────────────────────────
SOURCE_REGISTRY: dict[str, dict] = {
    "local_terminal": {
        "type":         SourceType.TERMINAL,
        "enabled":      True,
        "capabilities": {CONVERSATION, USER_INSTRUCTION},
    },
    # Exemplo de fonte futura com capabilities limitadas:
    # "web_test": {
    #     "type":         SourceType.WEB,
    #     "enabled":      False,
    #     "capabilities": {CONVERSATION},   # sem USER_INSTRUCTION
    # },
}


def get_source(source_id: str) -> dict | None:
    """Retorna a definição da fonte ou None se não estiver registrada."""
    return SOURCE_REGISTRY.get(source_id)


def is_enabled(source_id: str) -> bool:
    src = get_source(source_id)
    return bool(src and src.get("enabled", False))

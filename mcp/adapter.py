"""
mcp/adapter.py
==============
Converte tools de um servidor MCP para o formato que o ToolRegistry do Ciel
espera — sem dependências de UI.

Responsabilidades:
  1. Converter JSON Schema (formato MCP) → lista de dicts (formato registry)
  2. Gerar um callable síncrono que encapsula SyncMCPClient.call_tool()
  3. Montar o dict completo pronto para ser inserido no registry

Nada aqui conhece rich, textual, cli.py ou ciel.py.
"""

import logging
from typing import Any, Callable

from .client import SyncMCPClient, MCPToolSchema, MCPError

logger = logging.getLogger(__name__)


# ── Mapeamento de tipos JSON Schema → Python ──────────────────────────────────

_JSON_TYPE_MAP = {
    "string":  "str",
    "integer": "int",
    "number":  "float",
    "boolean": "bool",
    "array":   "list",
    "object":  "dict",
}


def _json_type_to_python(json_type: str) -> str:
    return _JSON_TYPE_MAP.get(json_type, "str")


# ── Conversão de schema ────────────────────────────────────────────────────────

def convert_parameters(mcp_input_schema: dict) -> list[dict]:
    """
    Converte o inputSchema de uma tool MCP para o formato de parâmetros
    que o tools_registry.py gera via inspect.signature().

    Formato de entrada (JSON Schema):
        {
            "type": "object",
            "properties": {
                "text":   {"type": "string",  "description": "Texto a enviar"},
                "chat_id": {"type": "string"},
            },
            "required": ["text", "chat_id"]
        }

    Formato de saída (lista de dicts do registry):
        [
            {"name": "text",    "type": "str", "description": "Texto a enviar"},
            {"name": "chat_id", "type": "str"},
        ]
    """
    if not mcp_input_schema or not isinstance(mcp_input_schema, dict):
        return []

    properties = mcp_input_schema.get("properties", {})
    required   = set(mcp_input_schema.get("required", []))

    params = []
    for name, prop in properties.items():
        entry: dict = {"name": name}

        # tipo
        raw_type = prop.get("type", "string")
        entry["type"] = _json_type_to_python(raw_type)

        # descrição
        if desc := prop.get("description", "").strip():
            entry["description"] = desc

        # parâmetros não obrigatórios recebem default None
        # (o modelo precisa saber que pode omitir)
        if name not in required:
            entry["default"] = "None"

        params.append(entry)

    return params


# ── Gerador de callable ────────────────────────────────────────────────────────

def make_tool_callable(
    client:    SyncMCPClient,
    tool_name: str,
) -> Callable[..., str]:
    """
    Gera um callable síncrono que encapsula client.call_tool().

    O callable gerado:
      - Aceita **kwargs (o run_agent sempre passa args como dict expandido)
      - Retorna str — mesmo padrão de todas as tools do Ciel
      - Trata MCPError internamente e retorna mensagem de erro legível
        (mesmo padrão das tools em tools/: nunca propaga exceção)

    Exemplo de uso pelo run_agent:
        fn = make_tool_callable(client, "send_message")
        result = fn(chat_id="123", text="oi")   # → "ok"
    """
    def tool_fn(**kwargs) -> str:
        # remove Nones — parâmetros opcionais omitidos pelo modelo
        clean_args = {k: v for k, v in kwargs.items() if v is not None}
        try:
            result = client.call_tool(tool_name, clean_args)
            return str(result) if result is not None else "ok"
        except MCPError as e:
            return f"Erro MCP [{tool_name}]: {e}"
        except Exception as e:
            return f"Erro inesperado [{tool_name}]: {e}"

    # nomeia a função para que inspect.signature() funcione no run_agent
    # (usado para mostrar a assinatura correta quando args são inválidos)
    tool_fn.__name__ = tool_name
    tool_fn.__qualname__ = f"mcp.{tool_name}"
    return tool_fn


# ── Entrada principal ──────────────────────────────────────────────────────────

def adapt_tools(
    client:         SyncMCPClient,
    server_name:    str,
    allowed_tools:  list[str] | None = None,
) -> dict:
    """
    Conecta ao servidor, descobre as tools e retorna um dict pronto
    para ser mesclado no ToolRegistry do Ciel.

    Parâmetros:
        client       — SyncMCPClient já conectado
        server_name  — nome do servidor (usado no namespace das tools)
        allowed_tools — lista de nomes de tools MCP a incluir; None = todas

    Retorno:
        {
            "mcp_telegram__send_message": {
                "fn":          <callable>,
                "description": "Envia uma mensagem...",
                "parameters":  [...],
                "categoria":   "mcp",
                "_mcp_server": "telegram",
                "_mcp_tool":   "send_message",
            },
            ...
        }

    Nomenclatura:
        mcp_{server_name}__{tool_name}
        duplo underline separa servidor de tool — evita colisão com tools
        que tenham underline no próprio nome (ex: send_message → não vira
        mcp_telegram_send_message, que ambiguaria com server "telegram_send")
    """
    try:
        mcp_tools: list[MCPToolSchema] = client.list_tools()
    except MCPError as e:
        logger.error("Falha no discovery do servidor '%s': %s", server_name, e)
        return {}

    registry_tools = {}

    for tool in mcp_tools:
        if allowed_tools is not None and tool.name not in allowed_tools:
            logger.debug("Tool '%s' ignorada (não está em allowed_tools)", tool.name)
            continue

        registry_name = _make_registry_name(server_name, tool.name)

        # checa colisão de nome
        if registry_name in registry_tools:
            logger.warning(
                "Colisão de nome ignorada: '%s' já registrada para servidor '%s'",
                registry_name, server_name,
            )
            continue

        params   = convert_parameters(tool.parameters)
        callable_ = make_tool_callable(client, tool.name)

        registry_tools[registry_name] = {
            "fn":          callable_,
            "description": tool.description or f"Tool MCP: {tool.name}",
            "parameters":  params,
            "categoria":   "mcp",
            "_mcp_server": server_name,
            "_mcp_tool":   tool.name,
        }

        logger.info("Adaptada: %s → %s (%d params)", tool.name, registry_name, len(params))

    return registry_tools


def _make_registry_name(server_name: str, tool_name: str) -> str:
    """
    Gera o nome da tool no registry.

    Regras:
    - Prefixo 'mcp_' para fácil identificação no run_agent
    - server_name e tool_name separados por '__' (duplo underline)
    - Apenas [a-z0-9_] — sanitiza outros caracteres

    Exemplos:
        ("telegram", "send_message")  → "mcp_telegram__send_message"
        ("my-server", "doThing")      → "mcp_my_server__doThing"
    """
    safe_server = _sanitize(server_name)
    safe_tool   = _sanitize(tool_name)
    return f"mcp_{safe_server}__{safe_tool}"


def _sanitize(name: str) -> str:
    """Remove caracteres inválidos para nome de tool no registry."""
    import re
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


# ── Utilitário reverso (para logging e debug) ──────────────────────────────────

def parse_registry_name(registry_name: str) -> tuple[str, str] | None:
    """
    Faz o parse reverso de um nome do registry.

    "mcp_telegram__send_message" → ("telegram", "send_message")
    Retorna None se não for uma tool MCP.
    """
    if not registry_name.startswith("mcp_"):
        return None
    rest = registry_name[4:]  # remove "mcp_"
    if "__" not in rest:
        return None
    server, tool = rest.split("__", 1)
    return server, tool


def is_mcp_tool(registry_name: str) -> bool:
    """Retorna True se o nome corresponde a uma tool MCP."""
    return registry_name.startswith("mcp_") and "__" in registry_name[4:]

"""
mcp/
====
Pacote de integração MCP para o Ciel CLI.
Desacoplado de qualquer UI — funciona no cli.py, ciel.py (Textual) e server.py.

Imports públicos:
    from mcp import MCPManager
    from mcp import SyncMCPClient, MCPClient
    from mcp import MCPError, MCPConnectionError, MCPTimeoutError, MCPToolError

Uso mínimo no cli.py / ciel.py:
    from mcp import MCPManager

    manager = MCPManager()
    manager.connect_all()
    tools.update(manager.all_tools())
    schema = tools_schema(tools)
"""

from .client import (
    MCPClient,
    SyncMCPClient,
    MCPToolSchema,
    ServerInfo,
    Transport,
    MCPError,
    MCPConnectionError,
    MCPTimeoutError,
    MCPProtocolError,
    MCPToolError,
)
from .manager import MCPManager

__all__ = [
    # manager (ponto de entrada principal)
    "MCPManager",
    # cliente
    "MCPClient",
    "SyncMCPClient",
    "MCPToolSchema",
    "ServerInfo",
    "Transport",
    # exceções
    "MCPError",
    "MCPConnectionError",
    "MCPTimeoutError",
    "MCPProtocolError",
    "MCPToolError",
]
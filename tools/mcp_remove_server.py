"""Remove e desconecta um servidor MCP do Ciel."""

_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        from mcp.manager import MCPManager
        _manager = MCPManager()
    return _manager


def run(name: str) -> str:
    """
    name: nome do servidor a remover (mesmo usado em mcp_add_server)
    """
    manager = _get_manager()
    ok, msg = manager.remove_server(name.strip())
    return msg

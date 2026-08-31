"""Lista os servidores MCP configurados, seu status de conexão e tools disponíveis."""

_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        from mcp.manager import MCPManager
        _manager = MCPManager()
    return _manager


def run(verbose: bool = False) -> str:
    """
    verbose: se True, lista os nomes completos de cada tool de cada servidor
    """
    manager = _get_manager()
    servers = manager.list_servers()

    if not servers:
        return "Nenhum servidor MCP configurado. Use mcp_add_server para adicionar."

    lines = []
    for s in servers:
        status_icon = "●" if s["connected"] else "○"
        lines.append(f"{status_icon} {s['name']}  [{s['type']}]  {s['status']}")

        if s["server_name"]:
            lines.append(f"  servidor: {s['server_name']} v{s['version']}")

        if verbose and s["tools"]:
            for t in s["tools"]:
                lines.append(f"    • {t}")
        elif s["tools"] and not verbose:
            preview = ", ".join(s["tools"][:3])
            if len(s["tools"]) > 3:
                preview += f" ... (+{len(s['tools'])-3})"
            lines.append(f"  tools: {preview}")

        if s["error"]:
            lines.append(f"  ⚠ {s['error']}")

    return "\n".join(lines)

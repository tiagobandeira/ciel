"""Registra e conecta um novo servidor MCP ao Ciel."""

# O manager é um singleton injetado pelo MCPManager.inject_tools()
# Fallback para instância global se chamado fora desse fluxo.
_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        from mcp.manager import MCPManager
        _manager = MCPManager()
    return _manager


def run(
    name: str,
    type: str,
    command: str = None,
    args: str = None,
    url: str = None,
    env: str = None,
    timeout: float = 30.0,
    allowed_tools: str = None,
) -> str:
    """
    name: identificador único do servidor (ex: telegram, github)
    type: tipo de transporte — "stdio" ou "sse"
    command: executável do servidor (obrigatório para type=stdio)
    args: argumentos separados por espaço (ex: "-m mcp_telegram")
    url: URL do servidor (obrigatório para type=sse)
    env: variáveis de ambiente em formato KEY=VALUE separadas por vírgula (ex: BOT_TOKEN=abc,DEBUG=1)
    timeout: segundos por chamada (padrão 30)
    allowed_tools: tools a expor, separadas por vírgula — vazio = todas
    """
    config: dict = {
        "name":    name.strip(),
        "type":    type.strip(),
        "timeout": timeout,
    }

    if command:
        config["command"] = command.strip()

    if args:
        config["args"] = args.strip().split()

    if url:
        config["url"] = url.strip()

    if env:
        env_dict = {}
        for pair in env.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                env_dict[k.strip()] = v.strip()
        if env_dict:
            config["env"] = env_dict

    if allowed_tools:
        config["allowed_tools"] = [t.strip() for t in allowed_tools.split(",") if t.strip()]

    manager = _get_manager()
    ok, msg = manager.add_server(config)
    return msg

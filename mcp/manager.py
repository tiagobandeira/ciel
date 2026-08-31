"""
mcp/manager.py
==============
Gerencia o ciclo de vida dos servidores MCP e a injeção de suas tools
no ToolRegistry do Ciel.

Responsabilidades:
  - Persistir configurações em mcp_servers.json (mesmo padrão do ciel_config.json)
  - Conectar / desconectar / reconectar servidores
  - Expor adapt_tools() de cada servidor para o registry do cli.py / ciel.py / server.py

Sem dependências de UI — logging via stdlib.

Uso típico no cli.py / ciel.py:
    from mcp.manager import MCPManager

    manager = MCPManager()               # carrega mcp_servers.json se existir
    manager.connect_all()                # conecta todos os servidores configurados
    tools.update(manager.all_tools())    # injeta no registry existente

    # quando o usuário adiciona um servidor via mcp_add_server:
    manager.add_server({
        "name":    "telegram",
        "type":    "stdio",
        "command": "python",
        "args":    ["-m", "mcp_telegram"],
        "env":     {"BOT_TOKEN": "..."},
    })
    tools.update(manager.server_tools("telegram"))
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from .client import SyncMCPClient, MCPConnectionError, MCPError
from .adapter import adapt_tools, parse_registry_name, is_mcp_tool

logger = logging.getLogger(__name__)

CONFIG_FILE = Path("mcp_servers.json")

# schema de uma configuração de servidor
# {
#   "name":         str  — identificador único (vira namespace das tools)
#   "type":         "stdio" | "sse"
#   "command":      str  — executável (stdio)
#   "args":         list — argumentos do comando (stdio)
#   "url":          str  — URL do servidor (sse)
#   "env":          dict — variáveis de ambiente extras
#   "timeout":      float — segundos por chamada (padrão 30)
#   "allowed_tools": list | null — null = todas
#   "enabled":      bool — false = não conecta na inicialização
# }


class ServerEntry:
    """Estado de um servidor registrado no manager."""

    def __init__(self, config: dict):
        self.config  = config
        self.client: SyncMCPClient | None = None
        self.tools:  dict                 = {}   # registry slice deste servidor
        self.error:  str                  = ""   # último erro de conexão
        self.connected_at: float          = 0.0

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def enabled(self) -> bool:
        return self.config.get("enabled", True)

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_alive()

    def status(self) -> str:
        if self.is_connected:
            n = len(self.tools)
            return f"conectado ({n} tool{'s' if n != 1 else ''})"
        if self.error:
            return f"erro: {self.error}"
        return "desconectado"


class MCPManager:
    """
    Gerenciador central de servidores MCP.

    Thread-safety: o Ciel é single-threaded no loop principal,
    então não há locks. Se usar em contexto multi-thread, adicione
    threading.Lock em torno de _servers.
    """

    def __init__(self, config_file: Path = CONFIG_FILE):
        self._config_file = config_file
        self._servers: dict[str, ServerEntry] = {}
        self._load_config()

    # ── Persistência ───────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        if not self._config_file.exists():
            return
        try:
            data = json.loads(self._config_file.read_text(encoding="utf-8"))
            for cfg in data.get("servers", []):
                name = cfg.get("name", "")
                if not name:
                    continue
                self._servers[name] = ServerEntry(cfg)
            logger.info("mcp_servers.json carregado: %d servidor(es)", len(self._servers))
        except Exception as e:
            logger.error("Erro ao ler %s: %s", self._config_file, e)

    def _save_config(self) -> None:
        data = {"servers": [e.config for e in self._servers.values()]}
        try:
            self._config_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Erro ao salvar %s: %s", self._config_file, e)

    # ── Conexão ────────────────────────────────────────────────────────────────

    def _make_client(self, config: dict) -> SyncMCPClient:
        transport = config.get("type", "stdio")
        timeout   = float(config.get("timeout", 30.0))
        max_retry = int(config.get("max_retries", 3))

        if transport == "stdio":
            return SyncMCPClient.stdio(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env", {}),
                timeout=timeout,
                max_retries=max_retry,
            )
        elif transport == "sse":
            return SyncMCPClient.sse(
                url=config["url"],
                headers=config.get("headers", {}),
                timeout=timeout,
                max_retries=max_retry,
            )
        else:
            raise ValueError(f"Tipo de transporte desconhecido: '{transport}'")

    def _connect_entry(self, entry: ServerEntry) -> bool:
        """
        Tenta conectar um servidor e fazer discovery das tools.
        Retorna True se bem-sucedido.
        """
        name = entry.name
        try:
            client = self._make_client(entry.config)
            info   = client.connect()
            tools  = adapt_tools(
                client,
                server_name=name,
                allowed_tools=entry.config.get("allowed_tools"),
            )
            entry.client       = client
            entry.tools        = tools
            entry.error        = ""
            entry.connected_at = time.time()
            logger.info(
                "Servidor '%s' conectado: %s v%s — %d tool(s)",
                name, info.name, info.version, len(tools),
            )
            return True
        except MCPConnectionError as e:
            entry.error = str(e)
            logger.error("Falha ao conectar '%s': %s", name, e)
            return False
        except Exception as e:
            entry.error = str(e)
            logger.error("Erro inesperado ao conectar '%s': %s", name, e)
            return False

    def connect_all(self) -> dict[str, bool]:
        """
        Conecta todos os servidores habilitados.
        Retorna dict {nome: sucesso}.
        Chamado uma vez na inicialização do Ciel.
        """
        results = {}
        for name, entry in self._servers.items():
            if not entry.enabled:
                logger.info("Servidor '%s' desabilitado — pulando", name)
                results[name] = False
                continue
            results[name] = self._connect_entry(entry)
        return results

    def disconnect_all(self) -> None:
        """Desconecta todos os servidores. Chamado no shutdown do Ciel."""
        for entry in self._servers.values():
            self._disconnect_entry(entry)

    def _disconnect_entry(self, entry: ServerEntry) -> None:
        if entry.client:
            try:
                entry.client.close()
            except Exception as e:
                logger.warning("Erro ao fechar '%s': %s", entry.name, e)
            entry.client = None
            entry.tools  = {}

    # ── API pública ────────────────────────────────────────────────────────────

    def add_server(self, config: dict) -> tuple[bool, str]:
        """
        Registra e conecta um novo servidor MCP.

        Parâmetros obrigatórios no config:
            name (str)     — identificador único
            type (str)     — "stdio" ou "sse"
            command (str)  — executável (stdio) OU
            url (str)      — URL (sse)

        Retorna (sucesso, mensagem).
        """
        name = config.get("name", "").strip()
        if not name:
            return False, "Campo 'name' é obrigatório."

        if not _valid_name(name):
            return False, f"Nome inválido: '{name}'. Use apenas letras, números e hífens."

        if name in self._servers:
            return False, f"Servidor '{name}' já existe. Use mcp_remove_server antes de re-adicionar."

        transport = config.get("type", "stdio")
        if transport == "stdio" and not config.get("command"):
            return False, "Transporte 'stdio' requer o campo 'command'."
        if transport == "sse" and not config.get("url"):
            return False, "Transporte 'sse' requer o campo 'url'."

        config.setdefault("enabled", True)
        entry = ServerEntry(config)
        self._servers[name] = entry

        ok = self._connect_entry(entry)
        if ok:
            self._save_config()
            n = len(entry.tools)
            tool_names = list(entry.tools.keys())
            summary = ", ".join(tool_names[:5])
            if len(tool_names) > 5:
                summary += f" ... (+{len(tool_names)-5})"
            return True, (
                f"Servidor '{name}' conectado com {n} tool(s): {summary}"
            )
        else:
            # remove da memória se não conseguiu conectar
            del self._servers[name]
            return False, f"Falha ao conectar '{name}': {entry.error}"

    def remove_server(self, name: str) -> tuple[bool, str]:
        """
        Desconecta e remove um servidor.
        Retorna (sucesso, mensagem).
        """
        if name not in self._servers:
            return False, f"Servidor '{name}' não encontrado."

        entry = self._servers.pop(name)
        self._disconnect_entry(entry)
        self._save_config()
        return True, f"Servidor '{name}' removido."

    def reconnect(self, name: str) -> tuple[bool, str]:
        """
        Reconecta um servidor existente (útil quando o processo morreu).
        """
        if name not in self._servers:
            return False, f"Servidor '{name}' não encontrado."

        entry = self._servers[name]
        self._disconnect_entry(entry)
        ok = self._connect_entry(entry)
        if ok:
            return True, f"Servidor '{name}' reconectado com {len(entry.tools)} tool(s)."
        return False, f"Falha ao reconectar '{name}': {entry.error}"

    # ── Acesso às tools ────────────────────────────────────────────────────────

    def all_tools(self) -> dict:
        """
        Retorna o merge de todas as tools de todos os servidores conectados.
        Pronto para tools.update(manager.all_tools()) no cli.py.
        """
        merged = {}
        for entry in self._servers.values():
            if entry.is_connected:
                merged.update(entry.tools)
        return merged

    def server_tools(self, name: str) -> dict:
        """
        Retorna as tools de um servidor específico.
        Útil após add_server() para injetar só as novas tools no registry.
        """
        entry = self._servers.get(name)
        if entry and entry.is_connected:
            return dict(entry.tools)
        return {}

    def remove_server_tools(self, name: str, tools: dict) -> None:
        """
        Remove as tools de um servidor do registry passado por referência.
        Chamado após remove_server() para limpar o registry ativo.

        Uso:
            manager.remove_server("telegram")
            manager.remove_server_tools("telegram", tools)
        """
        to_remove = [k for k in tools if _tool_belongs_to(k, name)]
        for key in to_remove:
            del tools[key]

    # ── Informações ────────────────────────────────────────────────────────────

    def list_servers(self) -> list[dict]:
        """
        Retorna lista de dicts com informações de cada servidor.
        Usado pela tool mcp_list_servers e pelo comando /mcp no cli.
        """
        result = []
        for entry in self._servers.values():
            server_info = entry.client.server_info if entry.client else None
            result.append({
                "name":       entry.name,
                "type":       entry.config.get("type", "stdio"),
                "status":     entry.status(),
                "connected":  entry.is_connected,
                "tools":      list(entry.tools.keys()),
                "server_name": server_info.name    if server_info else "",
                "version":     server_info.version if server_info else "",
                "error":       entry.error,
            })
        return result

    def healthcheck(self) -> dict[str, bool]:
        """
        Verifica quais servidores ainda estão vivos.
        Retorna dict {nome: vivo}.
        Pode ser chamado periodicamente para detectar processos mortos.
        """
        return {
            name: entry.is_connected
            for name, entry in self._servers.items()
        }

    def __repr__(self) -> str:
        connected = sum(1 for e in self._servers.values() if e.is_connected)
        return f"MCPManager({connected}/{len(self._servers)} conectados)"


# ── Helpers privados ───────────────────────────────────────────────────────────

def _valid_name(name: str) -> bool:
    """Nome válido: só letras, números, hífen e underline."""
    import re
    return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))


def _tool_belongs_to(registry_name: str, server_name: str) -> bool:
    """Verifica se uma tool do registry pertence a um servidor específico."""
    parsed = parse_registry_name(registry_name)
    if parsed is None:
        return False
    return parsed[0] == server_name

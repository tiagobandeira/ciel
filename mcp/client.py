"""
mcp/client.py
=============
Cliente MCP desacoplado — sem dependências de UI (rich, textual, etc.).

Suporta dois transportes:
  - stdio : processo local; comunica via stdin/stdout (JSON-RPC 2.0, newline-delimited)
  - sse   : servidor remoto; comunica via HTTP + Server-Sent Events

Uso típico:
    client = MCPClient.stdio("python", ["my_mcp_server.py"], env={"TOKEN": "..."})
    await client.connect()
    tools = await client.list_tools()
    result = await client.call_tool("send_message", {"chat_id": "123", "text": "oi"})
    await client.close()

Ou como context manager:
    async with MCPClient.stdio("python", ["my_mcp_server.py"]) as client:
        tools = await client.list_tools()
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Exceções ──────────────────────────────────────────────────────────────────

class MCPError(Exception):
    """Base para todos os erros do cliente MCP."""

class MCPConnectionError(MCPError):
    """Falha ao conectar ou processo morreu."""

class MCPTimeoutError(MCPError):
    """Chamada excedeu o tempo limite."""

class MCPProtocolError(MCPError):
    """Resposta não segue JSON-RPC 2.0."""

class MCPToolError(MCPError):
    """Servidor retornou erro ao executar uma tool."""


# ── Tipos de dados ─────────────────────────────────────────────────────────────

class Transport(str, Enum):
    STDIO = "stdio"
    SSE   = "sse"


@dataclass
class MCPToolSchema:
    """Schema de uma tool conforme retornado pelo servidor MCP."""
    name:        str
    description: str
    parameters:  dict  # JSON Schema dos parâmetros (properties, required, etc.)

    def to_registry_format(self, namespace: str) -> dict:
        """
        Converte para o formato que o ToolRegistry do Ciel espera.

        O formato esperado pelo tools_registry.py é:
            {
                "description": str,
                "parameters":  dict,   # JSON Schema
                "categoria":   str,
            }

        O campo "fn" é adicionado pelo MCPAdapter, não aqui.
        """
        return {
            "description": self.description,
            "parameters":  self.parameters,
            "categoria":   "mcp",
            "_mcp_server": namespace,
            "_mcp_tool":   self.name,
        }


@dataclass
class ServerInfo:
    """Informações retornadas pelo servidor no handshake."""
    name:            str
    version:         str
    protocol_version: str
    capabilities:    dict = field(default_factory=dict)


# ── Cliente principal ──────────────────────────────────────────────────────────

class MCPClient:
    """
    Cliente MCP assíncrono.

    Não instancie diretamente — use os construtores de classe:
        MCPClient.stdio(cmd, args, env)
        MCPClient.sse(url, headers)
    """

    def __init__(
        self,
        transport:   Transport,
        # stdio
        command:     str        = "",
        args:        list[str]  = None,
        env:         dict       = None,
        # sse
        url:         str        = "",
        headers:     dict       = None,
        # config
        timeout:     float      = 30.0,
        max_retries: int        = 3,
    ):
        self.transport   = transport
        self.command     = command
        self.args        = args or []
        self.env         = env or {}
        self.url         = url
        self.headers     = headers or {}
        self.timeout     = timeout
        self.max_retries = max_retries

        # estado interno
        self._process:   asyncio.subprocess.Process | None = None
        self._reader:    asyncio.StreamReader | None       = None
        self._writer:    asyncio.StreamWriter | None       = None
        self._connected: bool                              = False
        self._pending:   dict[str, asyncio.Future]        = {}
        self._reader_task: asyncio.Task | None            = None
        self.server_info: ServerInfo | None               = None

    # ── Construtores de classe ─────────────────────────────────────────────────

    @classmethod
    def stdio(
        cls,
        command:     str,
        args:        list[str] = None,
        env:         dict      = None,
        timeout:     float     = 30.0,
        max_retries: int       = 3,
    ) -> "MCPClient":
        """Cria um cliente para processo local via stdin/stdout."""
        return cls(
            transport=Transport.STDIO,
            command=command,
            args=args or [],
            env=env or {},
            timeout=timeout,
            max_retries=max_retries,
        )

    @classmethod
    def sse(
        cls,
        url:         str,
        headers:     dict  = None,
        timeout:     float = 30.0,
        max_retries: int   = 3,
    ) -> "MCPClient":
        """Cria um cliente para servidor remoto via HTTP/SSE."""
        return cls(
            transport=Transport.SSE,
            url=url,
            headers=headers or {},
            timeout=timeout,
            max_retries=max_retries,
        )

    # ── Context manager ────────────────────────────────────────────────────────

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ── Conexão ────────────────────────────────────────────────────────────────

    async def connect(self) -> ServerInfo:
        """
        Abre a conexão com o servidor e faz o handshake MCP (initialize).
        Retorna as informações do servidor.
        """
        if self._connected:
            return self.server_info

        if self.transport == Transport.STDIO:
            await self._connect_stdio()
        else:
            await self._connect_sse()

        self._reader_task = asyncio.create_task(self._read_loop())
        self.server_info  = await self._handshake()
        self._connected   = True
        logger.info("MCP conectado: %s v%s", self.server_info.name, self.server_info.version)
        return self.server_info

    async def _connect_stdio(self) -> None:
        # PYTHONIOENCODING garante UTF-8 no stdout/stdin do subprocesso no Windows
        # (sem isso, cp1252 é usado por padrão e caracteres não-ASCII corrompem)
        merged_env = {**os.environ, "PYTHONIOENCODING": "utf-8", **self.env}

        # limit de 8 MB — o padrão do asyncio (64 KB) estoura em payloads grandes
        # como os do mcp-remote (Notion retorna listas de pages em JSON numa linha só)
        _READER_LIMIT = 8 * 1024 * 1024

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
                limit=_READER_LIMIT,
            )
        except TypeError:
            # fallback para versões do Python que não aceitam limit= aqui
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
        except FileNotFoundError:
            raise MCPConnectionError(
                f"Comando não encontrado: '{self.command}'. "
                "Verifique se o servidor MCP está instalado."
            )
        except Exception as e:
            raise MCPConnectionError(f"Falha ao iniciar processo MCP: {e}") from e

        self._reader = self._process.stdout
        self._writer = self._process.stdin

    async def _connect_sse(self) -> None:
        # SSE requer aiohttp — importação lazy para não forçar dependência
        # quando só se usa stdio
        try:
            import aiohttp  # noqa: F401
        except ImportError:
            raise MCPConnectionError(
                "Transporte SSE requer 'aiohttp'. Instale com: pip install aiohttp"
            )
        # implementação SSE completa na Fase 1.2 do roadmap
        # (stdio cobre 90% dos casos de uso locais)
        raise NotImplementedError(
            "Transporte SSE ainda não implementado. Use stdio para servidores locais."
        )

    async def close(self) -> None:
        """Encerra a conexão e mata o processo (se stdio)."""
        self._connected = False

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        # cancela futures pendentes
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()
            self._process = None

        logger.info("MCP desconectado.")

    # ── Protocolo JSON-RPC 2.0 ────────────────────────────────────────────────

    def _make_id(self) -> str:
        return str(uuid.uuid4())[:8]

    async def _send(self, method: str, params: dict) -> str:
        """Envia uma mensagem JSON-RPC e retorna o id gerado."""
        msg_id = self._make_id()
        payload = {
            "jsonrpc": "2.0",
            "id":      msg_id,
            "method":  method,
            "params":  params,
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()
        return msg_id

    async def _request(self, method: str, params: dict) -> Any:
        """
        Envia uma requisição JSON-RPC e aguarda a resposta correspondente.
        Implementa retry com backoff exponencial.
        """
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return await self._request_once(method, params)
            except MCPTimeoutError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning("Timeout na tentativa %d/%d — aguardando %ds", attempt + 1, self.max_retries, wait)
                    await asyncio.sleep(wait)
            except MCPToolError:
                raise  # erros de tool não fazem retry
            except MCPConnectionError:
                raise  # erros de conexão não fazem retry
        raise last_error

    async def _request_once(self, method: str, params: dict) -> Any:
        if not self._writer:
            raise MCPConnectionError("Cliente não conectado. Chame connect() primeiro.")

        msg_id = await self._send(method, params)
        loop   = asyncio.get_event_loop()
        fut    = loop.create_future()
        self._pending[msg_id] = fut

        try:
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=self.timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise MCPTimeoutError(
                f"Timeout ({self.timeout}s) aguardando resposta do método '{method}'"
            )
        finally:
            self._pending.pop(msg_id, None)

    async def _read_loop(self) -> None:
        """Loop contínuo de leitura — roda em background como Task."""
        _LIMIT = 8 * 1024 * 1024  # 8 MB — mesmo valor do StreamReader
        buf = b""
        try:
            while True:
                if self._reader is None:
                    break
                try:
                    chunk = await self._reader.readuntil(b"\n")
                except asyncio.LimitOverrunError as e:
                    # linha maior que o buffer interno — lê e descarta
                    await self._reader.read(e.consumed)
                    logger.warning("Linha MCP truncada (%d bytes) — ignorada", e.consumed)
                    buf = b""
                    continue
                except asyncio.IncompleteReadError as e:
                    # processo fechou stdout no meio de uma linha
                    if e.partial:
                        self._dispatch(e.partial.decode(errors="replace").strip())
                    self._dispatch_connection_error("Servidor MCP encerrou a conexão inesperadamente.")
                    break

                if not chunk:
                    self._dispatch_connection_error("Servidor MCP encerrou a conexão inesperadamente.")
                    break

                buf += chunk
                if len(buf) > _LIMIT:
                    logger.warning("Payload MCP excede %d bytes — descartado", _LIMIT)
                    buf = b""
                    continue

                self._dispatch(buf.decode(errors="replace").strip())
                buf = b""
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._dispatch_connection_error(f"Erro no read loop: {e}")

    def _dispatch(self, raw: str) -> None:
        """Despacha uma linha JSON para o Future correspondente."""
        if not raw:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Linha não-JSON ignorada: %s", raw[:120])
            return

        msg_id = str(msg.get("id", ""))
        fut    = self._pending.get(msg_id)
        if fut is None or fut.done():
            return  # notificação ou resposta sem pending (normal em alguns servidores)

        if "error" in msg:
            err = msg["error"]
            fut.set_exception(MCPToolError(f"[{err.get('code')}] {err.get('message')}"))
        elif "result" in msg:
            fut.set_result(msg["result"])
        else:
            fut.set_exception(MCPProtocolError(f"Resposta sem 'result' nem 'error': {raw[:120]}"))

    def _dispatch_connection_error(self, msg: str) -> None:
        """Cancela todos os futures pendentes com erro de conexão."""
        exc = MCPConnectionError(msg)
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
        self._connected = False

    # ── Handshake MCP ─────────────────────────────────────────────────────────

    async def _handshake(self) -> ServerInfo:
        """
        Executa o handshake inicial do protocolo MCP:
        1. Envia 'initialize' com as capacidades do cliente
        2. Envia 'notifications/initialized' para confirmar
        """
        result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities":    {"tools": {}},
            "clientInfo":      {"name": "ciel-mcp-client", "version": "1.0.0"},
        })

        # notificação de confirmação (sem resposta esperada)
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method":  "notifications/initialized",
            "params":  {},
        }) + "\n"
        self._writer.write(notif.encode())
        await self._writer.drain()

        info = result.get("serverInfo", {})
        caps = result.get("capabilities", {})
        return ServerInfo(
            name=info.get("name", "unknown"),
            version=info.get("version", "0.0.0"),
            protocol_version=result.get("protocolVersion", ""),
            capabilities=caps,
        )

    # ── API pública ────────────────────────────────────────────────────────────

    async def list_tools(self) -> list[MCPToolSchema]:
        """
        Retorna a lista de tools disponíveis no servidor.
        Converte o schema MCP para MCPToolSchema.
        """
        result = await self._request("tools/list", {})
        tools  = []
        for t in result.get("tools", []):
            schema = MCPToolSchema(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("inputSchema", {"type": "object", "properties": {}}),
            )
            tools.append(schema)
        logger.info("Discovery: %d tools encontradas", len(tools))
        return tools

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Executa uma tool no servidor MCP.
        Retorna o conteúdo da resposta (str ou dict).
        Lança MCPToolError em caso de erro do servidor.
        """
        result = await self._request("tools/call", {
            "name":      tool_name,
            "arguments": arguments,
        })

        # extrai conteúdo — o protocolo MCP retorna lista de content blocks
        content = result.get("content", [])
        if not content:
            return ""

        # consolida blocos de texto
        parts = []
        for block in content:
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "image":
                parts.append(f"[imagem: {block.get('mimeType', 'desconhecido')}]")
            else:
                parts.append(str(block))

        return "\n".join(parts) if len(parts) > 1 else (parts[0] if parts else "")

    # ── Healthcheck ────────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        """Verifica se a conexão ainda está ativa."""
        if not self._connected:
            return False
        if self.transport == Transport.STDIO and self._process:
            return self._process.returncode is None
        return True

    def __repr__(self) -> str:
        status = "conectado" if self._connected else "desconectado"
        if self.transport == Transport.STDIO:
            return f"MCPClient(stdio, cmd='{self.command}', {status})"
        return f"MCPClient(sse, url='{self.url}', {status})"


# ── Wrapper síncrono para uso no Ciel (que ainda não é async) ─────────────────

class SyncMCPClient:
    """
    Wrapper síncrono em torno de MCPClient.

    O Ciel roda de forma síncrona (run_agent é blocking). Este wrapper
    gerencia um event loop interno para que o cliente assíncrono possa
    ser usado sem refatorar o cli.py.

    Uso:
        client = SyncMCPClient.stdio("python", ["server.py"])
        client.connect()
        tools = client.list_tools()
        result = client.call_tool("send_message", {"text": "oi"})
        client.close()
    """

    def __init__(self, async_client: MCPClient):
        self._client = async_client
        self._loop   = asyncio.new_event_loop()

    @classmethod
    def stdio(
        cls,
        command:     str,
        args:        list[str] = None,
        env:         dict      = None,
        timeout:     float     = 30.0,
        max_retries: int       = 3,
    ) -> "SyncMCPClient":
        return cls(MCPClient.stdio(command, args, env, timeout, max_retries))

    @classmethod
    def sse(
        cls,
        url:         str,
        headers:     dict  = None,
        timeout:     float = 30.0,
        max_retries: int   = 3,
    ) -> "SyncMCPClient":
        return cls(MCPClient.sse(url, headers, timeout, max_retries))

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def connect(self) -> ServerInfo:
        return self._run(self._client.connect())

    def list_tools(self) -> list[MCPToolSchema]:
        return self._run(self._client.list_tools())

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        return self._run(self._client.call_tool(tool_name, arguments))

    def is_alive(self) -> bool:
        return self._client.is_alive()

    def close(self) -> None:
        self._run(self._client.close())
        self._loop.close()

    @property
    def server_info(self) -> ServerInfo | None:
        return self._client.server_info

    def __repr__(self) -> str:
        return f"Sync{self._client!r}"
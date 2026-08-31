"""
test_mcp_client.py
==================
Testa o MCPClient de forma completamente isolada — sem Ollama, sem rede,
sem servidor MCP externo.

Sobe um servidor MCP mínimo como subprocesso (via stdin/stdout) e
valida o fluxo completo: connect → list_tools → call_tool → close.

Uso:
    python test_mcp_client.py
    python test_mcp_client.py -v   # verbose (mostra JSON trocado)
"""

import asyncio
import json
import sys
import textwrap

# ── Servidor MCP mínimo embutido ──────────────────────────────────────────────
# Roda como subprocesso. Implementa apenas o suficiente para o teste passar.

FAKE_SERVER_CODE = textwrap.dedent("""
import sys, json

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

def handle(msg):
    method = msg.get("method", "")
    mid    = msg.get("id")

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "fake-server", "version": "0.1.0"},
            "capabilities": {"tools": {}},
        }})

    elif method == "notifications/initialized":
        pass  # notificação, sem resposta

    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "tools": [
                {
                    "name": "echo",
                    "description": "Retorna o texto recebido",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Texto a ecoar"}
                        },
                        "required": ["text"],
                    },
                },
                {
                    "name": "soma",
                    "description": "Soma dois números",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "number"},
                            "b": {"type": "number"},
                        },
                        "required": ["a", "b"],
                    },
                },
            ]
        }})

    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})

        if name == "echo":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": args.get("text", "")}]
            }})
        elif name == "soma":
            total = args.get("a", 0) + args.get("b", 0)
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": str(total)}]
            }})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32601, "message": f"Tool desconhecida: {name}"
            }})
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {
            "code": -32601, "message": f"Método desconhecido: {method}"
        }})

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        handle(json.loads(line))
    except Exception as e:
        sys.stderr.write(f"server error: {e}\\n")
""")


# ── Testes ────────────────────────────────────────────────────────────────────

async def run_tests(verbose: bool = False):
    from mcp.client import MCPClient, MCPToolError

    print("Subindo servidor MCP de teste...")
    client = MCPClient.stdio(
        sys.executable,
        ["-c", FAKE_SERVER_CODE],
        timeout=10.0,
    )

    passed = 0
    failed = 0

    def ok(msg):
        nonlocal passed
        passed += 1
        print(f"  ✓ {msg}")

    def fail(msg, err=""):
        nonlocal failed
        failed += 1
        print(f"  ✗ {msg}")
        if err:
            print(f"      {err}")

    async with client:

        # 1. handshake
        try:
            assert client.server_info is not None
            assert client.server_info.name == "fake-server"
            ok(f"handshake — servidor: {client.server_info.name} v{client.server_info.version}")
        except Exception as e:
            fail("handshake", e)

        # 2. is_alive
        try:
            assert client.is_alive()
            ok("is_alive() → True enquanto conectado")
        except Exception as e:
            fail("is_alive", e)

        # 3. list_tools
        try:
            tools = await client.list_tools()
            assert len(tools) == 2
            names = [t.name for t in tools]
            assert "echo" in names
            assert "soma" in names
            ok(f"list_tools — {len(tools)} tools: {names}")
            if verbose:
                for t in tools:
                    print(f"      {t.name}: {t.description}")
        except Exception as e:
            fail("list_tools", e)

        # 4. to_registry_format
        try:
            tools = await client.list_tools()
            echo_tool = next(t for t in tools if t.name == "echo")
            fmt = echo_tool.to_registry_format("fake")
            assert fmt["categoria"] == "mcp"
            assert fmt["_mcp_server"] == "fake"
            assert fmt["_mcp_tool"] == "echo"
            assert "description" in fmt
            ok("to_registry_format — formato compatível com ToolRegistry")
        except Exception as e:
            fail("to_registry_format", e)

        # 5. call_tool echo
        try:
            result = await client.call_tool("echo", {"text": "olá ciel"})
            assert result == "olá ciel", f"esperado 'olá ciel', got '{result}'"
            ok(f"call_tool echo → '{result}'")
        except Exception as e:
            fail("call_tool echo", e)

        # 6. call_tool soma
        try:
            result = await client.call_tool("soma", {"a": 7, "b": 3})
            assert result == "10", f"esperado '10', got '{result}'"
            ok(f"call_tool soma(7, 3) → '{result}'")
        except Exception as e:
            fail("call_tool soma", e)

        # 7. tool inexistente → MCPToolError
        try:
            await client.call_tool("nao_existe", {})
            fail("tool inexistente deveria lançar MCPToolError")
        except MCPToolError as e:
            ok(f"MCPToolError para tool inexistente → '{e}'")
        except Exception as e:
            fail("tool inexistente lançou exceção errada", type(e).__name__)

        # 8. timeout — servidor que nunca responde; timeout estoura no initialize
        from mcp.client import MCPTimeoutError
        try:
            slow_client = MCPClient.stdio(
                sys.executable,
                ["-c", "import time, sys\nfor _ in iter(sys.stdin.readline, ''): time.sleep(60)"],
                timeout=1.0,
                max_retries=1,
            )
            try:
                await slow_client.connect()
                fail("deveria ter dado MCPTimeoutError no connect()")
            except MCPTimeoutError as e:
                ok(f"MCPTimeoutError no connect() → '{e}'")
            finally:
                await slow_client.close()
        except Exception as e:
            fail("teste de timeout", e)

    # 9. is_alive após close
    try:
        assert not client.is_alive()
        ok("is_alive() → False após close()")
    except Exception as e:
        fail("is_alive após close", e)

    # resultado
    total = passed + failed
    print()
    print(f"{'─' * 40}")
    print(f"  {passed}/{total} passou  |  {failed} falhou")
    if failed:
        print("  ⚠ Algum teste falhou — verifique acima.")
        sys.exit(1)
    else:
        print("  Tudo certo. Cliente MCP pronto para integração.")


if __name__ == "__main__":
    verbose = "-v" in sys.argv
    print()
    print("=== test_mcp_client.py ===")
    print()
    asyncio.run(run_tests(verbose=verbose))
    print()

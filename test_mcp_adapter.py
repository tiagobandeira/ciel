"""
test_mcp_adapter.py
===================
Testa o MCPAdapter de forma isolada — usa o mesmo servidor falso do
test_mcp_client.py embutido aqui.

Uso:
    python test_mcp_adapter.py
"""

import sys
import textwrap

FAKE_SERVER_CODE = textwrap.dedent("""
import sys, json

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line: continue
    msg = json.loads(line)
    method = msg.get("method", "")
    mid    = msg.get("id")

    if method == "initialize":
        send({"jsonrpc":"2.0","id":mid,"result":{
            "protocolVersion":"2024-11-05",
            "serverInfo":{"name":"test-server","version":"1.0"},
            "capabilities":{"tools":{}},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc":"2.0","id":mid,"result":{"tools":[
            {
                "name": "send_message",
                "description": "Envia uma mensagem para um chat",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "string", "description": "ID do chat destino"},
                        "text":    {"type": "string", "description": "Texto da mensagem"},
                        "silent":  {"type": "boolean", "description": "Enviar sem notificação"},
                    },
                    "required": ["chat_id", "text"],
                },
            },
            {
                "name": "get_updates",
                "description": "Retorna mensagens recebidas",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Máximo de mensagens"},
                    },
                    "required": [],
                },
            },
        ]}})
    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name == "send_message":
            send({"jsonrpc":"2.0","id":mid,"result":{
                "content":[{"type":"text","text":f"mensagem enviada para {args.get('chat_id')}"}]
            }})
        elif name == "get_updates":
            send({"jsonrpc":"2.0","id":mid,"result":{
                "content":[{"type":"text","text":"[]"}]
            }})
        else:
            send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"unknown: {name}"}})
""")


def run_tests():
    from mcp.client import SyncMCPClient
    from mcp.adapter import (
        adapt_tools, convert_parameters, make_tool_callable,
        is_mcp_tool, parse_registry_name, _make_registry_name,
    )

    passed = 0
    failed = 0

    def ok(msg):
        nonlocal passed; passed += 1
        print(f"  ✓ {msg}")

    def fail(msg, err=""):
        nonlocal failed; failed += 1
        print(f"  ✗ {msg}")
        if err: print(f"      {err}")

    # ── Testes unitários (sem servidor) ───────────────────────────────────────

    print("Testes unitários (sem servidor)...")

    # 1. convert_parameters — tipos
    try:
        schema = {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string",  "description": "ID do chat"},
                "count":   {"type": "integer"},
                "active":  {"type": "boolean"},
                "data":    {"type": "object"},
            },
            "required": ["chat_id"],
        }
        params = convert_parameters(schema)
        names  = [p["name"] for p in params]
        types  = {p["name"]: p["type"] for p in params}

        assert "chat_id" in names
        assert types["chat_id"] == "str"
        assert types["count"]   == "int"
        assert types["active"]  == "bool"
        assert types["data"]    == "dict"
        ok("convert_parameters — tipos JSON Schema → Python")
    except Exception as e:
        fail("convert_parameters tipos", e)

    # 2. convert_parameters — required vs opcional
    try:
        schema = {
            "type": "object",
            "properties": {
                "obrigatorio": {"type": "string"},
                "opcional":    {"type": "string"},
            },
            "required": ["obrigatorio"],
        }
        params = convert_parameters(schema)
        by_name = {p["name"]: p for p in params}

        assert "default" not in by_name["obrigatorio"]
        assert by_name["opcional"].get("default") == "None"
        ok("convert_parameters — required sem default, opcional com default=None")
    except Exception as e:
        fail("convert_parameters required/opcional", e)

    # 3. convert_parameters — descrição
    try:
        schema = {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto da mensagem"},
            },
            "required": ["text"],
        }
        params = convert_parameters(schema)
        assert params[0]["description"] == "Texto da mensagem"
        ok("convert_parameters — descrição preservada")
    except Exception as e:
        fail("convert_parameters descrição", e)

    # 4. convert_parameters — schema vazio
    try:
        assert convert_parameters({}) == []
        assert convert_parameters(None) == []
        ok("convert_parameters — schema vazio/None → lista vazia")
    except Exception as e:
        fail("convert_parameters schema vazio", e)

    # 5. _make_registry_name — nomenclatura
    try:
        assert _make_registry_name("telegram", "send_message") == "mcp_telegram__send_message"
        assert _make_registry_name("my-server", "doThing")     == "mcp_my_server__doThing"
        ok("_make_registry_name — namespace correto")
    except Exception as e:
        fail("_make_registry_name", e)

    # 6. is_mcp_tool
    try:
        assert is_mcp_tool("mcp_telegram__send_message") is True
        assert is_mcp_tool("create_tool")                is False
        assert is_mcp_tool("mcp_sem_duplo_underline")    is False
        ok("is_mcp_tool — identifica tools MCP corretamente")
    except Exception as e:
        fail("is_mcp_tool", e)

    # 7. parse_registry_name
    try:
        assert parse_registry_name("mcp_telegram__send_message") == ("telegram", "send_message")
        assert parse_registry_name("create_tool")                 is None
        ok("parse_registry_name — parse reverso correto")
    except Exception as e:
        fail("parse_registry_name", e)

    # ── Testes de integração (com servidor fake) ──────────────────────────────

    print("\nTestes de integração (com servidor fake)...")

    client = SyncMCPClient.stdio(sys.executable, ["-c", FAKE_SERVER_CODE], timeout=10.0)
    try:
        client.connect()

        # 8. adapt_tools — retorno completo
        try:
            tools = adapt_tools(client, "test")
            assert len(tools) == 2
            assert "mcp_test__send_message" in tools
            assert "mcp_test__get_updates"  in tools
            ok(f"adapt_tools — {len(tools)} tools registradas com namespace correto")
        except Exception as e:
            fail("adapt_tools retorno", e)

        # 9. estrutura do dict de cada tool
        try:
            tool = tools["mcp_test__send_message"]
            assert callable(tool["fn"])
            assert tool["categoria"]   == "mcp"
            assert tool["_mcp_server"] == "test"
            assert tool["_mcp_tool"]   == "send_message"
            assert isinstance(tool["description"], str) and tool["description"]
            assert isinstance(tool["parameters"],  list)
            ok("adapt_tools — estrutura do dict compatível com ToolRegistry")
        except Exception as e:
            fail("adapt_tools estrutura", e)

        # 10. parâmetros de send_message
        try:
            params  = tools["mcp_test__send_message"]["parameters"]
            by_name = {p["name"]: p for p in params}

            assert "chat_id" in by_name
            assert "text"    in by_name
            assert "silent"  in by_name

            # obrigatórios sem default
            assert "default" not in by_name["chat_id"]
            assert "default" not in by_name["text"]
            # opcional com default
            assert by_name["silent"].get("default") == "None"
            # tipos
            assert by_name["chat_id"]["type"] == "str"
            assert by_name["silent"]["type"]  == "bool"
            # descrições
            assert by_name["chat_id"]["description"] == "ID do chat destino"
            ok("adapt_tools — parâmetros de send_message (tipos, required, descrições)")
        except Exception as e:
            fail("adapt_tools parâmetros send_message", e)

        # 11. callable funciona (chama o servidor de verdade)
        try:
            fn     = tools["mcp_test__send_message"]["fn"]
            result = fn(chat_id="grupo_x", text="relatório pronto")
            assert "grupo_x" in result
            ok(f"callable send_message → '{result}'")
        except Exception as e:
            fail("callable send_message", e)

        # 12. callable com parâmetro opcional omitido (None filtrado)
        try:
            fn     = tools["mcp_test__send_message"]["fn"]
            result = fn(chat_id="grupo_x", text="oi", silent=None)
            assert "grupo_x" in result
            ok("callable — None filtrado antes de passar ao servidor")
        except Exception as e:
            fail("callable None filtrado", e)

        # 13. callable retorna str mesmo para erro
        try:
            fn     = make_tool_callable(client, "tool_inexistente")
            result = fn()
            assert isinstance(result, str)
            assert "Erro" in result
            ok(f"callable tool inexistente retorna str de erro → '{result[:60]}'")
        except Exception as e:
            fail("callable erro retorna str", e)

        # 14. allowed_tools filtra
        try:
            tools_filtradas = adapt_tools(client, "test", allowed_tools=["send_message"])
            assert len(tools_filtradas) == 1
            assert "mcp_test__send_message" in tools_filtradas
            assert "mcp_test__get_updates"  not in tools_filtradas
            ok("adapt_tools — allowed_tools filtra corretamente")
        except Exception as e:
            fail("adapt_tools allowed_tools", e)

    finally:
        client.close()

    # ── Resultado ─────────────────────────────────────────────────────────────

    total = passed + failed
    print()
    print(f"{'─' * 40}")
    print(f"  {passed}/{total} passou  |  {failed} falhou")
    if failed:
        print("  ⚠ Algum teste falhou — verifique acima.")
        sys.exit(1)
    else:
        print("  Tudo certo. Adaptador pronto para integração.")


if __name__ == "__main__":
    print()
    print("=== test_mcp_adapter.py ===")
    print()
    run_tests()
    print()

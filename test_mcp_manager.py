"""
test_mcp_manager.py
===================
Testa o MCPManager de forma isolada — sem Ollama, sem UI, sem mcp_servers.json real.
Usa um arquivo de config temporário e o servidor fake embutido.

Uso:
    python test_mcp_manager.py
"""

import json
import sys
import tempfile
import textwrap
from pathlib import Path

FAKE_SERVER_CODE = textwrap.dedent("""
import sys, json

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line: continue
    msg = json.loads(line)
    method = msg.get("method","")
    mid = msg.get("id")

    if method == "initialize":
        send({"jsonrpc":"2.0","id":mid,"result":{
            "protocolVersion":"2024-11-05",
            "serverInfo":{"name":"fake","version":"0.1"},
            "capabilities":{"tools":{}},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc":"2.0","id":mid,"result":{"tools":[
            {"name":"send_message","description":"Envia mensagem","inputSchema":{
                "type":"object",
                "properties":{
                    "text":{"type":"string","description":"Texto"},
                    "chat_id":{"type":"string","description":"ID do chat"},
                },
                "required":["text","chat_id"],
            }},
            {"name":"get_updates","description":"Recebe updates","inputSchema":{
                "type":"object","properties":{},"required":[],
            }},
        ]}})
    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments",{})
        if name == "send_message":
            send({"jsonrpc":"2.0","id":mid,"result":{
                "content":[{"type":"text","text":f"ok: {args.get('text','')}"}]
            }})
        elif name == "get_updates":
            send({"jsonrpc":"2.0","id":mid,"result":{
                "content":[{"type":"text","text":"[]"}]
            }})
        else:
            send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"unknown: {name}"}})
""")


def run_tests():
    from mcp.manager import MCPManager

    passed = 0
    failed = 0

    def ok(msg):
        nonlocal passed; passed += 1
        print(f"  ✓ {msg}")

    def fail(msg, err=""):
        nonlocal failed; failed += 1
        print(f"  ✗ {msg}")
        if err: print(f"      {err}")

    # config do servidor de teste
    server_config = {
        "name":    "test",
        "type":    "stdio",
        "command": sys.executable,
        "args":    ["-c", FAKE_SERVER_CODE],
        "timeout": 10.0,
    }

    # usa arquivo temporário para não poluir o diretório do projeto
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "mcp_servers.json"
        manager = MCPManager(config_file=config_path)

        # 1. manager vazio inicial
        try:
            assert len(manager.list_servers()) == 0
            assert manager.all_tools() == {}
            ok("manager vazio na inicialização")
        except Exception as e:
            fail("manager vazio", e)

        # 2. add_server — conecta e registra
        try:
            ok_flag, msg = manager.add_server(server_config)
            assert ok_flag, f"add_server falhou: {msg}"
            assert "test" in msg or "tool" in msg.lower()
            ok(f"add_server → '{msg}'")
        except Exception as e:
            fail("add_server", e)

        # 3. servidor aparece no list_servers
        try:
            servers = manager.list_servers()
            assert len(servers) == 1
            s = servers[0]
            assert s["name"] == "test"
            assert s["connected"] is True
            assert len(s["tools"]) == 2
            ok(f"list_servers — 1 servidor, {len(s['tools'])} tools, status: {s['status']}")
        except Exception as e:
            fail("list_servers", e)

        # 4. all_tools retorna tools com namespace correto
        try:
            tools = manager.all_tools()
            assert len(tools) == 2
            assert "mcp_test__send_message" in tools
            assert "mcp_test__get_updates"  in tools
            ok(f"all_tools — {len(tools)} tools com namespace mcp_test__*")
        except Exception as e:
            fail("all_tools", e)

        # 5. estrutura das tools compatível com ToolRegistry
        try:
            tool = manager.all_tools()["mcp_test__send_message"]
            assert callable(tool["fn"])
            assert tool["categoria"]   == "mcp"
            assert tool["_mcp_server"] == "test"
            assert isinstance(tool["parameters"], list)
            ok("estrutura do dict compatível com ToolRegistry")
        except Exception as e:
            fail("estrutura dict", e)

        # 6. callable funciona end-to-end
        try:
            fn     = manager.all_tools()["mcp_test__send_message"]["fn"]
            result = fn(text="olá mundo", chat_id="g1")
            assert "olá mundo" in result
            ok(f"callable end-to-end → '{result}'")
        except Exception as e:
            fail("callable end-to-end", e)

        # 7. config persistida em JSON
        try:
            assert config_path.exists()
            data = json.loads(config_path.read_text())
            assert len(data["servers"]) == 1
            assert data["servers"][0]["name"] == "test"
            ok(f"config persistida em {config_path.name}")
        except Exception as e:
            fail("persistência JSON", e)

        # 8. config carregada na reinicialização
        try:
            manager2 = MCPManager(config_file=config_path)
            assert len(manager2.list_servers()) == 1
            s = manager2.list_servers()[0]
            assert s["name"] == "test"
            assert s["connected"] is False   # ainda não chamou connect_all
            ok("config recarregada na reinicialização (desconectado antes de connect_all)")
        except Exception as e:
            fail("reinicialização", e)

        # 9. connect_all reconecta
        try:
            results = manager2.connect_all()
            assert results.get("test") is True
            assert len(manager2.all_tools()) == 2
            ok("connect_all reconecta e carrega tools")
            manager2.disconnect_all()
        except Exception as e:
            fail("connect_all", e)

        # 10. server_tools retorna só as tools do servidor pedido
        try:
            tools = manager.server_tools("test")
            assert len(tools) == 2
            assert all(k.startswith("mcp_test__") for k in tools)
            ok("server_tools — retorna só as tools do servidor específico")
        except Exception as e:
            fail("server_tools", e)

        # 11. add_server nome duplicado retorna erro claro
        try:
            ok_flag, msg = manager.add_server({**server_config, "name": "test"})
            assert not ok_flag
            assert "já existe" in msg
            ok(f"add_server nome duplicado → erro: '{msg}'")
        except Exception as e:
            fail("add_server duplicado", e)

        # 12. add_server nome inválido
        try:
            ok_flag, msg = manager.add_server({**server_config, "name": "nome inválido!"})
            assert not ok_flag
            ok(f"add_server nome inválido → erro: '{msg}'")
        except Exception as e:
            fail("add_server nome inválido", e)

        # 13. healthcheck
        try:
            health = manager.healthcheck()
            assert health.get("test") is True
            ok(f"healthcheck → {health}")
        except Exception as e:
            fail("healthcheck", e)

        # 14. remove_server_tools limpa o registry
        try:
            tools = dict(manager.all_tools())   # cópia
            assert len(tools) == 2
            manager.remove_server_tools("test", tools)
            assert len(tools) == 0
            ok("remove_server_tools — limpa tools do registry por referência")
        except Exception as e:
            fail("remove_server_tools", e)

        # 15. remove_server desconecta e remove da config
        try:
            ok_flag, msg = manager.remove_server("test")
            assert ok_flag, f"remove_server falhou: {msg}"
            assert len(manager.list_servers()) == 0
            assert len(manager.all_tools()) == 0
            data = json.loads(config_path.read_text())
            assert len(data["servers"]) == 0
            ok(f"remove_server → '{msg}', config limpa")
        except Exception as e:
            fail("remove_server", e)

        # 16. remove_server nome inexistente
        try:
            ok_flag, msg = manager.remove_server("nao_existe")
            assert not ok_flag
            ok(f"remove_server inexistente → erro: '{msg}'")
        except Exception as e:
            fail("remove_server inexistente", e)

    # ── resultado ──────────────────────────────────────────────────────────────
    total = passed + failed
    print()
    print(f"{'─' * 40}")
    print(f"  {passed}/{total} passou  |  {failed} falhou")
    if failed:
        print("  ⚠ Algum teste falhou — verifique acima.")
        sys.exit(1)
    else:
        print("  Tudo certo. Manager pronto para integração.")


if __name__ == "__main__":
    print()
    print("=== test_mcp_manager.py ===")
    print()
    run_tests()
    print()

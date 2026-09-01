# MCP — Model Context Protocol

> Integração do Ciel com servidores MCP externos para expansão dinâmica de capacidades.

---

## O que é MCP

MCP (Model Context Protocol) é um protocolo aberto que permite que agentes de IA se conectem a serviços externos — Telegram, Google Sheets, GitHub, bancos de dados — de forma padronizada. Em vez de criar uma integração customizada para cada serviço, o Ciel se conecta a um **servidor MCP** que faz a ponte.

O protocolo usa JSON-RPC 2.0 sobre dois transportes:

- **stdio** — o servidor roda como subprocesso local; comunicação via stdin/stdout. Transporte padrão e o único implementado atualmente.
- **SSE/HTTP** — o servidor roda de forma independente e expõe uma URL. Pendente de implementação.

---

## Estrutura de arquivos

```
mcp/
├── __init__.py          # exports públicos do pacote
├── client.py            # MCPClient (async) + SyncMCPClient (wrapper síncrono)
├── adapter.py           # converte schemas MCP → formato do ToolRegistry
├── manager.py           # ciclo de vida dos servidores, persistência
└── telegram/            # servidor MCP para Telegram (exemplo de integração)
    ├── __init__.py
    ├── server.py        # servidor JSON-RPC 2.0 sobre stdio
    └── channels.py      # cache local de canais (telegram_channels.json)

tools/
├── mcp_add_server.py    # tool admin: registra e conecta um servidor
├── mcp_list_servers.py  # tool admin: lista servidores e status
└── mcp_remove_server.py # tool admin: remove e desconecta um servidor

mcp_servers.json         # configuração persistida automaticamente
telegram_channels.json   # cache de canais Telegram (gerado automaticamente)
```

---

## Arquitetura

O pacote `mcp/` é completamente isolado de UI — funciona no `cli.py`, num futuro `ciel.py` (Textual) ou em qualquer frontend. As camadas são:

**`client.py`** — protocolo. Gerencia o subprocesso, serializa/deserializa JSON-RPC 2.0, controla timeouts e retries. Expõe `MCPClient` (async) e `SyncMCPClient` (wrapper síncrono para o cli.py).

**`adapter.py`** — conversão. Transforma o JSON Schema das tools MCP no formato que o `ToolRegistry` do Ciel espera. Gera os callables que o `run_agent` vai chamar. Define o namespace `mcp_{servidor}__{tool}`.

**`manager.py`** — orquestração. Gerencia o ciclo de vida de todos os servidores: conecta na inicialização, persiste em `mcp_servers.json`, expõe `all_tools()` para o `tools.update()` do `cli.py`.

**`tools/mcp_*.py`** — administração. Tools normais do Ciel que o LLM pode chamar para adicionar, listar e remover servidores em tempo de execução.

---

## Como o stdio funciona

O transporte stdio é o mesmo modelo adotado por Claude Desktop, Cursor e Zed. O Ciel sobe o servidor MCP como um **subprocesso filho** e conversa via stdin/stdout usando JSON-RPC 2.0.

```
Ciel CLI (cli.py)
    │
    │  subprocess: python mcp/telegram/server.py
    │  stdin/stdout pipes (JSON-RPC 2.0)
    ▼
Servidor MCP (subprocesso local)
    │
    │  HTTPS
    ▼
API externa (Telegram, Google, GitHub...)
```

Do ponto de vista do Ciel, todos os servidores são iguais. O que muda é o que cada servidor faz internamente — chamar a API do Telegram, do Google, etc. O Ciel não conhece nada sobre HTTP, OAuth ou tokens: só faz `call_tool("send_message", {...})`.

| Agente | Transporte padrão | Config |
|---|---|---|
| Claude Desktop | stdio | `claude_desktop_config.json` |
| Cursor | stdio | `cursor_mcp.json` |
| Zed | stdio | extensões |
| **Ciel** | **stdio** | **`mcp_servers.json`** |

---

## Namespace das tools

Todas as tools MCP seguem o padrão `mcp_{servidor}__{tool}` — duplo underline separa servidor de tool, evitando colisão com tools que têm underline no nome.

```
mcp_telegram__send_message
mcp_telegram__get_updates
mcp_sheets__read_range
mcp_sheets__write_cell
mcp_github__create_issue
```

---

## Integração no cli.py

O `MCPManager` é inicializado uma vez em `main()`, logo após o `load_tools()`:

```python
from mcp import MCPManager

mcp_manager = MCPManager()          # carrega mcp_servers.json
mcp_manager.connect_all()           # conecta todos os servidores habilitados
tools.update(mcp_manager.all_tools())  # injeta no registry
```

As tools MCP convivem no mesmo `ToolRegistry` que as tools permanentes e temporárias. O `run_agent` não precisa de nenhum path especial — o prefixo `mcp_` nos nomes é suficiente para logging e remoção direcionada.

Após qualquer reload de disco (após `create_tool`, `/promover`, troca de agente), as tools MCP são re-injetadas automaticamente:

```python
def _reload_tools(agent_info, safe, mcp_manager=None):
    tools = filter_tools(load_tools(), agent_info["allowed_tools"])
    if mcp_manager:
        tools.update(mcp_manager.all_tools())  # garante que não somem no reload
    return tools, tools_schema(tools)
```

---

## Adicionando um servidor

### Via agente (recomendado)

```
mcp_add_server(
    name="telegram",
    type="stdio",
    command="python",
    args="mcp/telegram/server.py",
    env="TELEGRAM_BOT_TOKEN=seu_token"
)
```

O servidor é conectado imediatamente, as tools aparecem no registry e a configuração é salva em `mcp_servers.json` para as próximas sessões.

### Via CLI

```
/mcp          # lista servidores, status e preview das tools
/mcp -v       # lista com todas as tools de cada servidor
```

### mcp_servers.json (configuração manual)

```json
{
  "servers": [
    {
      "name": "telegram",
      "type": "stdio",
      "command": "python",
      "args": ["mcp/telegram/server.py"],
      "env": { "TELEGRAM_BOT_TOKEN": "..." },
      "timeout": 30.0,
      "enabled": true
    },
    {
      "name": "sheets",
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-gdrive"],
      "env": { "GOOGLE_CREDENTIALS_FILE": "/caminho/credentials.json" },
      "timeout": 30.0,
      "enabled": true
    }
  ]
}
```

Campos disponíveis:

| Campo | Tipo | Descrição |
|---|---|---|
| `name` | string | Identificador único. Vira namespace das tools. |
| `type` | `"stdio"` \| `"sse"` | Transporte. SSE ainda não implementado. |
| `command` | string | Executável (stdio). |
| `args` | list | Argumentos do comando. |
| `url` | string | URL do servidor (sse). |
| `env` | dict | Variáveis de ambiente extras passadas ao subprocesso. |
| `timeout` | float | Segundos por chamada. Padrão: 30. |
| `allowed_tools` | list \| null | Tools a expor. `null` = todas. |
| `enabled` | bool | `false` = não conecta na inicialização. |

---

## Servidor MCP embutido: Telegram

O pacote inclui um servidor MCP próprio para Telegram em `mcp/telegram/server.py`. É um exemplo completo de como implementar um servidor MCP sobre stdio sem depender de nenhuma lib MCP externa — apenas `requests`.

### Tools disponíveis

| Tool | O que faz | Parâmetros obrigatórios |
|---|---|---|
| `mcp_telegram__get_channel` | Resolve canal por nome/username/id, com cache | `name` |
| `mcp_telegram__list_channels` | Lista canais salvos no cache local | — |
| `mcp_telegram__send_message` | Envia mensagem de texto | `channel_id`, `text` |
| `mcp_telegram__send_photo` | Envia foto com legenda opcional | `channel_id`, `photo` |
| `mcp_telegram__edit_message` | Edita mensagem existente enviada pelo bot | `channel_id`, `message_id`, `new_text` |
| `mcp_telegram__delete_message` | Deleta mensagem (bot precisa ser admin) | `channel_id`, `message_id` |
| `mcp_telegram__get_channel_info` | Info do canal: título, tipo, membros | `channel_id` |
| `mcp_telegram__get_updates` | Atualizações recentes; descobre chat_ids privados | — |

### Cache de canais

O `channels.py` mantém um cache local em `telegram_channels.json`. Toda vez que uma mensagem é enviada com sucesso, o chat de destino é salvo automaticamente. Isso permite que o agente resolva canais por nome em vez de precisar lembrar IDs numéricos.

```
get_channel("Ciel")  →  {"title": "Ciel", "id": "-1001234567890", "username": ""}
```

O arquivo `telegram_channels.json` deve ser adicionado ao `.gitignore`.

### Como conectar

```
mcp_add_server(
    name="telegram",
    type="stdio",
    command="python",
    args="mcp/telegram/server.py",
    env="TELEGRAM_BOT_TOKEN=123456789:ABCdef..."
)
```

Para o tutorial completo de configuração (criar bot, obter token, configurar canal), veja `docs/mcp_telegram_tutorial.md`.

---

## Resiliência

- **Timeout por chamada** — configurável por servidor (`timeout`, padrão 30s). Evita que uma chamada MCP travada bloqueie o loop do agente.
- **Retry com backoff exponencial** — 3 tentativas com espera de 1s → 2s → 4s entre elas.
- **Encoding UTF-8 garantido** — `PYTHONIOENCODING=utf-8` é injetado no ambiente de todo subprocesso. Corrige corrupção de caracteres não-ASCII no Windows (onde o padrão do console é `cp1252`).
- **Processo zumbi evitado** — `disconnect_all()` chamado automaticamente no `/sair`.
- **Reload sem perda** — tools MCP re-injetadas após qualquer reload de disco (`create_tool`, `/limpar-temp`, `/promover`, troca de agente).
- **Token ausente não trava o servidor** — o servidor Telegram responde normalmente ao handshake e informa o erro apenas na chamada da tool, permitindo que o servidor seja registrado antes de o token ser configurado.

---

## Testes

Todos os testes rodam sem servidor externo — usam um servidor fake embutido como subprocesso.

```bash
python test_mcp_client.py    # 9/9   protocolo JSON-RPC, handshake, timeouts
python test_mcp_adapter.py   # 14/14 conversão de schema, namespace, callables
python test_mcp_manager.py   # 16/16 ciclo de vida, persistência, reconnect
```

---

## Segurança

O `mcp_servers.json` e o `telegram_channels.json` podem conter tokens e IDs sensíveis. Adicione ambos ao `.gitignore`:

```
mcp_servers.json
telegram_channels.json
```

Se preferir não passar o token direto no `mcp_add_server`, defina a variável de ambiente antes de iniciar o Ciel:

```bash
# Linux/macOS
export TELEGRAM_BOT_TOKEN="seu_token"

# Windows (PowerShell)
$env:TELEGRAM_BOT_TOKEN="seu_token"
```

---

## Pendente

- **SSE/HTTP transport** — para servidores remotos (`_connect_sse()` é um stub)
- Healthcheck periódico para detectar processos mortos automaticamente

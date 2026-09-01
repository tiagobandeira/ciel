# Telegram via MCP — tutorial de integração

Do zero ao envio da primeira mensagem. O servidor MCP para Telegram está
incluído no projeto em `mcp/telegram/server.py` — sem dependências externas
além de `requests`.

---

## Pré-requisitos

- Ciel instalado e rodando dentro de um `venv`
- Python 3.10+
- `pip install requests` (única dependência do servidor Telegram)
- Conta no Telegram

---

## Passo 1 — Criar o bot no BotFather

1. No Telegram, busque por **@BotFather** (verificado ✅)
2. Envie `/newbot` e siga os prompts:
   - **Nome do bot** (ex: `Ciel MCP Bot`)
   - **Username** — deve terminar em `bot` (ex: `ciel_mcp_bot`)
3. O BotFather devolve um token no formato:

```
123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
```

> ⚠️ Nunca commite o token no git. Use variável de ambiente ou `.env` no `.gitignore`.

---

## Passo 2 — Criar o canal e adicionar o bot como admin

1. Crie um canal (ou use um existente)
2. Configurações do canal → **Administradores** → **Adicionar administrador**
3. Busque pelo username do bot (ex: `@ciel_mcp_bot`)
4. Conceda as permissões:
   - ✅ Publicar mensagens
   - ✅ Editar mensagens de outros
   - ✅ Apagar mensagens

---

## Passo 3 — Verificar o token

Acesse no navegador:

```
https://api.telegram.org/bot<SEU_TOKEN>/getMe
```

Resposta esperada:

```json
{
  "ok": true,
  "result": {
    "id": 123456789,
    "is_bot": true,
    "first_name": "Ciel MCP Bot",
    "username": "ciel_mcp_bot"
  }
}
```

Se retornar `"ok": false`, o token está errado — copie novamente do BotFather.

---

## Passo 4 — Obter o ID do canal (apenas para canais privados)

**Canal público:** use o `@username` diretamente, sem precisar do ID.

**Canal privado:**

1. Envie qualquer mensagem no canal
2. Acesse:

```
https://api.telegram.org/bot<SEU_TOKEN>/getUpdates
```

3. Localize `chat.id` no JSON:

```json
{
  "result": [{
    "channel_post": {
      "chat": {
        "id": -1001234567890,
        "title": "Meu Canal Privado"
      }
    }
  }]
}
```

O ID tem formato `-100XXXXXXXXXX` (número negativo). Guarde-o.

> Se `"result": []`, envie uma mensagem no canal e tente de novo.
> Alternativamente, use a tool `mcp_telegram__get_updates` depois de conectar.

---

## Passo 5 — Testar o servidor manualmente

Antes de adicionar ao Ciel, confirme que o servidor sobe:

```bash
# Linux / macOS
TELEGRAM_BOT_TOKEN="123456789:ABCdef..." python mcp/telegram/server.py

# Windows (PowerShell)
$env:TELEGRAM_BOT_TOKEN="123456789:ABCdef..."
python mcp/telegram/server.py
```

O processo fica em silêncio aguardando JSON no stdin — comportamento correto.
Use `Ctrl+C` para encerrar.

---

## Passo 6 — Adicionar o servidor ao Ciel

Inicie o Ciel e peça ao agente:

```
mcp_add_server(
    name="telegram",
    type="stdio",
    command="python",
    args="mcp/telegram/server.py",
    env="TELEGRAM_BOT_TOKEN=123456789:ABCdef..."
)
```

Resposta esperada:

```
Servidor 'telegram' conectado com 8 tool(s): mcp_telegram__get_channel,
mcp_telegram__list_channels, mcp_telegram__send_message, ...
```

A configuração é salva em `mcp_servers.json` e recarregada automaticamente
nas próximas sessões.

---

## Passo 7 — Verificar a integração

```
/mcp -v
```

```
● telegram  [stdio]  conectado (8 tools)
  servidor: telegram v1.1.0
    • mcp_telegram__get_channel
    • mcp_telegram__list_channels
    • mcp_telegram__send_message
    • mcp_telegram__send_photo
    • mcp_telegram__edit_message
    • mcp_telegram__delete_message
    • mcp_telegram__get_channel_info
    • mcp_telegram__get_updates
```

---

## Passo 8 — Enviar a primeira mensagem

```
Manda "Hello from Ciel MCP! 🤖" pro canal @meu_canal
```

O agente usa `mcp_telegram__send_message`:

```
channel_id = "@meu_canal"
text       = "Hello from Ciel MCP! 🤖"
```

Resposta:

```
Mensagem enviada. message_id: 42
```

---

## Cache de canais

Toda mensagem enviada com sucesso salva o canal em `telegram_channels.json`.
Nas próximas interações, o agente pode resolver canais por nome:

```
Manda um resumo pro canal "Ciel Notícias"
```

O agente chama `mcp_telegram__get_channel("Ciel Notícias")` para resolver o
`channel_id` antes de enviar — sem precisar que você lembre o ID numérico.

---

## Tools disponíveis

| Tool | O que faz | Parâmetros obrigatórios |
|---|---|---|
| `mcp_telegram__get_channel` | Resolve canal por nome/username/id | `name` |
| `mcp_telegram__list_channels` | Lista canais no cache local | — |
| `mcp_telegram__send_message` | Envia mensagem de texto | `channel_id`, `text` |
| `mcp_telegram__send_photo` | Envia foto com legenda | `channel_id`, `photo` |
| `mcp_telegram__edit_message` | Edita mensagem existente | `channel_id`, `message_id`, `new_text` |
| `mcp_telegram__delete_message` | Deleta mensagem | `channel_id`, `message_id` |
| `mcp_telegram__get_channel_info` | Info do canal (título, membros) | `channel_id` |
| `mcp_telegram__get_updates` | Atualizações recentes; descobre chat_ids | — |

---

## Gerenciando o servidor

```
# Ver status
/mcp

# Ver todas as tools
/mcp -v

# Remover
mcp_remove_server(name="telegram")

# Re-adicionar (ex: após trocar o token)
mcp_remove_server(name="telegram")
mcp_add_server(name="telegram", type="stdio", command="python",
               args="mcp/telegram/server.py", env="TELEGRAM_BOT_TOKEN=novo_token")
```

---

## Segurança

Adicione ao `.gitignore` antes de commitar:

```gitignore
mcp_servers.json
telegram_channels.json
.env
```

Para não passar o token direto no `mcp_add_server`, defina antes de iniciar o Ciel:

```bash
# Linux/macOS (~/.bashrc ou ~/.zshrc)
export TELEGRAM_BOT_TOKEN="123456789:ABCdef..."

# Windows (PowerShell — permanente para o usuário)
[System.Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "...", "User")
```

---

## Troubleshooting

**Servidor não conecta / timeout**

Confirme que o caminho para `server.py` está correto. Se o Ciel for iniciado
de outro diretório, use o caminho absoluto:

```
args="C:\\Users\\usuario\\Ciel\\mcp\\telegram\\server.py"
```

**"Chat not found"**

- Canal público: use `@nome` (com `@`)
- Canal privado: use o ID numérico (`-1001234567890`)
- Confirme que o bot é administrador do canal

**"Not enough rights"**

O bot precisa de permissão de admin com "Publicar mensagens" habilitado.

**Servidor aparece como desconectado no /mcp**

```
mcp_remove_server(name="telegram")
mcp_add_server(name="telegram", ...)
```

**Token inválido após re-criação do bot**

O token muda se o bot for recriado. Remova e adicione novamente com o novo token.

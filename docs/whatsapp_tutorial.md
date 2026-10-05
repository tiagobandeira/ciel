# WhatsApp — tutorial de integração

Do zero ao primeiro "oi" recebido pelo Ciel. A integração usa um bridge local
incluído no próprio projeto em `mcp/whatsapp/bridge.js`, escrito em Node.js
com Baileys — sem dependências externas de Go, sem serviços externos. O `python ciel.py bot` sobe esse bridge sozinho, então
você só precisa de um terminal.

Dois modos disponíveis, independentes entre si:

| Modo | O que faz |
|---|---|
| **Bot** | Ciel fica escutando mensagens recebidas e responde em tempo real |
| **MCP** | Modelo usa WhatsApp como tool pontual dentro de qualquer task ou conversa |

Este tutorial cobre o **Modo Bot** do início ao fim. O Modo MCP é abordado
mais adiante.

---

## Como funciona

```
 Seu celular                     Seu computador
┌────────────────┐         ┌──────────────────────────────────────┐
│ WhatsApp       │         │  bridge.js (Node)   ──►  ciel bot    │
│ (seu número)   │ ──────► │  porta 8765         POST  porta 8766 │
│                │ ◄────── │  (Baileys)          ◄──  /send       │
└────────────────┘         └──────────────────────────────────────┘
        mensagem                  webhook / resposta
```

O bridge fica conectado ao WhatsApp como um **aparelho vinculado** (igual ao
WhatsApp Web). Cada mensagem recebida vira um POST para o webhook do Ciel,
que roda o agente e devolve a resposta via `POST /send` do bridge.

Ao rodar `python ciel.py bot`, o Ciel inicia o bridge junto e o encerra ao
sair. Para quem prefere rodar o bridge à mão (ou usar outro), existe a opção
`--no-bridge`.

### Os dois números

Existem dois números envolvidos, e é fácil confundir:

| | Número do **Ciel** | Número do **usuário** |
|---|---|---|
| Papel | É a "conta" do bot | É quem conversa com o bot |
| Onde fica | Pareado com o bridge (QR) | Na `allow_from` |
| Exemplo | WhatsApp Business com um chip/número dedicado | Seu WhatsApp pessoal |

Fluxo típico: você abre o seu WhatsApp pessoal e manda mensagem **para o
número do Ciel**. O bridge, pareado na conta do Ciel, recebe e responde.

> **Exemplo de uso real:** o WhatsApp comum fica com o número pessoal e o
> WhatsApp Business, no mesmo celular, fica com o número do Ciel. O QR do
> bridge é escaneado pelo app Business.

### Dá para usar um número só?

**Hoje, não de forma direta.** Se o bridge estiver pareado no seu próprio
número e você mandar mensagem para si mesmo (conversa "Você"), o WhatsApp
entrega o evento com `from_me: true`. O bot descarta esses eventos de
propósito, porque as respostas do próprio bot também chegam como `from_me`
e isso criaria um loop infinito.

Suportar número único exigiria aceitar `from_me` apenas na conversa consigo
mesmo e ignorar o que o próprio bot enviou. Isso ainda não está implementado
(veja [Limitações conhecidas](#limitações-conhecidas)). Por enquanto,
use dois números.

### O que é o LID (e por que seu número não bate)

Versões recentes do WhatsApp identificam contatos por um ID interno, o
**LID** (`123456789012345@lid`), em vez do telefone. O bridge repassa o que o
WhatsApp entrega, então o `sender` que chega ao Ciel muitas vezes não é o
telefone, e sim algo como `+999999999999999`.

Consequência: **colocar só o telefone na `allow_from` pode não funcionar**.
O LID é o identificador da conta de quem está mandando (o seu), visto pela
conta do Ciel. Ele é estável para a mesma conta, mas muda se você trocar de
conta ou aparelho.

Como descobrir o seu LID: veja o [Passo 4](#passo-4--primeiro-oi-e-liberar-o-lid).

---

## Pré-requisitos

- Ciel instalado e rodando (Python 3.10+, `venv` ativado)
- Node.js 20+ ([nodejs.org](https://nodejs.org))
- **Git instalado e no PATH** (o `npm install` do Baileys precisa dele, veja abaixo)
- Celular com WhatsApp (comum ou Business) para escanear o QR
- Um segundo número para conversar com o bot (veja [Os dois números](#os-dois-números))

Verifique:

```bash
node -v    # deve ser v20 ou superior
git --version
```

---

## Passo 1 — Instalar o bridge

```bash
cd mcp/whatsapp
npm install
```

Isso instala o Baileys e o Express. Só precisa fazer uma vez.

> **Falhou?** O Baileys declara uma dependência que o npm baixa direto de um
> repositório Git. Sem o Git instalado (ou fora do PATH), a instalação falha
> com erro de conflito ou de dependência. Veja
> [Erro no `npm install`](#erro-no-npm-install) em Troubleshooting.

---

## Passo 2 — Configurar o canal no Ciel

No Ciel, execute:

```
/criar canal whatsapp
```

A entrevista vai perguntar:

1. **Modo** — Bot, MCP, ou ambos
2. **Agente** — qual agente vai atender as mensagens (ex: `general`)
3. **Número permitido** — o **seu** número pessoal (quem vai falar com o
   bot), no formato `+55 11 99999-9999`
4. **Bridge URL** — aceite o padrão (`http://127.0.0.1:8765`)

O Ciel grava `whatsapp_channels.json` na raiz do projeto:

```json
{
  "bridge_url": "http://127.0.0.1:8765",
  "bot": {
    "enabled": true,
    "agent": "general",
    "allow_from": ["+55 11 99999-9999"],
    "groups": {
      "policy": "allowlist",
      "allow_from": []
    },
    "dm_policy": "allowlist"
  },
  "mcp": {
    "enabled": false
  }
}
```

A comparação ignora espaços, hífens e parênteses: `+55 11 99999-9999` e
`+5511999999999` são equivalentes.

> ⚠️ Adicione `whatsapp_channels.json`, `mcp/whatsapp/auth/` e
> `mcp/whatsapp/node_modules/` ao `.gitignore`.

---

## Passo 3 — Subir o modo bot e parear pelo QR

Com o canal configurado, abra um terminal na raiz do projeto, com o `venv`
ativado, e rode:

```bash
python ciel.py bot
```

O Ciel sobe o bridge junto com o webhook e o encerra quando você sai
(Ctrl+C). Não é preciso rodar `node bridge.js` à parte.

Na primeira execução, o QR aparece **neste mesmo terminal**:

```
[whatsapp] Primeiro pareamento: o bridge vai mostrar um QR neste terminal.
           No celular: WhatsApp > Aparelhos conectados > Conectar um aparelho.
[bridge] Iniciando conexão WhatsApp…
[bridge] HTTP em 127.0.0.1:8765
[bridge] Webhook do Ciel: http://127.0.0.1:8766/webhook

[bridge] Escaneie o QR com o WhatsApp:

(QR code)
```

No celular, **no app da conta que será o Ciel** (por exemplo, o WhatsApp
Business):

1. **⋮** (três pontos) → **Aparelhos conectados**
2. **Conectar um aparelho**
3. Escaneie o QR

Logo após o pareamento é normal aparecer uma reconexão rápida antes da
confirmação:

```
  10:55:15  reconectando em 2s (tentativa 1)…
  10:55:19  ✓ WhatsApp conectado
```

Em seguida o banner mostra o status da conexão:

```
╭─────────────────────────────────────────╮
│  Ciel CLI (V1.0.0)  ·  Modo Bot         │
│                                         │
│  canal:   WhatsApp  ● conectado         │
│  agente:  general   model: gemma4:cloud │
│  MCP:     desabilitado                  │
│  webhook: 127.0.0.1:8766/webhook        │
│                                         │
│  permitidos:                            │
│  +55 11 99999-9999                      │
│                                         │
│  Ctrl+C para encerrar                   │
╰─────────────────────────────────────────╯

  Servidor de webhook iniciado. Aguardando mensagens…
```

A sessão fica salva em `mcp/whatsapp/auth/`. Nas próximas execuções o QR
não aparece mais.

### Rodar o bridge por conta própria (`--no-bridge`)

Se você prefere controlar o bridge (por exemplo, para usar outro bridge ou
separar os logs), suba cada um num terminal:

```bash
# terminal 1
cd mcp/whatsapp
node bridge.js

# terminal 2 (raiz do projeto, venv ativado)
python ciel.py bot --no-bridge
```

Ordem recomendada: bot primeiro, bridge depois. O bridge tenta entregar cada
mensagem ao webhook 3 vezes (esperando 1s e 2s entre as tentativas). Se o bot
continuar fora do ar, a mensagem é descartada.

Nesse modo valem as regras de [Ambientes](#ambientes-windows-wsl-e-docker) e as
[variáveis de ambiente do bridge](#variáveis-de-ambiente-do-bridge).

---

## Passo 4 — Primeiro "oi" e liberar o LID

Do seu WhatsApp pessoal, envie uma mensagem para o **número do Ciel**.

**Se o telefone na `allow_from` bater**, o agente responde direto. Mas, como
explicado em [O que é o LID](#o-que-é-o-lid-e-por-que-seu-número-não-bate),
é comum o remetente chegar como LID. Nesse caso o terminal mostra o evento
recebido (do bridge) e o descarte (do bot):

```
  02:36:46  ← +999999999999999 (direct)
  02:36:46  ✗ erro (ignorado)  remetente '+999999999999999' (direct) fora da allowlist | chat_id=999999999999999@lid
```

Esse `remetente` é o valor que você precisa liberar. Copie-o para a
`allow_from` de `whatsapp_channels.json` (mantendo o `+` na frente):

```json
"allow_from": ["+55 11 99999-9999", "+999999999999999"]
```

Não precisa reiniciar nada: a config é lida a cada mensagem. Envie outra
mensagem e o terminal passa a mostrar o agente trabalhando e a resposta
enviada:

```
  02:44:12  ← +999999999999999 (direct)
  02:44:12  step 1 › modelo  aguardando…
  02:44:15  step 1 › done  Tô sim! Como posso te ajudar?
  02:44:15  ✓ done  1 steps · 9134↑ 20↓ tokens
  02:44:15  → resposta enviada (23 chars)
```

> Libere apenas LIDs que você reconhece. Se `remetente` for de alguém que
> você não conhece, não adicione.

Mensagens `from_me` (enviadas pela própria conta do Ciel, por exemplo pelo
celular onde ela está logada) são descartadas de propósito e não aparecem no
log.

---

## Ambientes: Windows, WSL e Docker

**Regra principal: bridge e bot precisam rodar no mesmo ambiente** (os dois no
Windows, ou os dois no WSL). No WSL2, `127.0.0.1` do Linux e `127.0.0.1` do
Windows são máquinas diferentes. Como o bridge e o bot só escutam em
`127.0.0.1` (de propósito, por segurança), um não enxerga o outro.

No fluxo padrão (`python ciel.py bot`) isso é automático: o bridge sobe no mesmo
ambiente do bot. O `node` e as dependências do `npm install` precisam existir
nesse ambiente. A regra pesa de verdade com `--no-bridge`, quando você sobe
cada um à mão.

### Windows nativo (recomendado)

Instale o [Git for Windows](https://git-scm.com/download/win) e o Node.js 20+,
abra um **novo** terminal (para o PATH atualizar) e siga o tutorial normalmente.

### WSL

Funciona, desde que **os dois** rodem no WSL: o Python do Ciel, com o
`venv` criado no Linux, e o bridge.

Se você precisa manter o Ciel no Windows e o bridge no WSL, ative a rede
espelhada (Windows 11 22H2 ou superior). Crie ou edite
`C:\Users\<usuario>\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Depois rode `wsl --shutdown` no PowerShell e abra o WSL de novo. Com isso o
`127.0.0.1` passa a ser o mesmo dos dois lados.

> Evite a alternativa de apontar o bridge para o IP do Windows e abrir o bot
> em `0.0.0.0`: o webhook não tem autenticação e ficaria exposto na sua rede.

> **Como foi resolvido no desenvolvimento:** o `npm install` falhava no
> Windows (dependência via Git) e foi concluído pelo WSL. Em seguida o bridge
> foi iniciado no WSL, enquanto o bot rodava no PowerShell, e todas as
> mensagens falharam com `ECONNREFUSED`. A correção foi rodar o bridge no
> PowerShell, junto do bot. A sessão em `auth/` e as dependências já
> instaladas foram reaproveitadas.

### Docker (planejado, ainda não disponível)

Ainda não há imagem nem `docker-compose.yml` no projeto. Para suportar, falta:

- Permitir configurar o endereço de escuta do bridge (hoje fixo em
  `127.0.0.1`, que dentro de um container não é alcançável de fora).
- Permitir configurar o endereço de escuta do webhook do bot.
- Persistir `mcp/whatsapp/auth/` em um volume, para não reparear a cada
  reinício.
- Instalar o Git na imagem (necessário para o `npm install`).

O desenho mais seguro seria colocar bridge e bot no mesmo `docker compose`,
em uma rede interna, sem publicar as portas `8765` e `8766` para fora. Se
você precisar publicar alguma, use `127.0.0.1:porta:porta`.

---

## Opções do comando bot

```bash
python ciel.py bot                          # agente e modelo da config
python ciel.py bot --model llama3.2         # sobrescreve o modelo
python ciel.py bot --agent dev_helper       # troca o agente (veja a nota)
python ciel.py bot --safe                   # desabilita tools de execução arbitrária
python ciel.py bot --no-bridge              # não sobe o bridge (você roda node bridge.js à parte)
```

> **Nota sobre `--agent`:** além de usar o agente informado, esta opção
> **grava** o agente em `whatsapp_channels.json` e força `bot.enabled = true`.
> Ou seja, a troca persiste nas próximas execuções.

## Variáveis de ambiente do bridge

Só valem ao rodar o bridge à mão (`--no-bridge`). No modo padrão o Ciel usa a
`bridge_url` da config e a porta 8766 do webhook.

```bash
# porta HTTP do bridge (padrão: 8765)
BRIDGE_PORT=8765 node bridge.js

# URL do webhook do Ciel (padrão: http://127.0.0.1:8766/webhook)
CIEL_WEBHOOK_URL=http://127.0.0.1:8766/webhook node bridge.js

# logs detalhados do Baileys (útil pra debug)
LOG_LEVEL=info node bridge.js
```

No PowerShell, defina antes e rode em seguida:

```powershell
$env:LOG_LEVEL = "info"
node bridge.js
```

---

## Modo MCP (envio pontual)

O Modo MCP permite que qualquer agente envie mensagens pelo WhatsApp durante
uma task ou conversa, sem o Ciel estar em modo bot.

Pré-requisito: bridge rodando. Ele só sobe automaticamente junto do
`python ciel.py bot`; para usar só o MCP, rode `cd mcp/whatsapp && node bridge.js`
(pareando pelo QR na primeira vez, como no [Passo 3](#passo-3--subir-o-modo-bot-e-parear-pelo-qr)).

Ative o MCP na entrevista (`/criar canal whatsapp`) ou edite
`whatsapp_channels.json` manualmente:

```json
"mcp": { "enabled": true }
```

A tool `whatsapp_send` fica disponível automaticamente:

```
Manda "build finalizado ✅" pro número +55 11 99999-9999
```

O agente chama `whatsapp_send(chat_id="5511999999999@s.whatsapp.net", text="build finalizado ✅")`.

O `chat_id` pode ser o JID do telefone (`...@s.whatsapp.net`) ou o LID que
aparece nos logs (`...@lid`).

---

## Usando outro bridge (Evolution API, etc.)

O Ciel só depende do contrato HTTP — qualquer bridge que respeite os endpoints
abaixo funciona sem mudar código:

| Endpoint | Método | O que faz |
|---|---|---|
| `/status` | GET | retorna `{"status": "connected"\|"waiting_qr"\|"disconnected"}` |
| `/send` | POST | recebe `{"chat_id": "...", "text": "..."}` e envia |
| webhook do Ciel | POST | o bridge envia `{"chat_id", "sender", "text", "type", "from_me", "mentions"}` |

Para usar outro bridge, basta apontar `bridge_url` em `whatsapp_channels.json`
para a URL do bridge alternativo e rode o bot com `--no-bridge`, para o Ciel não
subir o `bridge.js` embutido. O payload recebido pode precisar de um
adaptador — abra uma issue se precisar de ajuda.

Atenção: o campo `sender` precisa ser comparável com a `allow_from`. Se o
seu bridge entrega LIDs, valem as mesmas regras do
[Passo 4](#passo-4--primeiro-oi-e-liberar-o-lid).

---

## Segurança

Adicione ao `.gitignore`:

```gitignore
whatsapp_channels.json
mcp/whatsapp/auth/
mcp/whatsapp/node_modules/
```

- `mcp/whatsapp/auth/` é a **sessão do WhatsApp do Ciel**. Quem tiver essa
  pasta controla a conta. Nunca commite nem compartilhe.
- `whatsapp_channels.json` contém seu número e seu LID.

**Allowlist vazia = nenhuma mensagem processada.** O Ciel é fail-closed por
padrão: se `allow_from` estiver vazio, todas as mensagens são ignoradas (e
cada descarte aparece no log como `✗ erro (ignorado)`).

**O agente executa tools no computador de quem roda o bot.** Quem consegue
mandar mensagem por um número liberado (incluindo alguém com acesso ao seu
celular ou ao WhatsApp Web) fala com esse agente. Recomendações:

- Rode com `--safe` para desabilitar `run_script` e `create_tool`.
- Revise o `allowed_tools` do agente usado pelo bot e deixe só o necessário.
- **Não use `dm_policy: "pairing"`**: hoje ele aceita qualquer remetente, e a
  aprovação manual descrita no código ainda não existe.
- Nunca exponha as portas `8765` e `8766` para a internet — use sempre
  `127.0.0.1`.

---

## Limitações conhecidas

- **Número único não suportado:** mensagens `from_me` são descartadas, então
  não dá para conversar com o bot pela conversa "Você" do mesmo número.
- **Liberação do LID é manual:** quando o remetente chega como LID, é preciso
  copiar o valor do log para `allow_from` em `whatsapp_channels.json`.
- **Só texto:** áudio, imagem sem legenda e stickers são ignorados. Legendas
  de imagem e vídeo são tratadas como texto.
- **Histórico em memória:** cada chat mantém as últimas 40 mensagens e tudo
  é perdido ao reiniciar o bot.
- **Comandos `/` não são executados:** `/task`, `/tool` etc. chegam ao modelo
  como texto comum. O modelo pode interpretar, mas não é o mesmo
  comportamento da CLI.
- **Grupos:** a política `mention_only` ainda não está implementada, e na
  política `allowlist` a verificação de grupos precisa ser revisada. Use o
  bot apenas em conversas diretas.
- **Mensagens perdidas:** se o bot estiver fora do ar, o bridge tenta 3 vezes e
  descarta. Não há fila.
- **Formatação:** o WhatsApp usa `*negrito*` (um asterisco). Respostas do
  modelo com `**negrito**` aparecem com asteriscos sobrando.
- **Custo de contexto:** cada mensagem envia o prompt do agente e o schema das
  tools (na casa de 9 mil tokens de entrada com o agente `general`). Agentes
  com menos tools ficam mais baratos e mais estáveis.

---

## Troubleshooting

### Erro no `npm install`

O Baileys tem uma dependência que o npm baixa de um repositório Git. Se o Git
não estiver instalado ou não estiver no PATH, a instalação falha com erro de
dependência/conflito, geralmente mencionando `git`.

1. Instale o Git ([git-scm.com](https://git-scm.com)).
2. Abra um **novo** terminal e confirme com `git --version`.
3. Limpe e reinstale:

```bash
cd mcp/whatsapp
rm -rf node_modules package-lock.json   # PowerShell: Remove-Item -Recurse -Force node_modules, package-lock.json
npm install
```

Se não puder instalar o Git no Windows, uma saída é rodar o `npm install`
no WSL (que normalmente já tem Git). Depois siga a regra de
[Ambientes](#ambientes-windows-wsl-e-docker): bridge e bot no mesmo ambiente.
Se o bridge apresentar erros estranhos ao rodar no Windows com dependências
instaladas pelo WSL, apague `node_modules` e reinstale com o Git disponível no
Windows.

> Se você for commitar o `package-lock.json`, faça isso depois de uma
> instalação bem-sucedida: ele trava as versões que funcionaram.

### `fetch failed (ECONNREFUSED)` no bridge

O bridge não conseguiu abrir conexão com o webhook do Ciel. Com o bridge
iniciado pelo `ciel bot` isso é raro; costuma acontecer com `--no-bridge`.
Verifique:

- O bot está rodando? Rode `netstat -ano | findstr 8766` (Windows) ou
  `ss -ltn | grep 8766` (Linux). Precisa aparecer `LISTENING`/`LISTEN`.
- Bridge e bot estão **no mesmo ambiente**? (Bridge no WSL + bot no Windows
  causa exatamente esse erro. Veja [Ambientes](#ambientes-windows-wsl-e-docker).)
- A porta bate com `CIEL_WEBHOOK_URL`?

Para testar o webhook manualmente (PowerShell):

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8766/webhook -Method Post -ContentType "application/json" -Body '{"chat_id":"x@s.whatsapp.net","sender":"+55 00 00000-0000","text":"teste","type":"direct","from_me":false,"mentions":[]}'
```

### O bot encerra logo ao iniciar

O Ciel imprime uma mensagem `[whatsapp] ...` e sai. Os casos mais comuns:

- **Porta do webhook em uso** (`Não consegui abrir a porta 8766`): já existe
  outro `ciel bot` rodando. Encerre-o e tente de novo.
- **Falha ao subir o bridge:** confira Node 20+ no ambiente atual e se o
  `npm install` em `mcp/whatsapp` foi concluído (veja
  [Erro no `npm install`](#erro-no-npm-install)).
- **Modo bot não habilitado:** rode `/criar canal whatsapp` ou ajuste
  `bot.enabled` em `whatsapp_channels.json`.

### Mensagem enviada mas Ciel não responde

Olhe o terminal do bot:

| O que aparece | Causa |
|---|---|
| `✗ erro (ignorado) ... fora da allowlist` | O `remetente` mostrado não está na `allow_from`. Copie-o (veja o [Passo 4](#passo-4--primeiro-oi-e-liberar-o-lid)). |
| `←` aparece mas nada do bot depois | O webhook não está recebendo (comum com `--no-bridge`): veja `ECONNREFUSED` acima. |
| Nada em nenhum dos dois | O WhatsApp não entregou: confira o número de destino e se o bridge está `✓ conectado`. |
| Só aparecem eventos do bridge sem `←` | A mensagem foi enviada pela própria conta do Ciel (`from_me`), que não é exibida nem processada. |

### Estou conversando comigo mesmo e nada acontece

Veja [Dá para usar um número só?](#dá-para-usar-um-número-só). Mande a
mensagem de **outro** número para o número pareado com o bridge.

### Banner mostra `○ desconectado`

O bridge não está rodando (com `--no-bridge`, ou se caiu depois de subir) ou
está em outra porta. Verifique:

```bash
curl http://127.0.0.1:8765/status
# esperado: {"status":"connected"}
```

### QR não aparece na segunda execução

Normal: a sessão está salva em `auth/`. Se quiser reparear:

```bash
rm -rf mcp/whatsapp/auth/
python ciel.py bot
```

### Respostas estranhas ou cortadas (`parse error` no log)

Quando o modelo responde em texto puro e o loop espera outro formato, o
Ciel pede nova tentativa, e a segunda resposta pode sair pior (ou comentar o
próprio formato). Isso dobra o consumo de tokens e é uma limitação do loop
agêntico, não do WhatsApp. Modelos maiores e agentes com menos tools reduzem
o problema.

### Resposta chega duplicada

Verifique se há duas instâncias de `node bridge.js` ou `python ciel.py bot`
rodando em paralelo.

### Bridge reconecta em loop

O Baileys tenta reconectar automaticamente com backoff exponencial (até 30s,
no máximo 10 tentativas). Se o loop não parar, verifique a conexão com a
internet e o status do WhatsApp no celular. Se aparecer
`Sessão encerrada`, a conta foi desconectada em **Aparelhos conectados**:
apague `mcp/whatsapp/auth/` e pareie de novo.
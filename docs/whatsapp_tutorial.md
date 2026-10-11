# WhatsApp — tutorial de integração

Do zero ao primeiro "oi" recebido pelo Ciel. A integração usa um bridge local
incluído no próprio projeto em `mcp/whatsapp/bridge.js`, escrito em Node.js
com Baileys — sem dependências externas de Go, sem serviços externos. O
`python ciel.py bot` sobe esse bridge sozinho, então você só precisa de um
terminal.

Dois modos disponíveis, independentes entre si:

| Modo | O que faz |
|---|---|
| **Bot** | Ciel fica escutando mensagens recebidas e responde em tempo real |
| **MCP** | Modelo usa WhatsApp como tool pontual dentro de qualquer task ou conversa |

Este tutorial cobre o **Modo Bot** do início ao fim. O Modo MCP é abordado
mais adiante. Para usar o Ciel num grupo, veja [Grupos](#grupos).

## Caminho rápido

Se você já sabe o que está fazendo, são quatro passos (cada um é detalhado
mais abaixo):

```bash
cd mcp/whatsapp && npm install   # 1. uma vez só
# no Ciel:  /criar canal whatsapp  # 2. configurar (entrevista)
python ciel.py bot               # 3. sobe o bot e o bridge; escaneie o QR
```

4. Mande um "oi" do seu WhatsApp para o número do Ciel. Se o terminal mostrar
   `fora da allowlist`, copie o `remetente` do log para `allow_from` em
   `whatsapp_channels.json` (veja o [Passo 4](#passo-4--primeiro-oi-e-liberar-o-lid)).

## Índice

**Do zero ao primeiro "oi"**

- [Como funciona e os dois números](#como-funciona)
- [Pré-requisitos](#pré-requisitos)
- [Passo 1 — Instalar o bridge](#passo-1--instalar-o-bridge)
- [Passo 2 — Configurar o canal no Ciel](#passo-2--configurar-o-canal-no-ciel)
- [Passo 3 — Subir o modo bot e parear pelo QR](#passo-3--subir-o-modo-bot-e-parear-pelo-qr)
- [Passo 4 — Primeiro "oi" e liberar o LID](#passo-4--primeiro-oi-e-liberar-o-lid)

**Extras (opcional)**

- [Comandos no WhatsApp](#comandos-no-whatsapp)
- [Grupos](#grupos)
- [Iniciar junto com o Windows](#iniciar-junto-com-o-windows)
- [Modo MCP (envio pontual)](#modo-mcp-envio-pontual)

**Referência**

- [Opções do comando bot](#opções-do-comando-bot) · [Variáveis de ambiente](#variáveis-de-ambiente-do-bridge) · [Ambientes (Windows, WSL, Docker)](#ambientes-windows-wsl-e-docker)
- [Usando outro bridge](#usando-outro-bridge-evolution-api-etc) · [Segurança](#segurança) · [Limitações conhecidas](#limitações-conhecidas)

**Deu problema?**

- [Troubleshooting](#troubleshooting)

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

**Hoje, não.** Use dois números (veja acima).

<details>
<summary>Por quê</summary>

Se o bridge estiver pareado no seu próprio número e você mandar mensagem para si
mesmo (conversa "Você"), o WhatsApp entrega o evento com `from_me: true`. O bot
descarta esses eventos de propósito, porque as respostas do próprio bot também
chegam como `from_me` e isso criaria um loop infinito.

Suportar número único exigiria aceitar `from_me` apenas na conversa consigo
mesmo e ignorar o que o próprio bot enviou. Isso ainda não está implementado
(veja [Limitações conhecidas](#limitações-conhecidas)).

</details>

### O que é o LID (e por que seu número não bate)

Versões recentes do WhatsApp identificam contatos por um ID interno, o **LID**
(`123456789012345@lid`), em vez do telefone. Por isso o `sender` que chega ao
Ciel muitas vezes é algo como `+999999999999999`, e **colocar só o telefone na
`allow_from` pode não funcionar**.

Sem problema: no [Passo 4](#passo-4--primeiro-oi-e-liberar-o-lid) você copia o
valor certo do log. Em grupos vale o mesmo para cada membro (veja
[Grupos](#grupos)).

<details>
<summary>Mais detalhes</summary>

O LID é o identificador da conta de quem está mandando (a sua), visto pela conta
do Ciel. Ele é estável para a mesma conta, mas muda se você trocar de conta ou
aparelho. O bridge só repassa o que o WhatsApp entrega.

</details>

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
      "chats": {}
    },
    "dm_policy": "allowlist"
  },
  "mcp": {
    "enabled": false
  }
}
```

O arquivo gerado também traz chaves `_comentario*` com um resumo do formato;
pode ignorá-las. `groups.chats` começa vazio: para usar o Ciel em grupo, veja
[Grupos](#grupos).

A comparação ignora espaços, hífens e parênteses: `+55 11 99999-9999` e
`+5511999999999` são equivalentes.

> ⚠️ Adicione `whatsapp_channels.json`, `mcp/whatsapp/auth/`,
> `mcp/whatsapp/node_modules/` e `data/user/.id_secret` ao `.gitignore`.

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

Para usar outro bridge ou separar os logs, dá para subir cada um à mão.

<details>
<summary>Ver como rodar o bridge por conta própria</summary>

Suba cada um num terminal:

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

Se já houver um bridge respondendo na porta, o `python ciel.py bot` (sem a
flag) usa esse e não o encerra ao sair.

Nesse modo valem as regras de [Ambientes](#ambientes-windows-wsl-e-docker) e as
[variáveis de ambiente do bridge](#variáveis-de-ambiente-do-bridge).

</details>

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

> **Aqui termina o caminho básico.** Antes de usar no dia a dia, leia
> [Segurança](#segurança). O que vem a seguir é opcional.

---

# Extras (opcional)

Nada daqui é necessário para o primeiro "oi".

## Comandos no WhatsApp

Mensagens que começam com `/` são tratadas como comandos pelo roteador
(`mcp/whatsapp/router.py`), sem passar pelo modelo:

| Comando | O que faz |
|---|---|
| `/help` | lista os comandos |
| `/task` | lista as tasks de `tasks/` |
| `/task <nome>` | executa a task (se o nome exato não existir, procura tasks parecidas; havendo mais de uma, pede para ser mais específico) |
| `/novo` | apaga o histórico **deste chat** e começa uma conversa nova |

Qualquer outro `/algo` responde "Comando ... não reconhecido".

- Em **conversa direta** todos os comandos funcionam. Em **grupos** só os
  liberados na config do grupo (padrão: `/help` e `/novo`). Veja
  [Grupos](#grupos).
- `/task` roda com o agente e as tools do chat onde foi chamado.
- O histórico é separado por chat: `/novo` num grupo não mexe na conversa
  direta, e vice-versa.
- Chats sem mensagem há 30 minutos têm o histórico apagado sozinhos
  (`SESSION_TIMEOUT_MINUTES` em `router.py`). Isso limpa só a memória da
  conversa: arquivos e dados gravados por tools não são afetados.

---

## Grupos

O Ciel pode atender um grupo do WhatsApp com um **agente próprio**. Exemplo: um
grupo de família anotando informações num arquivo (com um agente que só tem as
tools de anotação), enquanto a sua conversa direta continua com o agente
`general`.

**Por padrão nenhum grupo é atendido.** Cada grupo precisa ser liberado em
`groups.chats`, em `whatsapp_channels.json`.

### Passo a passo

1. Crie o grupo no WhatsApp e adicione o **número do Ciel** e as pessoas que
   vão usar.
2. Mande uma mensagem qualquer no grupo (ainda não liberado). O terminal do
   bot mostra:

   ```
     11:02:10  ✗ erro (ignorado)  remetente '+999999999999999' (group) fora da allowlist | chat_id=120363000000000000@g.us
   ```

   - `chat_id=...@g.us` é o **JID do grupo**.
   - `remetente` é quem escreveu, muitas vezes um LID (veja
     [O que é o LID](#o-que-é-o-lid-e-por-que-seu-número-não-bate)).
   - Peça para **cada pessoa** mandar uma mensagem, para anotar o remetente de
     todos.
3. Adicione o grupo em `whatsapp_channels.json`:

   ```json
   "groups": {
     "chats": {
       "120363000000000000@g.us": {
         "agent": "nome_do_agente",
         "require_mention": true,
         "members": {
           "+55 11 99999-9999": "Ana",
           "+999999999999999": "Bruno"
         },
         "commands": ["/help", "/novo"]
       }
     }
   }
   ```

4. Sem reiniciar nada, mande `@Ciel oi` no grupo.

### Campos

| Campo | Padrão | O que faz |
|---|---|---|
| chave (`...@g.us`) | obrigatório | JID do grupo, copiado do log |
| `members` | obrigatório | Quem pode falar com o Ciel nesse grupo, no formato `"número": "Nome"`. Aceita telefone ou LID, com a mesma comparação da `allow_from`. O nome é enviado ao agente. Grupo sem membros é ignorado. |
| `agent` | o `bot.agent` | Agente que atende esse grupo (arquivo em `agents/`) |
| `require_mention` | `true` | O Ciel só age quando a mensagem tem uma menção |
| `commands` | `["/help", "/novo"]` | Comandos liberados nesse grupo |

### Como as regras funcionam

- Uma mensagem de grupo só é processada se o grupo estiver em `chats` **e**
  quem escreveu estiver em `members`. A `allow_from` não vale no grupo, e
  estar em `members` não libera conversa direta: são listas independentes.
- Com `require_mention: true`, o Ciel só responde se a mensagem tiver uma
  menção (ou o texto contiver `@ciel`). Hoje conta **qualquer** menção: o bot
  não confere quem foi mencionado.
- O `@número` da menção é removido do texto antes de chegar ao agente, e a
  mensagem chega como `[Nome] texto`, para o agente saber quem escreveu.
  Números ou nomes digitados dentro da mensagem não são alterados.
- Cada grupo tem histórico próprio (veja
  [Comandos no WhatsApp](#comandos-no-whatsapp)).
- **O agente define o que o grupo pode fazer**: tools, tasks e comandos rodam
  com as tools dele. Para um grupo, crie um agente só com o necessário
  (seção `## Tools permitidas` do arquivo do agente) em vez de reaproveitar o
  `general`, que tem todas as tools.

### Comandos em grupo

Por padrão só `/help` e `/novo`. O `/task` fica de fora de propósito: ele
executaria tasks do projeto a pedido de qualquer membro (limitado pelas tools
do agente do grupo, mas ainda gastaria tokens e responderia no grupo). Qualquer
comando fora da lista recebe "Comando '/x' não está liberado neste grupo." e
nada é executado.

Para liberar mais comandos, ajuste a lista do grupo:

```json
"commands": ["/help", "/novo", "/task"]
```

---

## Iniciar junto com o Windows

Para o bot subir sozinho quando o PC liga, use o **Agendador de Tarefas**. Como
o Ciel já sobe o bridge, basta uma tarefa.

**Antes, pareie uma vez à mão** (`python ciel.py bot` e escaneie o QR, como no
[Passo 3](#passo-3--subir-o-modo-bot-e-parear-pelo-qr)). Sem sessão pareada o
bot fica esperando um QR que ninguém vai escanear.

Na tarefa:

1. **Gatilho:** "Ao fazer logon" (ou "Ao iniciar o computador").
2. **Ação:** "Iniciar um programa".
   - Programa: `C:\caminho\do\projeto\venv\Scripts\python.exe`
   - Argumentos: `ciel.py bot`
   - Iniciar em: a pasta do projeto (para os caminhos relativos, como
     `agents/`, `tasks/` e `data/user`, funcionarem)
3. **Configurações:** "Não iniciar uma nova instância" se a tarefa já estiver
   em execução.

Dicas:

- Prefira "Executar somente quando o usuário estiver conectado". Com "estando
  o usuário conectado ou não", o PATH pode não incluir o `node`, e o bot
  encerra com "Node.js não encontrado no PATH".
- Se já houver um bridge respondendo na porta 8765, o `ciel bot` usa esse e
  não o encerra ao sair.
- Uma segunda instância do bot sai com erro de porta 8766 em uso.

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

# Referência

Consulte quando precisar.

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

---

## Variáveis de ambiente do bridge

Só valem ao rodar o bridge à mão (`--no-bridge`). No modo padrão o Ciel usa a
`bridge_url` da config e a porta 8766 do webhook.

<details>
<summary>Ver variáveis e exemplos</summary>

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

</details>

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

<details>
<summary>Ciel no Windows e bridge no WSL (rede espelhada)</summary>

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

</details>

### Docker (planejado, ainda não disponível)

Ainda não há imagem nem `docker-compose.yml` no projeto.

<details>
<summary>O que falta para suportar</summary>

Para suportar, falta:

- Permitir configurar o endereço de escuta do bridge (hoje fixo em
  `127.0.0.1`, que dentro de um container não é alcançável de fora).
- Permitir configurar o endereço de escuta do webhook do bot.
- Persistir `mcp/whatsapp/auth/` em um volume, para não reparear a cada
  reinício.
- Instalar o Git na imagem (necessário para o `npm install`).

O desenho mais seguro seria colocar bridge e bot no mesmo `docker compose`,
em uma rede interna, sem publicar as portas `8765` e `8766` para fora. Se
você precisar publicar alguma, use `127.0.0.1:porta:porta`.

</details>

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
data/user/.id_secret
```

- `mcp/whatsapp/auth/` é a **sessão do WhatsApp do Ciel**. Quem tiver essa
  pasta controla a conta. Nunca commite nem compartilhe.
- `whatsapp_channels.json` contém seu número, seu LID e os JIDs e membros dos grupos.
- `data/user/.id_secret` é o segredo usado para mascarar IDs (veja abaixo).
  Não commite. Se apagar, o Ciel cria outro, e os apelidos de sessão mudam.

**O que o modelo recebe.** O texto da mensagem e, no grupo, o `[Nome]` do
membro. O ID real do chat (JID) não vai para o modelo: o `session_id` que entra
no prompt é um apelido (`wa_` + 12 caracteres) calculado por HMAC com o segredo
local. A allowlist e o envio da resposta usam o ID real, só dentro do seu
computador. Isso não protege o que as pessoas escrevem na mensagem: se o modelo
for de nuvem, o conteúdo da conversa vai para o provedor.

**Allowlist vazia = nenhuma mensagem processada.** O Ciel é fail-closed por
padrão: se `allow_from` estiver vazio, todas as mensagens são ignoradas (e
cada descarte aparece no log como `✗ erro (ignorado)`).

**O agente executa tools no computador de quem roda o bot.** Quem consegue
mandar mensagem por um número liberado (incluindo alguém com acesso ao seu
celular ou ao WhatsApp Web) fala com esse agente. Recomendações:

- Rode com `--safe` para desabilitar `run_script` e `create_tool`.
- Revise o `allowed_tools` do agente usado pelo bot e deixe só o necessário.
  Num grupo, quem está em `members` fala com o agente do grupo: dê a ele só as
  tools de que o grupo precisa.
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
- **Histórico em memória:** cada chat mantém as últimas 40 mensagens. Tudo é
  perdido ao reiniciar o bot e, por chat, após 30 minutos sem mensagens.
- **Comandos:** só existem `/help`, `/task` e `/novo` (veja
  [Comandos no WhatsApp](#comandos-no-whatsapp)). Outros `/algo` respondem
  "não reconhecido".
- **Menção em grupo:** com `require_mention`, qualquer menção na mensagem
  conta; o bot não confere se quem foi mencionado é o Ciel.
- **Mensagens perdidas:** se o bot estiver fora do ar, o bridge tenta 3 vezes e
  descarta. Não há fila.
- **Formatação:** o WhatsApp usa `*negrito*` (um asterisco). Respostas do
  modelo com `**negrito**` aparecem com asteriscos sobrando.
- **Custo de contexto:** cada mensagem envia o prompt do agente e o schema das
  tools (na casa de 9 mil tokens de entrada com o agente `general`). Agentes
  com menos tools ficam mais baratos e mais estáveis.

---

# Deu problema?

## Troubleshooting

Escolha o problema; os detalhes ficam recolhidos até você abrir ("Ver como resolver").

### Mensagem enviada mas Ciel não responde

Olhe o terminal do bot:

| O que aparece | Causa |
|---|---|
| `✗ erro (ignorado) ... (direct) fora da allowlist` | O `remetente` mostrado não está na `allow_from`. Copie-o (veja o [Passo 4](#passo-4--primeiro-oi-e-liberar-o-lid)). |
| `✗ erro (ignorado) ... (group) fora da allowlist` | O grupo não está em `groups.chats` ou quem escreveu não está em `members`. Copie o `chat_id` (JID do grupo) e o `remetente` (veja [Grupos](#grupos)). |
| `✗ erro (ignorado)  grupo ... exige menção` | Mencione o Ciel (`@Ciel ...`) ou use `"require_mention": false` no grupo. |
| Resposta no chat: `Comando '/x' não está liberado neste grupo.` | Inclua o comando em `commands` do grupo. |
| Resposta no chat: `[Erro de configuração: agente 'x' não encontrado]` | O `agent` do chat ou do grupo não existe em `agents/`. |
| `←` aparece mas nada do bot depois | O webhook não está recebendo (comum com `--no-bridge`): veja `ECONNREFUSED` acima. |
| Nada em nenhum dos dois | O WhatsApp não entregou: confira o número de destino e se o bridge está `✓ conectado`. |
| Só aparecem eventos do bridge sem `←` | A mensagem foi enviada pela própria conta do Ciel (`from_me`), que não é exibida nem processada. |

### Alterei algo e nada mudou

<details>
<summary>Ver como resolver</summary>

O `whatsapp_channels.json` é lido a cada mensagem, mas o código Python
(`bot.py`, `router.py`, `channels.py`...) só é carregado quando o bot sobe.
Se você trocou algum desses arquivos, dê Ctrl+C e rode `python ciel.py bot`
de novo.

</details>

### Estou conversando comigo mesmo e nada acontece

<details>
<summary>Ver como resolver</summary>

Veja [Dá para usar um número só?](#dá-para-usar-um-número-só). Mande a
mensagem de **outro** número para o número pareado com o bridge.

</details>

### O bot encerra logo ao iniciar

<details>
<summary>Ver como resolver</summary>

O Ciel imprime uma mensagem `[whatsapp] ...` e sai. Os casos mais comuns:

- **Porta do webhook em uso** (`Não consegui abrir a porta 8766`): já existe
  outro `ciel bot` rodando. Encerre-o e tente de novo.
- **Falha ao subir o bridge:** confira Node 20+ no ambiente atual e se o
  `npm install` em `mcp/whatsapp` foi concluído (veja
  [Erro no `npm install`](#erro-no-npm-install)).
- **Modo bot não habilitado:** rode `/criar canal whatsapp` ou ajuste
  `bot.enabled` em `whatsapp_channels.json`.

</details>

### Banner mostra `○ desconectado`

<details>
<summary>Ver como resolver</summary>

O bridge não está rodando (com `--no-bridge`, ou se caiu depois de subir) ou
está em outra porta. Verifique:

```bash
curl http://127.0.0.1:8765/status
# esperado: {"status":"connected"}
```

</details>

### QR não aparece na segunda execução

<details>
<summary>Ver como resolver</summary>

Normal: a sessão está salva em `auth/`. Se quiser reparear:

```bash
rm -rf mcp/whatsapp/auth/
python ciel.py bot
```

</details>

### Erro no `npm install`

<details>
<summary>Ver como resolver</summary>

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

</details>

### `fetch failed (ECONNREFUSED)` no bridge

<details>
<summary>Ver como resolver</summary>

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

</details>

### Respostas estranhas ou cortadas (`parse error` no log)

<details>
<summary>Ver como resolver</summary>

Quando o modelo responde em texto puro e o loop espera outro formato, o
Ciel pede nova tentativa, e a segunda resposta pode sair pior (ou comentar o
próprio formato). Isso dobra o consumo de tokens e é uma limitação do loop
agêntico, não do WhatsApp. Modelos maiores e agentes com menos tools reduzem
o problema.

</details>

### Resposta chega duplicada

<details>
<summary>Ver como resolver</summary>

Verifique se há duas instâncias de `node bridge.js` ou `python ciel.py bot`
rodando em paralelo.

</details>

### Bridge reconecta em loop

<details>
<summary>Ver como resolver</summary>

O Baileys tenta reconectar automaticamente com backoff exponencial (até 30s,
no máximo 10 tentativas). Se o loop não parar, verifique a conexão com a
internet e o status do WhatsApp no celular. Se aparecer
`Sessão encerrada`, a conta foi desconectada em **Aparelhos conectados**:
apague `mcp/whatsapp/auth/` e pareie de novo.

</details>
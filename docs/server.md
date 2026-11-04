# Server web

O `server.py` expõe o Ciel no navegador usando os **mesmos** agentes, tools,
sessões e base de conhecimento da CLI. Ele serve duas superfícies:

| Superfície | Endereço | Papel |
|---|---|---|
| **Site simples** | `/` | chat, sessões, tasks, fontes e ajustes — o "CLI no navegador" |
| **Interface visual** | `/ui` | apresentação de partículas: núcleo, pesquisa, artigos, painéis e voz |

![Ciel Local Server](assets/screenshot_server.png)

## Iniciar

```bash
python server.py
```

Por padrão escuta **só nesta máquina**:

```text
http://127.0.0.1:5000
```

Para abrir na rede local (celular, outro PC), use `--lan`. Não há HTTPS: use
apenas em rede confiável.

```bash
python server.py --lan
```

```text
http://192.168.x.x:5000
```

### Flags

| Flag | Ação |
|---|---|
| `--agent <nome>` | persona inicial |
| `--model <nome>` | modelo do Ollama (padrão: o salvo pela interface) |
| `--port <porta>` | porta (padrão `5000`) |
| `--host <endereço>` | endereço de escuta (padrão `127.0.0.1`) |
| `--lan` | equivale a `--host 0.0.0.0` |
| `--safe` | modo seguro permanente, ignora autenticação |
| `--debug` | modo debug do Flask |
| `--reset-password [--sim]` | gera nova senha e sai |

## Login e senha

Na primeira execução o server gera uma **senha padrão** e a mostra no terminal.
Ela fica ativa até você trocá-la em **cadeado → trocar senha**, no topo da
página. O hash fica em `~/.ciel/secrets.json`, o mesmo arquivo das chaves de
provider (fora do repositório).

O login define o que a sessão pode fazer:

| Estado | Tools disponíveis |
|---|---|
| deslogado | modo seguro: `run_script`, `create_tool` e `create_temp_tool` ficam fora |
| logado | todas as tools do agente |
| `--safe` | modo seguro permanente, mesmo logado |

Downloads (`/download`) e indexação de fonte local (`/api/source`) exigem
login. Downloads servem apenas arquivos de `data/`.

### Esqueci a senha

Gere outra sem perder as chaves de provider:

```bash
python ciel.py --reset-password         # pede confirmação ("resetar")
python ciel.py --reset-password --sim   # sem confirmação (automação)
```

Também funciona como `python server.py --reset-password`. Sem terminal
interativo o comando recusa, a menos que você passe `--sim` de propósito. A
senha nova aparece uma vez no terminal e **todas as sessões abertas no
navegador caem** (o token é assinado a partir do hash da senha).

O reset é operação de **nível de sistema**: roda no terminal, sem token e sem
passar pelo workspace guard — é o usuário do SO, dono do arquivo, quem executa.
Não apague `~/.ciel/secrets.json` para recuperar a senha: leva as chaves de
provider no mesmo arquivo. Para guardar os segredos em outro lugar, defina
`CIEL_SECRETS_PATH`.

## Comportamento

- **Um turno por vez.** O estado é de uma sessão por processo: um segundo envio
  simultâneo recebe `409` em vez de intercalar o histórico. O front avisa
  "turno em andamento" e você reenvia depois.
- **Tools interativas.** No site simples, tools como `entrevista_interativa`
  funcionam no navegador: a pergunta aparece no chat com botões (ou campo
  livre) e o turno fica pausado esperando a resposta. Depois de responder, o
  card mostra "o agente está pensando…" até a próxima pergunta ou a resposta
  final. O botão **parar** cancela o turno mesmo com uma pergunta pendente.
- **Interface visual.** O `/ui` ainda não renderiza essas perguntas: nele a
  tool segue o comportamento antigo.

## Interface visual (`/ui`)

Abra com o server rodando:

```text
http://127.0.0.1:5000/ui
```

A tela é um canvas de partículas com o chat. Em **Ajustes** ficam os controles
principais:

- **Apresentação** — `Núcleo`, `Pesquisa` e `Artigo`. O modo define o que o
  agente pode desenhar na tela: no `Núcleo` é só conversa; em `Pesquisa` ele
  abre painéis (texto, tarefas, notícias, imagens, vídeo e feed); em `Artigo` a
  resposta vira um artigo no palco.
- **Artigos** — no modo Artigo, os artigos abertos ficam numa barra lateral. Os
  que você **salvar** vão para o SQLite e reabrem entre sessões e reinícios do
  server; os demais vivem só na sessão.
- **Formas de tool / Profundidade** — liga o desenho animado associado a cada
  tool e controla a quantidade de partículas da cena (custo visual).
- **Leitura** — liga a leitura em voz alta pelo próprio navegador.
- **Falar** — grava áudio do microfone e transcreve localmente com
  `faster-whisper` (dependência opcional: `pip install faster-whisper`).

A interface visual **não tem tela de login**: ela abre sem cookie e, por isso,
roda em modo seguro. Se você entrar no site simples (`/`) primeiro, o cookie
vale também para `/ui` e libera as tools de execução.

Configuração em `ciel_config.json`:

```json
{
  "ui_anotar": { "criar_formas": false, "live": true, "live_motor": "heuristica" },
  "ui_voz":    { "modelo": "base", "idioma": "pt", "device": "auto" }
}
```

`live_motor` aceita `heuristica` (rápido, local) ou `secundario` (mais preciso,
gasta cota). `ui_voz` tem os mesmos campos do Whisper local: modelo, idioma,
device, `beam_size`, `preload` e `pasta_modelos`.

## Limitações

- Sem HTTPS e sem controle de acesso por usuário: é um server local.
- `--lan` expõe a interface para a rede; use só em rede confiável.
- O `/ui` é uma camada de apresentação; o harness e as tools são os mesmos da
  CLI e da TUI.
- `--safe` ignora a autenticação de propósito: o server inteiro fica restrito.

→ [Segurança](seguranca.md) · [TUI](tui.md) · [Comandos](comandos.md)

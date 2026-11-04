# Referência de comandos

Comandos da CLI do Ciel. Na TUI, o menu do `/` mostra a lista disponível; alguns
comandos são exclusivos da CLI (indicados na tabela). Fora dos comandos, tudo o
que você digita vai para o agente como conversa normal.

> A fonte da verdade é o `/ajuda` dentro do Ciel. Esta página organiza a lista
> por assunto e aponta a documentação de cada tópico.

## Sessão e histórico

| Comando | Ação |
|---|---|
| `/novo` | inicia uma nova sessão (pergunta se salva a atual) |
| `/limpar` | limpa o histórico de exibição |
| `/history` | lista sessões salvas — `r` retoma, `b` cria branch, `d` deleta |
| `/history <agente>` | filtra sessões por agente |
| `/history salvar` | salva e nomeia a sessão atual |
| `/history exportar` | exporta a sessão atual como `.md` |
| `/tokens` | tokens gastos na sessão |
| `/copiar` | copia a última resposta do agente |
| `/sair` | encerra (pergunta se salva) |

As sessões são salvas automaticamente no SQLite e podem ser retomadas a
qualquer momento. `/history` abre a lista com as opções `r` (retomar), `b`
(criar branch) e `d` (deletar). Um branch é uma sessão filha que herda o
histórico e as fontes da sessão pai — útil para explorar outro caminho sem
perder o contexto original. `/history exportar` gera um `.md` da sessão.

## Agente, tools e skills

| Comando | Ação |
|---|---|
| `/agente` | mostra agente e histórico atual |
| `/agente <nome>` | troca de persona (começa uma nova sessão) |
| `/tools` | lista as tools ativas na sessão |
| `/tools-extras` | tools opcionais e status de instalação |
| `/promover <tool>` | promove uma tool de `tools/temp/` para permanente |
| `/limpar-temp` | remove as tools temporárias da sessão |
| `/skill` | lista skills disponíveis |
| `/skill <nome>` | exibe o conteúdo da skill |
| `/skill <nome> <prompt>` | executa o prompt usando a skill |
| `/skill import <caminho>` | compila uma skill externa (`--executar`, `--forcar`) |
| `/skill run <nome>` | executa uma skill absorvida como board |
| `/replicar <nome>` | alias de `/skill run` |
| `/analisar <caminho>` | alias legado de `/skill import` |

→ [Agentes](agents.md) · [Skills](skills.md)

## Tasks e processos

| Comando | Ação |
|---|---|
| `/task` | lista as tasks disponíveis |
| `/task <nome>` | executa pelo nome (parcial ou exato) |
| `/task <arquivo.md>` | executa pelo caminho direto |
| `/criar task` | cria uma task por entrevista guiada |
| `/criar agente` | cria um agente por entrevista guiada |
| `/modo` | mostra o modo atual (`chat` ou `build`) |
| `/modo <chat\|build>` | alterna o modo (build exige perfil `nuvem`) |
| `/processo` | lista os processos nativos (CLI) |
| `/processo <nome> "<objetivo>"` | executa um processo específico (CLI) |
| `/processo --retomar <id>` | retoma um processo pausado (CLI) |
| `/processo --analisar [id]` | analisa uma execução; no perfil local não chama modelo (CLI) |
| `/subagente` | lista os subagentes da última execução |
| `/subagente <id\|título>` | detalha um subagente |
| `/subagente stop` | cancela o subagente em execução (TUI) |
| `/lab` | lista o estudo atual, o arquivo e os estudos salvos |
| `/lab salvar <nome>` | copia o estudo atual para o histórico |
| `/preview` | lista os previews locais |
| `/preview start <pasta> [porta]` | sobe um servidor estático |
| `/preview stop [id\|porta\|todos]` | encerra previews sem chamar o modelo |

→ [Tasks](tasks.md) · [Perfis, modos e processos](processos.md) · [Subagentes](subagentes.md) · [Motor interno](multitask.md)

## Base de conhecimento

| Comando | Ação |
|---|---|
| `/source <arquivo ou URL>` | indexa como fonte da sessão |
| `/source --global <arquivo ou URL>` | indexa como fonte compartilhada do agente |
| `/source --listar` | lista as fontes com IDs |
| `/source --remover <id>` | remove uma fonte pelo ID |
| `/source --limpar-orfas` | remove fontes de sessões deletadas |

Formatos: `.pdf`, `.txt`, `.md` e URLs. → [Fontes](sources.md)

## Modelos e perfil

| Comando | Ação |
|---|---|
| `/model` | mostra modelo local/secundário e providers; escolher um número ativa |
| `/model <nome>` | troca o modelo local (Ollama) |
| `/connect` | conecta ou atualiza um provider do modelo secundário |
| `/perfil` | mostra o perfil da sessão (local/nuvem) e o modo |
| `/perfil <local\|nuvem>` | troca o orquestrador da sessão |

→ [Modelo secundário](secondary-model.md) · [Perfis e modos](processos.md#perfil)

## Workspace e integrações

| Comando | Ação |
|---|---|
| `/workspace` | mostra o workspace ativo e os paths liberados |
| `/workspace <caminho>` | libera pasta/arquivo fora do workspace (leitura ou leitura+escrita) |
| `/mcp` | lista servidores MCP conectados e o status |
| `/mcp -v` | lista também as tools de cada servidor |
| `/criar canal whatsapp` | configura o canal WhatsApp (bot e/ou MCP) (CLI) |

→ [MCP](mcp.md) · [WhatsApp](whatsapp_tutorial.md) · [Segurança](seguranca.md)

## Imagens e entrada

| Comando | Ação |
|---|---|
| `/img <arquivo> [texto]` | envia uma imagem ao modelo (alias: `/imagem`) |

> Imagens exigem o perfil `local` por enquanto.

## Interno e legado

| Comando | Ação |
|---|---|
| `/multitask ...` | alias interno/deprecated do motor de processos (debug e testes) (CLI) |
| `/multitask --skill <nome>` | executa uma skill pelo motor (CLI) |
| `/multitask --fluxos` / `--listar` / `--retomar <id>` | inspeção e retomada do quadro (CLI) |

O `/multitask` continua existindo, mas a superfície recomendada é `/processo` e
o modo `build`. Ver [multitask.md](multitask.md).

## Flags da linha de comando

| Flag | Ação |
|---|---|
| `--cli` / `--tui` | força a interface (mutuamente exclusivas) |
| `--agent <nome>` | persona inicial |
| `--model <nome>` | modelo local do Ollama |
| `--perfil <local\|nuvem>` | orquestrador da sessão |
| `--modo <chat\|build>` | modo da sessão (build exige nuvem) |
| `--safe` | remove as tools de execução arbitrária do schema |
| `--auto` | não pede confirmação para criação de tools (só CLI) |
| `--task <arquivo.md>` | executa a task em modo headless e sai (só CLI) |
| `--list-agents` | lista as personas e sai (só CLI) |
| `--no-queue` | desativa o `task_runner` e chama o agente direto (só CLI) |
| `--reset-password` | gera nova senha do server web; `--sim` dispensa confirmação |

`python ciel.py` sem flag abre a TUI se o Textual estiver instalado; com
`--modo build` (sem `--tui`) abre a CLI. Use `--tui --modo build` para o build
na TUI.

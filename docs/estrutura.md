# Estrutura do projeto

Visão geral dos diretórios e dos módulos principais. Pastas de dados e de
estado local (`data/`, bancos `.db`, `tools/temp/`, `knowledge/cache/`) são
geradas em tempo de execução e não vão para o git.

```text
Ciel/
├── ciel.py                      # entry point: escolhe TUI, CLI ou bot
├── cli.py                       # CLI interativa
├── ciel_tui.py                  # TUI (Textual)
├── server.py                    # server web (site simples + /ui)
├── bot.py                       # modo bot WhatsApp
│
├── agent_loader.py              # lê agents/*.md e monta o system prompt
├── agent_loop.py                # loop do agente: steps, tools, contexto
├── tool_dispatch.py             # execução, confirmação e UNSAFE_TOOLS
├── tools_registry.py            # carrega tools/, tools/temp/ e ui_tools/
├── workspace.py                 # workspace guard
├── processes.py                 # catálogo de processos nativos
├── board.py                     # quadro de execução (data/runs/<id>/)
├── task_defs.py / task_runner.py # parser e runner de tasks
├── history_store.py             # sessões, branches e turnos (SQLite)
├── history_ui.py                # contexto injetado a partir do histórico
├── token_tracker.py             # contagem de tokens
├── skill_loader.py              # skills e metadados
├── article_store.py             # artigos salvos da interface visual
├── ui_bus.py / ui_routes.py     # barramento e rotas do /ui
│
├── agents/                      # personas (.md)
├── auth/                        # senha e token do server web
├── flows/                       # fluxos dos processos (.md)
├── kernels/                     # ambientes base (web_static)
├── knowledge/                   # base de conhecimento (db, ingest, retriever)
├── llm/                         # clientes, papéis e tool calls nativos
├── mcp/                         # client MCP + servidores telegram, whatsapp, google
├── multitask/                   # motor: flow, planner, runner, checks, report
├── prompts/                     # prompts internos (planejamento, web search…)
├── skills/                      # skills (.md)
├── system/                      # core_prompt, core_build, tool_template
├── tasks/                       # tasks do usuário (+ tasks/.ciel internas)
├── templates/                   # scaffolds usados pelos processos
├── tests/                       # test_core, test_integration, test_security, test_tools
├── tools/                       # tools nativas (+ tools/temp/ ignorado)
├── trust/                       # capabilities, input, segredos, model manager
├── ui_tools/                    # tools de apresentação do /ui
├── web/                         # front do site (app.js/style.css) e do /ui
├── data/                        # saídas do usuário, runs, labs, preview, cache
├── docs/                        # documentação por tópico
└── examples/                    # scripts de apoio (reset do demo de bugfix)
```

## Entry points

| Arquivo | Para quê |
|---|---|
| `ciel.py` | escolhe a interface e repassa as flags; também `--reset-password` |
| `cli.py` | modo terminal interativo e headless (`--task`) |
| `ciel_tui.py` | interface Textual |
| `server.py` | site web e `/ui` |
| `bot.py` | atendimento pelo WhatsApp |

## Configuração e estado local

| Arquivo | Conteúdo |
|---|---|
| `ciel_config.json` | modelo, perfil, `max_tokens`, papéis, `ui_*` (ignorado no git) |
| `providers.json` | providers do modelo secundário |
| `~/.ciel/secrets.json` | chaves de provider + hash da senha do server |
| `agent_history.db` | sessões, turnos e artigos salvos (SQLite) |
| `.ciel_workspace.json` | grants do workspace guard (ignorado no git) |
| `mcp_servers.json` | servidores MCP conectados (ignorado no git) |
| `whatsapp_channels.json` | canais do bot WhatsApp (ignorado no git) |
| `data/runs/<id>/` | `board.json` e `eventos.jsonl` de cada execução |
| `knowledge/cache/` | páginas web indexadas como fonte |

Template de configuração: `ciel_config.example.json`. As decisões de arquitetura
e nomenclatura ficam em [decisoes.md](decisoes.md).

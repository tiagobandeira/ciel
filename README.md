![Ciel](docs/assets/banner.jpeg)

# Ciel CLI

CLI agêntica para automação de tarefas via linguagem natural, com suporte a modelos locais (Ollama) e cloud. Janela de contexto otimizada, base de conhecimento por sessão e tools extensíveis.

Cada **persona** é um arquivo `.md` em `/agents/` — troque o comportamento do agente sem mudar código.

> **Aviso de segurança:** este projeto permite que o agente execute scripts Python e instale pacotes via pip. Use sempre dentro de um `venv` e considere a flag `--safe` se não confiar no modelo ou no input. Veja [Segurança](#segurança) antes de começar.

## Índice

- [Instalação](#instalação)
- [Configuração](#configuração)
- [Uso](#uso)
- [Comandos da CLI](#comandos-da-cli)
- [Interfaces](#interfaces) — CLI · TUI · Server Local
- [Sistema de histórico e branches](#sistema-de-histórico-e-branches)
- [Tasks](#tasks)
- [Base de conhecimento](#base-de-conhecimento-fontes)
- [Criando sua própria persona](#criando-sua-própria-persona)
- [MCP — integrações externas](#mcp--integrações-externas)
- [Modelo secundário](#modelo-secundário-opcional)
- [Skills](#skills-opcional)
- [Segurança](#segurança)
- [Arquitetura](#arquitetura)
- [Estrutura do projeto](#estrutura-do-projeto)

---

## Instalação

> Primeira vez? Siga o **[tutorial passo a passo](docs/tutorial.md)** — do zero ao primeiro chat.

```bash
# 1. Crie e ative um ambiente virtual (recomendado)
python -m venv venv

# Windows
venv\Scripts\activate.bat        # Prompt de Comando
venv\Scripts\Activate.ps1        # PowerShell

# Linux/macOS
source venv/bin/activate

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Confirme que o Ollama está rodando
ollama list
```

> O ambiente virtual isola as dependências do Ciel do seu Python global. É especialmente importante aqui porque o agente pode instalar pacotes.  
> Dependências instaladas: `requests` `rich` `pymupdf` `pyperclip` `prompt_toolkit`
>
> **TUI (opcional):** se quiser usar a interface gráfica no terminal, instale também o `textual`:
> ```bash
> pip install textual
> ```
> Ou descomente a última linha do `requirements.txt` e rode `pip install -r requirements.txt` novamente.

**O Ciel verifica o ambiente na inicialização:**

- **Ollama não acessível** ou **modelo não encontrado** → erro bloqueante com instruções para resolver
- **Modelo secundário não configurado** → aviso informativo abaixo do banner (não bloqueia o uso)
- **Tools opcionais sem dependência instalada** → aviso com contagem e link para `/tools-extras`

---

## Configuração

O Ciel funciona sem nenhuma configuração extra — o `ciel_config.json` é opcional e ativa o [modelo secundário](#modelo-secundário-opcional).

```bash
# Copie o template de configuração
cp ciel_config.example.json ciel_config.json
```

Edite `ciel_config.json` com seu provider e chave:

```json
{
  "base_url": "https://integrate.api.nvidia.com/v1",
  "model":    "deepseek-ai/deepseek-v4-flash-0731",
  "api_key":  "SUA_CHAVE_AQUI"
}
```

Funciona com qualquer API OpenAI-compatible: NVIDIA Build (gratuito), OpenRouter, OpenAI, Anthropic, entre outros.

→ **[Documentação completa: docs/secondary-model.md](docs/secondary-model.md)**

---

## Uso

![Ciel em uso](docs/assets/screenshot.png)

O ponto de entrada unificado é `ciel.py` — ele detecta automaticamente se o Textual está instalado e abre a TUI ou a CLI.

```bash
python ciel.py                             # TUI se Textual instalado, senão CLI
python ciel.py --cli                       # força modo CLI
python ciel.py --tui                       # força TUI (requer Textual)
python ciel.py --agent dev_helper          # agente específico
python ciel.py --model gemma4:e2b-it-qat   # modelo local
python ciel.py --safe                      # sem tools de execução arbitrária
python ciel.py --auto                      # pula confirmação de create_tool (confia na sessão inteira)
python ciel.py --list-agents               # lista personas disponíveis
python server.py                           # versão server local
```

> Todas as flags (`--agent`, `--model`, `--safe`, `--auto`, `--list-agents`) funcionam tanto no modo CLI quanto TUI.  
> `--task` (modo headless) é exclusivo do modo CLI — use `python ciel.py --cli --task tasks/minha_task.md`.

---

## Comandos da CLI

| Comando | Ação |
|---|---|
| `/tools` | lista tools ativas nessa sessão |
| `/agente` | mostra agente e histórico atual |
| `/agente <nome>` | troca de persona sem reiniciar |
| `/novo` | inicia nova sessão |
| `/limpar` | limpa o histórico de exibição |
| `/history` | gerencia sessões salvas (ver, retomar, branch) |
| `/history <agente>` | filtra sessões por agente |
| `/history salvar` | salva e nomeia a sessão atual |
| `/history exportar` | exporta sessão como `.md` |
| `/source <arquivo>` | indexa arquivo na base de conhecimento |
| `/source --global <arquivo>` | indexa como fonte compartilhada do agente |
| `/source --listar` | lista fontes disponíveis com IDs |
| `/source --remover <id>` | remove uma fonte pelo ID |
| `/source --limpar-orfas` | remove fontes de sessões deletadas |
| `/task` | lista todas as tasks disponíveis |
| `/task <nome>` | executa task pelo nome (parcial ou exato) |
| `/task <arquivo.md>` | executa task pelo caminho direto |
| `/skill` | lista skills disponíveis |
| `/skill <nome>` | exibe conteúdo da skill |
| `/skill <nome> <prompt>` | executa prompt usando a skill |
| `/img <arquivo> [texto]` | envia imagem ao modelo (alias: `/imagem`) |
| `/tokens` | mostra tokens gastos na sessão atual |
| `/copiar` | copia última resposta do agente |
| `/model` | exibe e configura modelos local e secundário |
| `/tools-extras` | tools opcionais disponíveis e status de instalação |
| `/mcp` | lista servidores MCP conectados e status |
| `/mcp -v` | lista com todas as tools de cada servidor |
| `/workspace` | mostra workspace ativo e paths liberados |
| `/workspace <caminho>` | libera pasta/arquivo fora do workspace (leitura ou leitura+escrita) |
| `/promover <tool>` | promove tool temporária para permanente |
| `/limpar-temp` | remove tools temporárias da sessão |
| `/analisar <caminho>` | absorve skill externa como primitivas Ciel |
| `/ajuda` | exibe todos os comandos disponíveis |
| `/sair` | encerra |

---

## Interfaces

### CLI

A interface padrão — rich rendering, autocomplete por Tab e spinner de progresso. Ativa automaticamente quando Textual não está instalado.

```bash
python ciel.py --cli
```

### 🖥️ TUI (opcional)

O **Ciel TUI** é uma interface de terminal interativa construída com [Textual](https://github.com/Textualize/textual), com três painéis em tempo real:

- **Sidebar** — agente ativo, ações rápidas (F1–F4) e histórico de sessões navegável
- **Chat** — log com Markdown, autocomplete e input com suporte a pill de texto e chips de link
- **Painel direito** — modelo ativo, contagem de tokens separada por orquestrador e modelo secundário, uso de CPU/RAM/VRAM

![Ciel TUI](docs/assets/screenshot_tui.png)

**Dependência extra:**

```bash
pip install textual
```

**Executar:**

```bash
python ciel.py                         # abre TUI automaticamente se Textual instalado
python ciel.py --tui                   # força TUI
python ciel.py --tui --agent dev_helper
python ciel.py --tui --safe
```

**Atalhos principais:**

| Tecla | Ação |
|---|---|
| `F1`–`F4` | Tool / Task / Skill / Agente |
| `Tab` | Circula pelos painéis visíveis |
| `/` | Foca o input |
| `Ctrl+K` | Abre editor do conteúdo colado (pill) |
| `Ctrl+G` | Confirma edição no pill |
| `Ctrl+D` | Deleta o pill |
| `Ctrl+S` | Salva sessão |
| `Ctrl+N` | Nova sessão |
| `Ctrl+B` | Alterna sidebar |
| `Ctrl+L` | Limpa o chat |
| `Ctrl+Y` | Abre modal de cópia — tela cheia para selecionar trechos do chat |
| `Ctrl+Q` | Sair |

→ **[Documentação completa: docs/tui.md](docs/tui.md)**

### 🌐 Server Local

O **Ciel Server** oferece uma interface web para executar o Ciel localmente através do navegador — mesmos agentes, tools, sessões e base de conhecimento da CLI, em uma interface mais acessível.

```bash
python server.py
```

O servidor pode ser acessado localmente ou por outros dispositivos na mesma rede:

```text
http://127.0.0.1:5000
http://192.168.x.x:5000
```

![Ciel Local Server](docs/assets/screenshot_server.png)

---

## Sistema de histórico e branches

As sessões são salvas automaticamente e podem ser retomadas a qualquer momento.

```bash
/history salvar          # salva e nomeia a sessão atual
/history                 # lista sessões salvas
                         # → r: retomar  b: criar branch  d: deletar
```

Branches criam uma sessão filha que herda o histórico e as fontes da sessão pai — útil para explorar um caminho diferente sem perder o contexto original.

---

## Tasks

Tasks são fluxos de execução definidos pelo usuário em arquivos `.md`. O agente executa as ações em ordem como um inspetor — sem planejar, sem improvisar.

```bash
/task                        # lista todas as tasks disponíveis
/task noticias               # executa pelo nome (parcial ou exato)
/task tasks/minha_task.md    # executa pelo caminho direto
```

Se mais de uma task corresponder ao nome buscado, o agente lista as candidatas e pede para escolher.

<p align="center">
  <img src="docs/assets/screenshot_task.png" width="600">
</p>

### Modo headless

Tasks podem ser executadas sem abrir o terminal interativo — útil para automações, cron jobs e pipelines.

```bash
python ciel.py --cli --task tasks/noticias_do_dia.md
```

O agente executa a task e encerra. Sem prompt, sem sessão interativa.

---

## Base de conhecimento (fontes)

Indexa arquivos locais para o agente consultar por relevância, sem carregar tudo no contexto. Suporta `.pdf`, `.txt` e `.md`.

```bash
/source relatorio.pdf              # disponível só nesta sessão
/source --global manual.txt        # disponível em todas as sessões do agente
/source --listar                   # vê IDs e resumos das fontes
/source --remover 3                # remove a fonte de id=3
```

O agente consulta as fontes automaticamente via `search_knowledge`, `list_sources` e `read_source`. Fontes de sessão são removidas quando a sessão é deletada. Fontes `--global` persistem até remoção explícita.

**Escopos de visibilidade:**

```
_shared       → todas as sessões do agente
session_id    → sessão atual e seus branches
```

---

## Criando sua própria persona

Crie `agents/meu_agente.md`:

```markdown
# Meu Agente

## Persona
Você é um agente especializado em X...

## Tools permitidas
calculator
read_file
search_knowledge
list_sources

## Comportamento
- Regra 1
- Regra 2
```

Rode com `python ciel.py --agent meu_agente`.

### Campos do .md

| Seção | Obrigatório | Descrição |
|---|---|---|
| `# Título` | sim | Nome do agente exibido na CLI |
| `## Persona` | sim | Personalidade e contexto do agente |
| `## Tools permitidas` | não | `todas` ou lista de nomes. Padrão: todas |
| `## Comportamento` | não | Regras adicionais de decisão |
| `## Formato de resposta` | não | Override do JSON padrão (avançado) |

---

## MCP — integrações externas

O Ciel suporta o [Model Context Protocol](https://modelcontextprotocol.io), permitindo conectar servidores externos e usar suas ferramentas diretamente no agente — sem modificar código.

```bash
# conectar um servidor (via tool do agente ou direto)
mcp_add_server(name="telegram", type="stdio",
               command="python", args="mcp/telegram/server.py",
               env="TELEGRAM_BOT_TOKEN=seu_token")

# verificar servidores conectados
/mcp -v
```

As tools do servidor aparecem automaticamente no registry com namespace `mcp_{servidor}__{tool}` e o agente passa a usá-las como qualquer outra tool. A configuração persiste em `mcp_servers.json` e é recarregada a cada sessão.

O projeto inclui um servidor MCP para **Telegram** (`mcp/telegram/`) pronto para usar. Outros servidores MCP públicos (NPM, PyPI) também funcionam sem adaptação.

→ **[Documentação completa: docs/mcp.md](docs/mcp.md)** · **[Tutorial Telegram: docs/mcp_telegram_tutorial.md](docs/mcp_telegram_tutorial.md)** · **[Tutorial Notion: docs/mcp_notion_tutorial.md](docs/mcp_notion_tutorial.md)**

---

## Modelo secundário (opcional)

O Ciel suporta um modelo secundário externo para tarefas que exigem raciocínio mais complexo ou contexto extenso — sem substituir o orquestrador local.

Quando o orquestrador (Gemma4/Ollama) identifica que o problema está além das suas capacidades, ele delega via tool `secondary_model` para um modelo externo configurado pelo usuário. O resultado volta pro orquestrador, que entrega ao usuário.

Sem configuração, o Ciel funciona normalmente — o modelo secundário é uma adição, não uma dependência.

Veja [Configuração](#configuração) para o setup. Para detalhes sobre providers, controle de cota e respostas longas:

→ **[Documentação completa: docs/secondary-model.md](docs/secondary-model.md)**

---

## Skills (opcional)

Skills são arquivos `.md` em `skills/` com instruções detalhadas injetadas diretamente no system prompt do modelo secundário — sem passar pelo orquestrador local. Permitem configurar o secundário para domínios específicos com contexto que um modelo pequeno não conseguiria carregar.

```bash
/skill                          # lista skills disponíveis
/skill frontend-visual          # exibe o conteúdo da skill
/skill frontend-visual cria um site de portfólio animado
```

Skills incluídas: `frontend-visual`, `code-review`, `refactor`, `docs-generator`, `data-analysis`.

### Skills integradas ao agente

Skills também podem ser vinculadas diretamente a um agente em seu arquivo `.md`. Quando o agente é carregado, as skills listadas são injetadas automaticamente no system prompt do modelo secundário.

> **Atenção ao contexto:** cada skill adicionada aumenta o número de tokens enviados na chamada ao modelo secundário. Considere aumentar `max_tokens` em `ciel_config.json` para evitar respostas truncadas — respeitando o limite máximo do provider.

→ **[Documentação completa: docs/skills.md](docs/skills.md)**

---

## Segurança

Este projeto tem duas superfícies de risco que você deve conhecer:

**`run_script`** — executa qualquer arquivo `.py` que o modelo solicitar na sua máquina. Use `--safe` para desabilitar:

```bash
python ciel.py --safe
```

Recomendado ao usar modelos menos confiáveis, modelos pequenos propensos a alucinações, ou ao expor a CLI a inputs externos.

**`create_tool` / `create_temp_tool`** — o agente pode criar novas tools dinamicamente e, dependendo do modelo, pode tentar instalar pacotes via pip. Por isso o uso de `venv` é essencial: qualquer instalação fica isolada do seu Python global e pode ser descartada junto com o ambiente. Tools criadas dinamicamente ficam em `tools/temp/` e não são versionadas pelo git.

Antes de executar qualquer criação de tool, a CLI exibe o código gerado com syntax highlight e pede confirmação explícita:

```
[s] sim   [n] nao   [a] auto (confia pro resto da sessão)
```

Escolher `a` (auto) dispensa confirmações para o resto da sessão. A flag `--auto` faz o mesmo ao iniciar:

```bash
python ciel.py --auto   # pula confirmação de create_tool na sessão inteira
```

Em modo headless (`--task`), criação de tools é recusada automaticamente a menos que `--auto` seja passado explicitamente.

**Workspace guard** — todas as tools que recebem caminhos de arquivo são validadas contra o diretório de onde o Ciel foi iniciado (cwd). Se o modelo tentar ler ou escrever fora desse workspace, a CLI pede confirmação explícita antes de prosseguir:

```
[s] sim, só essa vez   [a] sim, e lembrar   [n] não
```

Escolher `a` persiste o grant em `.ciel_workspace.json` (gitignored) e o path aparece no `/workspace` nas próximas sessões. Para liberar um caminho manualmente antes de iniciar uma tarefa:

```bash
/workspace ~/projetos/outro-repo   # [l] leitura  [e] leitura+escrita  [n] cancelar
```

Em sessões headless (`--task`), qualquer acesso fora do workspace é recusado automaticamente sem prompt.

**Limitações:**

- Modelos locais pequenos (< 8B) podem falhar em raciocínio complexo — considere configurar um modelo secundário.
- `--safe` remove `run_script`, `create_tool` e `create_temp_tool` do schema — o modelo nunca vê essas tools. As definições de tools bloqueadas estão centralizadas em `tool_dispatch.py`.
- A janela de contexto é otimizada por design: sessões típicas ficam em torno de 20k–30k tokens totais.

---

## Arquitetura

<p align="center">
  <img src="docs/assets/agent_cli_architecture.svg" width="700">
</p>

O modelo é intercambiável — o valor está no harness: tool registry dinâmico, sessões com branch/fork, base de conhecimento por sessão e injeção de contexto otimizada para janelas pequenas.

Tasks permitem execução predefinida de fluxos complexos — uma forma deliberada de compensar as limitações de contexto de modelos locais menores sem depender de um orquestrador grande.

---

## Estrutura do projeto

```
Ciel/
├── README.md
├── ciel.py                               ← entry point unificado (TUI/CLI)
├── cli.py                                ← CLI interativa
├── ciel_tui.py                           ← TUI (requer Textual)
├── tool_dispatch.py                      ← fonte única de UNSAFE_TOOLS e lógica de confirmação
├── workspace.py                          ← workspace guard: valida paths antes de invocar tools
├── agent_loop.py
├── server.py
├── agent_loader.py
├── tools_registry.py
├── history_store.py
├── history_ui.py
├── ciel_config.example.json              ← template de configuração
├── mcp_servers.json                      ← gerado automaticamente
├── telegram_channels.json                ← gerado automaticamente
├── agents/
│   ├── general.md
│   ├── dev_helper.md
│   ├── frontend.md
│   └── rpg_master.md
├── mcp/
│   ├── __init__.py
│   ├── client.py                         ← protocolo JSON-RPC 2.0, stdio/SSE
│   ├── adapter.py                        ← converte schemas MCP → ToolRegistry
│   ├── manager.py                        ← ciclo de vida dos servidores
│   └── telegram/
│       ├── __init__.py
│       ├── server.py                     ← servidor MCP para Telegram (Bot API)
│       └── channels.py                   ← cache local de canais
├── tools/
│   ├── calculator.py
│   ├── create_tool.py
│   ├── create_temp_tool.py
│   ├── get_hardware_info.py
│   ├── get_local_datetime.py
│   ├── get_network_info.py
│   ├── http_request.py
│   ├── list_directory.py
│   ├── list_sources.py
│   ├── mcp_add_server.py                 ← registra e conecta servidor MCP
│   ├── mcp_list_servers.py               ← lista servidores e status
│   ├── mcp_remove_server.py              ← remove e desconecta servidor
│   ├── read_file.py
│   ├── read_source.py
│   ├── read_url.py
│   ├── run_script.py
│   ├── search_knowledge.py
│   ├── secondary_model.py
│   ├── web_search_extended.py
│   └── write_file.py
├── knowledge/
│   ├── __init__.py
│   ├── db.py
│   ├── ingest.py
│   ├── ingest_url.py
│   └── retriever.py
├── skills/
│   ├── code-review.md
│   ├── data-analysis.md
│   ├── docs-generator.md
│   ├── frontend-visual.md
│   └── refactor.md
├── tasks/
│   ├── iniciar_rpg.md
│   └── noticias_do_dia.md
├── system/
│   ├── core_prompt.md
│   └── tool_template.md
├── prompts/
│   └── web_search.md
├── web/
│   ├── static/
│   │   ├── app.js
│   │   └── style.css
│   └── templates/
│       └── index.html
└── docs/
    ├── KNOWLEDGE_ROADMAP.md
    ├── TESTING.md
    ├── mcp.md
    ├── mcp_telegram_tutorial.md
    ├── mcp_notion_tutorial.md
    ├── secondary-model.md
    ├── skills.md
    ├── sources.md
    ├── tasks.md
    ├── tools.md
    ├── tui.md
    └── tutorial.md
```
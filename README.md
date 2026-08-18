# Ciel CLI

CLI agêntica para automação de tarefas via linguagem natural, com suporte a modelos locais (Ollama) e cloud. Janela de contexto otimizada, base de conhecimento por sessão e tools extensíveis.

Cada **persona** é um arquivo `.md` em `/agents/` — troque o comportamento do agente sem mudar código.

> **Aviso de segurança:** este projeto permite que o agente execute scripts Python e instale pacotes via pip. Use sempre dentro de um `venv` e considere a flag `--safe` se não confiar no modelo ou no input. Veja [Segurança](#segurança) antes de começar.

## Instalação

```bash
# 1. Crie e ative um ambiente virtual (recomendado)
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# 2. Instale as dependências
pip install requests rich pymupdf

# 3. Ollama rodando em localhost:11434
```

> Usar `venv` é especialmente importante neste projeto: o agente pode criar tools dinamicamente
> e instalar pacotes via pip. Sem isolamento, isso afeta seu Python global.

## Uso

```bash
python cli.py                             # agente padrão (general)
python cli.py --agent general             # agente geral
python cli.py --agent dev_helper          # focado em scripts Python
python cli.py --agent researcher          # leitura e síntese de arquivos
python cli.py --agent general --safe      # sem tools de execução arbitrária
python cli.py --model gemma4:cloud        # outro modelo Ollama
python cli.py --list-agents               # lista personas disponíveis
```

## Comandos da CLI

| Comando                        | Ação                                              |
|-------------------------------|---------------------------------------------------|
| `/tools`                      | lista tools ativas nessa sessão                   |
| `/agente <nome>`              | troca de persona sem reiniciar                    |
| `/novo`                       | inicia nova sessão                                |
| `/limpar`                     | limpa o histórico de exibição                     |
| `/history`                    | gerencia sessões salvas (ver, retomar, branch)    |
| `/source <arquivo>`           | indexa arquivo na base de conhecimento            |
| `/source --global <arquivo>`  | indexa como fonte compartilhada do agente         |
| `/source --listar`            | lista fontes disponíveis com IDs                  |
| `/source --remover <id>`      | remove uma fonte pelo ID                          |
| `/source --limpar-orfas`      | remove fontes de sessões deletadas                |
| `/task`                       | lista todas as tasks disponíveis                  |
| `/task <nome>`                | executa task pelo nome (parcial ou exato)         |
| `/task <arquivo.md>`          | executa task pelo caminho direto                  |
| `/ajuda`                      | exibe todos os comandos disponíveis               |
| `/sair`                       | encerra                                           |

## Sistema de histórico e branches

As sessões são salvas automaticamente e podem ser retomadas a qualquer momento.

```bash
# durante a sessão
/history salvar          # salva e nomeia a sessão atual
/history                 # lista sessões salvas
                         # → r: retomar  b: criar branch  d: deletar
```

Branches criam uma sessão filha que herda o histórico e as fontes da sessão pai —
útil para explorar um caminho diferente sem perder o contexto original.

## Tasks

Tasks são fluxos de execução definidos pelo usuário em arquivos `.md`.
O agente executa as ações em ordem como um inspetor — sem planejar, sem improvisar.

```bash
/task                        # lista todas as tasks disponíveis
/task noticias               # executa pelo nome (parcial ou exato)
/task tasks/minha_task.md    # executa pelo caminho direto
```

Se mais de uma task corresponder ao nome buscado, o agente lista as candidatas e pede para escolher.

## Base de conhecimento (fontes)

Indexa arquivos locais para o agente consultar por relevância, sem carregar tudo no contexto.
Suporta `.pdf`, `.txt` e `.md`.

```bash
/source relatorio.pdf              # disponível só nesta sessão
/source --global manual.txt        # disponível em todas as sessões do agente
/source --listar                   # vê IDs e resumos das fontes
/source --remover 3                # remove a fonte de id=3
```

O agente consulta as fontes automaticamente via `search_knowledge`, `list_sources` e `read_source`.
Fontes de sessão são removidas quando a sessão é deletada. Fontes `--global` persistem até remoção explícita.

**Escopos de visibilidade:**

```
_shared       → todas as sessões do agente
session_id    → sessão atual e seus branches
```

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

Rode com `python cli.py --agent meu_agente`.

### Campos do .md

| Seção                    | Obrigatório | Descrição                                          |
|--------------------------|-------------|----------------------------------------------------|
| `# Título`               | sim         | Nome do agente exibido na CLI                      |
| `## Persona`             | sim         | Personalidade e contexto do agente                 |
| `## Tools permitidas`    | não         | `todas` ou lista de nomes. Padrão: todas           |
| `## Comportamento`       | não         | Regras adicionais de decisão                       |
| `## Formato de resposta` | não         | Override do JSON padrão (avançado)                 |

## Segurança

Este projeto tem duas superfícies de risco que você deve conhecer:

**`run_script`** — executa qualquer arquivo `.py` que o modelo solicitar na sua máquina.
Use `--safe` para desabilitar essa tool:

```bash
python cli.py --agent general --safe
```

Recomendado ao usar modelos menos confiáveis, modelos pequenos propensos a alucinações,
ou ao expor a CLI a inputs externos.

**`create_tool`** — o agente pode criar novas tools dinamicamente e, dependendo do modelo,
pode tentar instalar pacotes via pip como parte desse processo. Por isso o uso de `venv` é
essencial: qualquer instalação fica isolada do seu Python global e pode ser descartada junto
com o ambiente.

Tools criadas dinamicamente ficam em `tools/temp/` e não são versionadas pelo git.

## Estrutura do projeto

```
PyAgentCLI/
├── README.md
├── cli.py
├── agent_loader.py
├── history_store.py
├── history_ui.py
├── tools_registry.py
├── server.py
├── agents/
│   ├── dev_helper.md
│   ├── enem_tutor.md
│   ├── general.md
│   ├── loja_manager.md
│   └── prof_assistant.md
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
│   ├── read_file.py
│   ├── read_source.py
│   ├── read_url.py
│   ├── run_script.py
│   ├── search_knowledge.py
│   ├── web_search_extended.py
│   └── write_file.py
├── knowledge/
│   ├── __init__.py
│   ├── db.py
│   ├── ingest.py
│   ├── ingest_url.py
│   └── retriever.py
├── system/
│   ├── core_prompt.md
│   └── tool_template.md
├── prompts/
│   └── web_search.md
└── docs/
    ├── KNOWLEDGE_ROADMAP.md
    ├── TESTING.md
    ├── sources.md
    ├── tasks.md
    └── tools.md
```

## Arquitetura

```
User Harness    agents/*.md         personas, tools permitidas, comportamento
Harness Built   cli.py + tools/     loop agêntico, tool registry, RAG, histórico
Model           Ollama              LLM intercambiável via --model
```

O modelo é intercambiável — o valor está no harness: tool registry dinâmico,
sessões com branch/fork, base de conhecimento por sessão e injeção de contexto otimizada
para janelas pequenas.

A janela de contexto é otimizada por design: uma sessão típica com tasks,
busca e escrita de arquivos fica em torno de 20k–30k tokens totais,
viabilizando o uso contínuo com modelos locais de janela menor.

## Limitações

- Modelos pequenos locais (< 8B) podem falhar em tasks com múltiplos steps ou raciocínio complexo.
- `run_script` executa qualquer `.py` que o modelo solicitar — use `--safe` se não confiar no input.
- `create_tool` pode tentar instalar dependências via pip — use sempre dentro de um `venv`.

---

Posicione como **automação de tarefas pessoais via linguagem natural com modelos locais**,
não como agente geral de propósito irrestrito.

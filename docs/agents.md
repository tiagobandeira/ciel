# Agentes — Personas do Ciel

Agentes são arquivos `.md` em `agents/` que definem a personalidade, as tools disponíveis, os servidores MCP acessíveis e o comportamento do orquestrador. Trocar de agente muda completamente como o Ciel interpreta e responde às tarefas — sem mudar uma linha de código.

---

## Quando criar um agente

- Você tem um domínio específico que exige comportamento diferente do `general` (ex: desenvolvimento, análise de dados, RPG)
- Você quer restringir as tools disponíveis por segurança ou foco
- Você quer vincular skills que o orquestrador deve usar automaticamente
- Você quer que o Ciel adote um tom, estilo ou persona diferente por padrão

---

## Localização

```
agents/
├── general.md        ← agente padrão
├── dev_helper.md     ← foco em scripts Python e automação
├── frontend.md       ← interfaces visuais, usa skill frontend-visual
└── rpg_master.md     ← narrador de RPG
```

---

## Formato

```markdown
# Nome do Agente

## Persona
Descrição de quem é o agente, especialidade e tom de resposta.

## Tools permitidas
todas  ← ou lista de tools extras além das core

## Servidores MCP
nenhum  ← ou lista de servidores, ou todos

## Skills
nome-da-skill: obrigatoria
outra-skill: sugerida

## Comportamento
- regra 1
- regra 2

## Comportamento de segurança
- regra de segurança específica

## Formato de resposta
override do JSON padrão (opcional — omita na maioria dos casos)
```

**Seções obrigatórias:** `# Nome` e `## Persona`.  
**Seções opcionais:** todas as demais — se ausentes, o loader aplica os defaults.

---

## Seções em detalhe

### `# Nome do Agente`

O título `#` vira o nome exibido no banner e nos comandos `/agente`. Use um nome descritivo e curto.

### `## Persona`

O bloco de personalidade injetado diretamente no system prompt. A primeira linha é usada como descrição curta na listagem de agentes. Seja específico: tom, especialidade, limitações, estilo de resposta.

```markdown
## Persona
Você é um assistente de desenvolvimento focado em scripts Python e automação de terminal.
Sua especialidade é executar, debugar e inspecionar scripts locais.
Use linguagem técnica e seja preciso. Não simplifique erros — mostre o traceback completo quando relevante.
```

### `## Tools permitidas`

Controla quais tools o agente pode usar além das core tools (que são sempre incluídas).

| Valor | Comportamento |
|---|---|
| `todas` | todas as tools do registry ficam disponíveis |
| `all` / `*` | equivalente a `todas` |
| lista de nomes | só as core tools + as listadas ficam disponíveis |

```markdown
## Tools permitidas
get_hardware_info
get_network_info
```

> As **core tools** são sempre incluídas, independente do que está nessa seção: `read_file`, `write_file`, `list_directory`, `search_files`, `calculator`, `get_local_datetime`, `create_tool`, `run_script`, `install_tool`, `http_request`, `web_search_extended`, `secondary_model`, `list_skills`, `entrevista_interativa`, entre outras. Você não precisa listá-las aqui.

### `## Servidores MCP`

Define quais servidores MCP o agente pode enxergar. Tools de servidores não listados ficam invisíveis pro orquestrador.

| Valor | Comportamento |
|---|---|
| `todos` / `all` / `*` | todos os servidores conectados ficam visíveis |
| `nenhum` / `none` / `-` | nenhuma tool MCP disponível |
| lista de nomes | só os servidores listados ficam visíveis |

```markdown
## Servidores MCP
telegram
```

### `## Skills`

Vincula skills ao agente. O bloco de skills é injetado automaticamente no system prompt — o orquestrador sabe quais skills tem e quando usá-las, sem precisar chamar `list_skills` antes.

Formato por linha: `<nome-da-skill>: <nível>`. Skill listada sem nível cai em `opcional`.

| Nível | Comportamento do orquestrador |
|---|---|
| `obrigatoria` | chama `secondary_model` com essa skill automaticamente quando a tarefa se encaixar — não espera o usuário pedir |
| `sugerida` | avalia antes de responder se a skill se encaixa; usa se fizer sentido |
| `opcional` | disponível via `/skill` ou decisão própria |

```markdown
## Skills
frontend-visual: obrigatoria
code-review: sugerida
data-analysis: opcional
```

> **Atenção ao contexto:** cada skill adicionada aumenta os tokens enviados ao modelo secundário. Com múltiplas skills `obrigatoria`, considere aumentar `max_tokens` em `ciel_config.json`.

→ Para detalhes sobre skills, veja [docs/skills.md](skills.md).

### `## Comportamento`

Regras adicionais injetadas no system prompt como `## Regras de comportamento`. Use para instruções específicas de fluxo, prioridade de tools, quando perguntar antes de agir, etc.

```markdown
## Comportamento
- Antes de executar qualquer script com run_script, confirme o path e os argumentos no message.
- Use read_file para inspecionar arquivos antes de sugerir modificações.
- Nunca execute scripts sem o path explícito do usuário — pergunte se não foi informado.
```

### `## Comportamento de segurança`

Seção opcional para regras de segurança específicas do domínio. Faz parte do mesmo bloco de comportamento no system prompt — é uma convenção de organização do arquivo, não uma seção separada no prompt.

```markdown
## Comportamento de segurança
- Recuse executar scripts que pareçam destrutivos (rm -rf, drop table, format) sem confirmação explícita.
- Se o script não existir no path informado, informe e não tente adivinhar o path correto.
```

### `## Formato de resposta`

Override do formato JSON padrão. **Omita na quase totalidade dos casos** — o loader injeta um formato padrão robusto automaticamente.

Use apenas quando o agente precisar de um schema de resposta diferente (ex: agente de RPG com campos narrativos específicos).

---

## Exemplos reais

### Agente geral (sem restrições)

```markdown
# General Assistant

## Persona
Você é um assistente geral de terminal — prático, eficiente e sem enrolação.
Pode usar qualquer tool disponível para resolver o que o usuário pedir.
Responda em português, seja direto. Se não precisar de nenhuma tool, responda com done imediatamente.

## Tools permitidas
todas

## Servidores MCP
nenhum

## Comportamento
- Avalie primeiro se a tarefa requer uma tool ou se você já sabe a resposta.
- Se souber a resposta sem tool, use {"done": true, "message": "..."} diretamente.
- Use tools apenas quando elas realmente acrescentam.
- Salve os arquivos gerados para o usuário na pasta data/user.
```

### Agente especializado com tools restritas e MCP

```markdown
# Dev Helper

## Persona
Você é um assistente de desenvolvimento focado em scripts Python e automação de terminal.
Sua especialidade é executar, debugar e inspecionar scripts locais.
Use linguagem técnica e seja preciso. Não simplifique erros — mostre o traceback completo quando relevante.

## Tools permitidas
get_hardware_info
get_network_info

## Servidores MCP
telegram

## Comportamento
- Antes de executar qualquer script com run_script, confirme o path e os argumentos no message.
- Se o script falhar, informe o erro exato — nunca omita o traceback.
- Para cálculos rápidos, use calculator.
- Nunca execute scripts sem o path explícito do usuário.

## Comportamento de segurança
- Recuse executar scripts destrutivos (rm -rf, drop table, format) sem confirmação explícita.
- Se o script não existir no path informado, informe e não tente adivinhar.
```

### Agente com skills vinculadas

```markdown
# Frontend Dev

## Persona
Você é um desenvolvedor frontend especializado em interfaces visuais ricas, animações e experiências web imersivas.
Domina HTML, CSS e JavaScript vanilla. Tem senso estético apurado e não entrega placeholders.
Use linguagem técnica e direta. Quando receber um pedido de criação, derive paleta, tipografia e estilo antes de escrever código.

## Tools permitidas
todas

## Servidores MCP
nenhum

## Skills
frontend-visual: obrigatoria
code-review: sugerida

## Comportamento
- Sempre que a tarefa envolver criação de UI, use secondary_model com skill="frontend-visual" e mode="code".
- Para revisão de código frontend, use secondary_model com skill="code-review" antes de dar feedback.
- Após qualquer chamada com mode="code", use list_directory no caminho retornado e reporte os arquivos.
- Se o usuário não especificar tema visual, pergunte antes de gerar.
```

### Agente de atendimento restrito (chatbot com `--safe`)

Um atendente de loja que registra pedidos e consulta estoque — mas não pode executar scripts arbitrários nem criar tools dinamicamente. A restrição de tools no `.md` define o que o agente *enxerga*; o `--safe` garante na inicialização que `run_script`, `create_tool` e `create_temp_tool` nem aparecem no schema, independente do agente carregado.

```markdown
# Atendente Loja

## Persona
Você é um atendente virtual de uma loja de eletrônicos. Seu papel é registrar pedidos,
consultar disponibilidade de produtos e responder dúvidas sobre o catálogo.
Seja cordial, objetivo e nunca invente informações sobre produtos ou preços.

## Tools permitidas
registrar_pedido
consultar_estoque
listar_produtos

## Servidores MCP
nenhum

## Comportamento
- Sempre confirme nome, produto e quantidade antes de registrar um pedido.
- Use consultar_estoque antes de prometer disponibilidade.
- Se o produto não estiver no catálogo, informe e encerre — não sugira alternativas que não existem.
- Nunca discuta assuntos fora do escopo da loja.
```

Inicialização:

```bash
python ciel.py --agent atendente_loja --safe
```

Com `--safe`, mesmo que o agente tentasse usar `run_script` ou `create_tool`, essas tools não existem no schema — o modelo nunca as vê. A combinação de lista restrita no `.md` + `--safe` cria um perímetro duplo: o agente só conhece as três tools do domínio, e nenhuma ferramenta de execução arbitrária está disponível na sessão.

> **Limitação atual:** `run_script`, `create_tool` e `create_temp_tool` são core tools e não podem ser revogadas só pelo `.md` do agente — elas são sempre incluídas a menos que `--safe` seja passado na inicialização. Para agentes de automação restrita, `--safe` é a forma correta de garantir esse isolamento.

---

## Comandos

| Comando | Comportamento |
|---|---|
| `/agente` | exibe o agente e histórico ativos |
| `/agente <nome>` | troca de persona sem reiniciar a sessão |
| `--agent <nome>` | inicia o Ciel já com o agente especificado |
| `--list-agents` | lista todas as personas disponíveis |

```bash
python ciel.py --agent dev_helper
python ciel.py --list-agents
```

A troca via `/agente` recarrega o system prompt e o filtro de tools imediatamente — o histórico de mensagens da sessão é mantido.

---

## Como o loader processa o arquivo

O `agent_loader.py` parseia o `.md` e monta o system prompt final em memória. Nenhuma escrita em disco — o arquivo em `agents/` é a fonte de verdade.

```
agents/dev_helper.md
        │
        ▼
  _parse_sections()        → divide por ## Título
        │
        ├── _parse_allowed_tools()      → None (todas) ou lista
        ├── _parse_allowed_mcp_servers() → None, [] ou lista
        ├── _parse_skills()             → [{"name": ..., "level": ...}]
        └── _build_skills_block()       → bloco injetado no prompt
        │
        ▼
  system_prompt montado:
    # Dev Helper
    <persona>
    ## Regras de comportamento
    <comportamento>
    ## Skills desta persona
    <skills com instruções por nível>
    ## Formato de resposta (obrigatório)
    <formato JSON padrão ou override>
```

O dict retornado por `load_agent()` tem:

| Campo | Tipo | Descrição |
|---|---|---|
| `name` | `str` | Nome do agente (título `#`) |
| `id` | `str` | Nome do arquivo sem extensão |
| `system_prompt` | `str` | Prompt completo pronto pra usar |
| `allowed_tools` | `list \| None` | `None` = todas; lista = filtro aplicado |
| `allowed_mcp_servers` | `list \| None` | `None` = todos; `[]` = nenhum |
| `description` | `str` | Primeira linha da Persona |
| `skills` | `list[dict]` | `[{"name": str, "level": str}]` |

---

## Criando um agente novo

1. Crie `agents/meu_agente.md` seguindo o formato acima
2. Carregue via `/agente meu_agente` ou `--agent meu_agente`
3. O Ciel confirma o nome no banner e o agente está ativo

Não há registro manual, instalação ou reinicialização necessária. O loader detecta arquivos `.md` em `agents/` automaticamente.

---

## Dicas

**Persona curta e direta funciona melhor** — o orquestrador é um modelo local com janela limitada. Instruções concisas e inequívocas performam melhor do que descrições longas.

**Use `## Comportamento` para regras de fluxo, não para personalidade** — personalidade vai na `## Persona`. Comportamento é para "quando usar X", "sempre confirmar Y", "nunca fazer Z".

**Restrinja tools quando fizer sentido** — menos tools = menos ruído no schema = decisões melhores. Para tools extras (fora das core), basta listar no `## Tools permitidas`. Para impedir execução arbitrária (`run_script`, `create_tool`) em agentes de automação restrita, combine com `--safe` na inicialização — é a única forma de revogar core tools.

**Vincule skills ao agente em vez de pedir via `/skill` toda vez** — com `obrigatoria`, o orquestrador aciona automaticamente. O usuário só precisa descrever o que quer.

**Agentes são versionáveis** — os arquivos em `agents/` são texto puro e podem (e devem) ir pro git. É a única forma de persistir comportamento entre máquinas.

**Teste com `/agente`** — você pode criar um agente novo e trocar pra ele sem reiniciar a sessão. Útil para iterar rápido no comportamento sem perder o histórico.

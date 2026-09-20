# Tasks

Tasks são fluxos de execução definidos pelo usuário em arquivos `.md`.
O agente executa as ações em ordem como um inspetor — sem planejar, sem improvisar.

---

## Quando usar

- Fluxos que você repete com frequência
- Sequências que precisam de consistência (mesma ordem, mesmas tools)
- Automações via cron
- Fluxos gerados por outro modelo para execução local

---

## Localização

```
tasks/
├── noticias-do-dia.md
└── minha-task.md
```

---

## Formato

```markdown
## task: nome-da-task

objetivo: descrição curta do que a task faz

grupo: tudo                    # opcional — controla agrupamento de tools

ações:
- ação em linguagem natural
- ação com tool sugerida  [tool: nome_da_tool]
- ação sem tool — agente decide qual usar

resultado esperado: o que deve ser entregue ao final
```

**Regras:**
- `## task:` e `ações:` são obrigatórios
- `[tool: nome]` é opcional por ação — use quando quiser precisão (ex: tool customizada)
- Sem `[tool:]`, o agente escolhe a tool mais adequada
- `objetivo` e `resultado esperado` são opcionais mas ajudam o agente
- `grupo` é opcional — omitir usa o comportamento padrão (uma chamada ao modelo por ação)

---

## Campo `grupo`

Controla se o agente pode agrupar chamadas de tools em fila, sem acionar o modelo entre elas.

| Valor | Comportamento |
|---|---|
| ausente | cada ação chama o modelo individualmente (padrão) |
| `tudo` | qualquer tool repetida consecutivamente é agrupada em fila |
| `calculator, web_search` | só as tools listadas são elegíveis para agrupamento |

**Quando usar:**
Use `grupo` quando a task tiver múltiplas chamadas à mesma tool. O agente executa todas
de uma vez e só aciona o modelo quando encontra uma ação que exige raciocínio.

**Quando não usar:**
Tasks com entrevistas, fluxos interativos, ou ações que dependem do resultado da anterior
para montar os parâmetros da próxima — omitir `grupo` nesses casos.

O modelo que cria a task via `/criar task` já decide automaticamente se deve incluir
o campo `grupo` com base nas ações definidas.

---

## Comandos

| Comando | Comportamento |
|---|---|
| `/task` | lista todas as tasks disponíveis |
| `/task <nome>` | executa pelo nome (parcial ou exato) |
| `/task <arquivo.md>` | executa pelo caminho direto |

Se mais de uma task corresponder ao nome buscado, o agente lista as candidatas e pede para escolher.

---

## Steps

Tasks usam `MAX_STEPS_TASK` (padrão: 9 steps) em vez dos 6 do loop normal.
Os 3 steps extras cobrem a margem de leitura de URLs, retries e etapas extras do fluxo.

Se os steps se esgotarem e faltar uma tool, o auto tool é acionado normalmente.

Quando `grupo` está definido, ações de fila não consomem steps — todas as chamadas
à mesma tool dentro de um bloco contíguo rodam dentro do mesmo step.

---

## Exemplos

### Task padrão (sem grupo)

```markdown
## task: noticias-do-dia

objetivo: buscar notícias atualizadas e organizadas por categoria

ações:
- obter data atual  [tool: get_local_datetime]
- buscar notícias segmentadas por tema (Brasil, Mundo, Tecnologia)  [tool: web_search_extended]
- ler o conteúdo das 2-3 URLs mais relevantes retornadas  [tool: read_url]
- descartar resultados sem data recente
- organizar por categorias e exibir no terminal

resultado esperado: notícias do dia com conteúdo real organizadas por categoria
```

### Task com grupo (fila de tools)

```markdown
## task: relatorio-financeiro

objetivo: calcular indicadores financeiros e gerar relatório

grupo: calculator

ações:
- calcular receita bruta: 1250 + 890 + 2100  [tool: calculator]
- calcular impostos (15% da receita bruta): (1250 + 890 + 2100) * 0.15  [tool: calculator]
- calcular lucro líquido: receita bruta menos impostos menos custos fixos (800)  [tool: calculator]
- calcular margem de lucro percentual  [tool: calculator]
- montar relatório com análise interpretativa dos números

resultado esperado: relatório estruturado com receita, impostos, lucro, margem e análise
```

Nesse exemplo, as 4 chamadas à `calculator` rodam em fila no step 1 sem acionar o modelo.
O modelo é chamado apenas para montar o relatório final com os resultados acumulados.

---

## Tools customizadas

Se uma ação usa `[tool: nome]` e a tool não existe, o agente avisa antes de iniciar
e oferece criar via auto tool. Útil para tasks que dependem de integrações específicas
(ex: `telegram_send`, `whatsapp_send`) que ainda não estão no registry.

---

## Modo headless

Tasks podem ser executadas sem abrir o terminal interativo, via flag `--task`:

```bash
python cli.py --task tasks/noticias_do_dia.md
```

O agente executa a task e encerra. Sem prompt, sem sessão interativa — ideal para automações, scripts externos e pipelines.

### Automação com cron

```bash
# todo dia às 8h — busca e envia notícias
0 8 * * * cd /caminho/do/projeto && python cli.py --task tasks/noticias-auto.md
```
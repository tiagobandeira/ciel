# Multitask (motor interno)

Motor de execução que divide um objetivo em tasks, mantém o progresso em um
quadro em disco e entrega um relatório. **Não é mais um comando de usuário**:
ele roda por baixo dos processos nativos (`/processo`) e do modo `build`.

> **Superfície atual:** `/processo` / modo build. Ver
> [processos.md](processos.md). `/multitask` continua existindo apenas como
> alias interno/deprecated para debug e testes.

## Conceitos

| Termo | Definição |
|---|---|
| Fluxo | Arquivo `.md` em `flows/` com cabeçalho + tasks. É o "plano escrito à mão". |
| Execução | Uma rodada do quadro para um objetivo, com id próprio. |
| Fase | Agrupamento de tasks; aparece no status e no relatório. |
| Task | Unidade de trabalho com objetivo, ações e resultado esperado. |
| Quadro | `data/runs/<id>/board.json` — estado completo, gravado a cada mudança. |
| Evento | Linha em `data/runs/<id>/eventos.jsonl` (`task_iniciada`, `task_concluida`…). |

## Formato do fluxo

```markdown
## flow: exemplo_site
objetivo: criar um site estático mínimo
perfil: local                 # local | nuvem (opcional)
formato: markdown             # markdown | resumo | whatsapp | bullets
como_testar: abra index.html

## task: estrutura
fase: estrutura               # default: "geral"
agente: dev_helper            # persona opcional
tools: read_file, write_file, list_directory, create_directory
objetivo: criar os arquivos base
ações:
- criar index.html
- criar style.css
resultado esperado: os arquivos existem
checagem: {"tipo": "arquivo", "path": "index.html"}
depende_de: outra-task        # por nome ou por id (t1)

## task: conferir
fase: verificação
depende_de: estrutura
ações:
- listar a pasta [tool: list_directory]
resultado esperado: a listagem contém os arquivos
```

Campos aceitos em cada task: `fase`, `agente`, `tools`, `objetivo`, `ações`,
`resultado esperado`, `depende_de`, `checagem`. O parser é o mesmo de
`tasks/*.md` (`task_defs.parse_task_text`).

`tools:` é opcional. Quando presente, só essas tools entram no schema da task
— menos tokens por step e menos distração. Sem ele, valem todas as tools do
agente. Use `read_file` com `offset`/`limit` e `edit_file` em vez de scripts
para ler/corrigir arquivos grandes.

O `formato:` do cabeçalho define a mensagem final. Se o objetivo do usuário
pedir explicitamente ("em tópicos", "um resumo", "no WhatsApp"), o formato é
ajustado automaticamente; um `formato:` explícito no fluxo vence a heurística.

## Comandos

```
/multitask                          # visão geral (fluxos + execuções)
/multitask --fluxos                 # lista flows/
/multitask --listar                 # execuções e status
/multitask <fluxo> <objetivo>       # executa um fluxo escrito à mão
/multitask <fluxo>                  # usa o objetivo do fluxo
/multitask <objetivo>               # objetivo livre: planejador monta o plano
/multitask --retomar <id>           # retoma tasks pendentes
```

Na CLI, o plano é mostrado antes de executar e pede confirmação. Para plano
livre, `[r]` refaz o plano com um ajuste seu.

Se o primeiro token corresponder a um arquivo em `flows/` (ou a um caminho
`.md` existente), ele é usado como fluxo; caso contrário, todo o texto é
tratado como objetivo livre e vai para o planejador.

### Nomenclatura

| Comando | Papel |
|---|---|
| `/task <arquivo>` | executa **uma** task `.md` (unidade isolada, sem quadro) |
| `/multitask` | planeja/executa o quadro, com checagens e correção |
| `/quadro` | **adiado** — futura visão/gestão do quadro, sem executar |

O quadro é o mesmo `data/runs/<id>/board.json` usado pelo multitask; hoje ele
é estado interno, exposto pelo relatório e por `--listar`/`--retomar`. `/tarefas`
seria alias de `/quadro` se ele for implementado; `/tasks` não. Decisão
registrada em [decisoes.md](decisoes.md).

## Como a execução funciona

1. **Plano.** Em objetivo livre, o papel `planner` (modelo secundário) recebe
   o objetivo e devolve um JSON de fases/tasks. O harness valida por código;
   inválido, devolve os erros ao modelo até `max_replans + 1` tentativas. Em
   fluxo predefinido, o `Board` vem do arquivo.
2. O plano é mostrado para aprovação (`[s] executar`, `[n] cancelar`,
   `[r] refazer com um ajuste`).
3. O runner (`multitask/runner.py`) pega a próxima task pendente cuja
   dependência já terminou.
4. Monta um contexto mínimo: objetivo geral, fase, task, ações, dependências
   e o que já foi concluído na fase.
5. Chama `run_agent` com `history=[]`, `context_injection=...` e um limite de
   steps por task.
6. Roda a checagem por código declarada na task (se houver).
7. Se a checagem falhar, monta um contexto de correção com o erro e os
   arquivos envolvidos e tenta de novo, até `max_correcoes_por_task`. Se o
   mesmo erro se repetir `max_falhas_iguais` vezes (default 2), para e marca
   a checagem como suspeita — evita queimar tokens repetindo a mesma coisa.
8. Grava status, resumo, tokens, duração, verificação e artefatos no quadro.
9. Repete até concluir, falhar, pausar (Ctrl+C) ou esgotar o orçamento.
10. Gera o relatório final (`multitask/report.py`) no formato do fluxo.

Artefatos são detectados pelos arquivos modificados/criados durante a task
(ignorando `.git`, `venv`, `__pycache__`, `data/runs`, banco de histórico etc.).

Ferramentas que importam aqui: `create_directory` cria pastas de verdade (não
use `.keep`/`run_script`), e `secondary_model` aceita `output_dir` para salvar
o projeto no caminho exato, sem a pasta com timestamp.

## Plano livre (planejador)

`/multitask <objetivo>` usa `roles.planner` — o mesmo provider salvo por
`/connect`, independente do perfil do executor ser `local` ou `build`.

- O prompt fica em [prompts/planejamento.md](../prompts/planejamento.md) e
  define schema, tamanho das tasks, tipos de checagem e regras.
- O JSON é validado **antes de executar**: ids únicos, dependências apenas
  para tasks anteriores, `resultado_esperado` obrigatório, no máximo 6 ações
  por task, agente existente, checagem estruturalmente válida e limite de
  tasks do orçamento. Task de criar pasta com `checagem` tipo `arquivo` é
  rejeitada: pasta usa `diretorio`.
- Plano inválido volta ao modelo com a lista de erros; ele tem
  `orcamento.max_replans + 1` tentativas.
- Na aprovação, `[r]` chama o planejador de novo com o ajuste que você
  escrever (até `max_replans` vezes).
- Tokens do planejamento entram na sessão e no relatório final.

## Checagens e correção

A checagem é **código**, roda depois do `done` do modelo e não depende de o
modelo avaliar o próprio trabalho. Tipos:

```yaml
checagem: {"tipo": "arquivo", "path": "index.html", "contem": "<html"}
checagem: {"tipo": "diretorio", "path": "data/user/meu-projeto",
           "contem_arquivos": ["index.html"]}
checagem: {"tipo": "comando", "cmd": ["python", "-m", "pytest", "-q"],
           "cwd": ".", "esperado": 0, "timeout": 60}
checagem: {"tipo": "http", "url": "http://127.0.0.1:8000/", "esperado": 200}
checagem: {"tipo": "json", "path": "dados.json", "chaves": ["itens"]}
checagem: [ {"tipo": "arquivo", "path": "a.txt"},
            {"tipo": "arquivo", "path": "b.txt"} ]   # todas precisam passar
```

| Tipo | Campos principais |
|---|---|
| `arquivo` | `path`, `existe` (default true), `contem`, `nao_contem`, `tamanho_min` |
| `diretorio` | `path`, `existe` (default true), `contem_arquivos` |
| `comando` | `cmd` (lista ou string), `cwd`, `esperado` (default 0), `timeout` |
| `http` | `url`, `esperado` (default 200), `metodo`, `corpo_contem`, `timeout` |
| `json` | `path`, `chaves` obrigatórias |

Uma string (`checagem: manual`) é apenas um critério textual: não conta como
verificação automática.

**Correção:** se a checagem falhar, o runner não chama o modelo de novo às
cegas. Ele monta um contexto com o erro, `stdout`/`stderr` e o conteúdo dos
arquivos envolvidos e repete a mesma task. Limite em
`orcamento.max_correcoes_por_task` (default 3). Esgotou, a task falha e a
execução para — o relatório mostra o erro e as pendências.

**Segurança:** paths e `cwd` são resolvidos dentro do workspace. Fluxos fora
de `flows/` pedem confirmação na CLI e avisam quando há checagens de comando.

## Revisão por fase

No perfil `nuvem`, ao concluir uma fase o runner chama o revisor com o
secundário. Ele recebe o quadro da fase, os resumos e as tasks pendentes e
pode apenas ajustar o que ainda não executou:

- adicionar task;
- atualizar objetivo/ações/check/tools de task pendente;
- pular task pendente;
- reordenar tasks pendentes.

O revisor nunca altera task concluída/falha/em andamento. A revisão é opt-in
no runner (`revisar_fases=True`) e o `/processo` a liga automaticamente no
perfil `nuvem`. Eventos: `fase_revisada` e `fase_revisao_falhou`.

## Preview e entrega

O `app_web` termina com uma task `publicar`:

- `start_preview` sobe `data/user/app_web` em `http://127.0.0.1:8765/`;
- a task escreve `COMO_RODAR.md` com a URL e o comando manual;
- o check faz um `GET` na URL e confere o arquivo;
- o preview continua ativo depois do run; use `stop_preview` para encerrar.

O servidor é estático (`python -m http.server`), escuta só em `127.0.0.1` e
não executa código do projeto. `list_previews` mostra o que está ativo.

Na CLI, `/preview` lista, `/preview start <pasta> [porta]` inicia e
`/preview stop [id|porta|todos]` encerra — **sem chamar o modelo**.

## Perfis de modelo

O fluxo pode declarar `perfil: nuvem` para usar o provider configurado como
executor (o mesmo salvo por `/connect`). Sem provider configurado, cai no
Ollama local. O perfil `local` usa o modelo de `--model`.

Na CLI, `--perfil nuvem` (ou `/perfil nuvem`) muda o orquestrador da sessão
para o provider de API; nesse caso o chat normal já roda no modelo maior, sem
a tool `secondary_model`. O perfil da sessão e o `perfil:` do fluxo usam a
mesma resolução de papéis. O modo `build` é outra camada: ele escolhe o
processo e usa este motor por baixo.

## Custo e orçamento

O runner mede custo por task em `board.meta["metricas"][task.id]`:

```json
{"steps": 6, "tokens_in": 24000, "tokens_out": 2000,
 "parse_errors": 0, "compactions": 1,
 "context_peak_chars": 18000, "tool_calls": 5, "batch_calls": 1}
```

- `orcamento.max_tokens_por_task` (default 100.000) limita uma task; ao
  estourar, o loop devolve `limit` e a checagem decide se aceita.
- `orcamento.max_tokens` continua sendo o limite do run (0 = sem limite).
- O planner declara `tools` e `max_steps` por task; quando não declara, o
  harness usa presets de leitura/escrita/código.
- Use essas métricas para descobrir se o custo está em steps, contexto,
  parse error ou correção — antes de aumentar qualquer orçamento.

Exemplo real do `corrigir_bug` (3 tasks, 54k tokens):

| Task | steps | tokens_in | tokens_out | parse | compact | batch |
|---|---:|---:|---:|---:|---:|---:|
| diagnosticar | 4 | 16.706 | 732 | 0 | 0 | 1 |
| corrigir | 3 | 13.054 | 437 | 0 | 0 | 0 |
| verificar | 5 | 21.943 | 1.131 | 0 | 0 | 0 |

## Limites desta fase

- O planejador exige um provider secundário configurado (`/connect`). Sem
  ele, use um fluxo escrito à mão.
- A correção é a mesma task com contexto de erro; ela não cria uma task nova
  no quadro (o contador `correcoes` e os eventos registram as tentativas).
- Replanejamento automático quando uma task falha ainda não existe: a
  execução para e o relatório mostra o erro.
- Sem paralelismo e sem TUI dedicada: use `python ciel.py --cli`.
- `--retomar` só tenta tasks pendentes; uma task que falhou não é repetida
  automaticamente.

## Exemplo

```bash
python ciel.py --cli
> /multitask --fluxos
> /multitask exemplo_site
```

O relatório final lista o que foi feito por fase, arquivos, decisões, falhas,
pendências e como testar.

## O que vem depois

1. Entrevista e fluxo `web_projeto` completo (o preview/entrega já entrou).
2. Painel na TUI e `analisar` sobre o quadro.
3. Subagentes paralelos e mais fluxos (dados/acadêmicos).

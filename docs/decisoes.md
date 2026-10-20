# Registro de decisões — Ciel

Decisões de arquitetura e nomenclatura tomadas durante a implementação dos
modos local/build e do multitask. Cada entrada registra a decisão e o porquê,
para não rediscutir o mesmo ponto depois.

Data de referência: 2026-10-19.

> **Nota de terminologia:** as decisões D-001 a D-008 usam “build” para o
> perfil de modelo. A D-010 renomeia esse perfil para **nuvem** e reserva
> **build** para o modo de construção. Onde ler “perfil build” nas decisões
> antigas, entenda “perfil nuvem”.

---

## D-001 — Perfil e modo são eixos diferentes

**Decisão:** separar `perfil` (quem é o modelo) de `modo` (o que o harness faz).

| Eixo | Pergunta | Valores |
|---|---|---|
| Perfil | Quem é o modelo? | `local`, `build` |
| Modo | O que o harness faz? | `chat`, `task`, `multitask` |

**Por quê:** `build` não é um orquestrador diferente; é um preset de
roteamento que aponta o orquestrador e o worker para o provider salvo pelo
`/connect`. Multitask é uma forma de execução que pode rodar em qualquer
perfil. Fundir os dois faria a CLI crescer em flags ambíguas.

**Consequência:** `--perfil` / `/perfil` mudam o modelo; `/multitask` muda a
forma de executar. Um não substitui o outro.

---

## D-002 — Build não ativa multitask automaticamente

**Decisão:** no perfil build, o chat continua sendo chat. O multitask só roda
quando o usuário pede (`/multitask`) ou quando o modelo chamar uma tool de
execução de plano.

**Por quê:** ativar multitask em toda mensagem transforma “bom dia” em plano
de três tasks, aumenta custo/latência e dificulta distinguir conversa de
execução. O padrão dos agentes atuais é um quadro de tarefas vivo, não um
pipeline automático.

**Próximo passo:** `/quadro` + tools `tarefa_criar` / `tarefa_atualizar` /
`tarefa_listar` para o build gerenciar o quadro; a execução em lote continua
explícita.

---

## D-003 — `/quadro` fica adiado; `/task` e `/multitask` não mudam

**Decisão:** não implementar `/quadro` (CRUD manual do quadro) agora. O quadro
continua sendo **estado interno** do motor multitask. Se um dia for exposto
como comando, o nome canônico será `/quadro`, `/tarefas` poderá ser alias e
`/tasks` continua rejeitado.

**Por quê:** `/task` é uma unidade isolada, `/multitask` é o motor que executa
um plano. Um `/quadro` com CRUD é útil só se o usuário criar/editar tarefas
fora do plano com frequência — caso contrário, vira superfície e engenharia
sem demanda. Antes de decidir, vamos testar o multitask em projetos reais
(notebook, jogo, artigo, landing page).

**Semântica atual (sem `/quadro`):**

| Comando | O que faz |
|---|---|
| `/task <arquivo>` | executa **uma** task `.md` (unidade isolada) |
| `/multitask <fluxo\|objetivo>` | planeja/executa o quadro, com checagens e correção |
| `/multitask --listar` | lista execuções e status |
| `/multitask --retomar <id>` | retoma uma execução pausada |

**Status:** adiado. Reavaliar depois dos testes práticos descritos em
[testes-multitask.md](testes-multitask.md).

---

## D-004 — Um quadro só, compartilhado por build e multitask

**Decisão:** existe **um** quadro por execução/sessão, persistido em
`data/runs/<id>/board.json`. Build e multitask leem e escrevem o mesmo quadro.

**Por quê:** dois estados separados (“todo da sessão” e “quadro do multitask”)
fazem o usuário perguntar por que uma tarefa criada no chat não aparece no
`/multitask --listar`. Um quadro, várias views.

**Consequência:** se `/quadro` for implementado no futuro, ele lê/escreve o
mesmo arquivo; hoje o quadro é interno ao runner e visível pelo relatório do
`/multitask`. As tasks criadas no build podem ser executadas depois pelo
multitask sem migração.

---

## D-005 — Build usa o modelo principal, não a tool `secondary_model`

**Decisão:** no perfil build, o modelo do provider secundário é o
orquestrador. A tool `secondary_model` é removida do schema e o core prompt
vira `system/core_build.md`.

**Por quê:** chamar o `secondary_model` no build seria o modelo chamando a si
mesmo, com contexto duplicado. O prompt local (`core_prompt.md`) ensina um
orquestrador pequeno a delegar; no build isso está errado.

**Consequência:** skills `obrigatoria` da persona entram no prompt do build;
`/skill` injeta o conteúdo no orquestrador; as demais skills podem ser
carregadas sob demanda.

---

## D-006 — Ferramentas básicas são core

**Decisão:** `create_directory` é uma core tool, assim como `read_file`,
`write_file` e `list_directory`.

**Por quê:** sem ela o modelo tenta `run_script` com script inexistente ou
`write_file` com `.keep` só para criar pasta. Isso não é orquestração, é
capacidade faltando. `create_directory` resolve o caso básico e o planner é
instruído a usá-la.

**Relacionado:** checagem de pasta usa `{"tipo": "diretorio", ...}`, não
`arquivo`; e `secondary_model` aceita `output_dir` para salvar no caminho
exato, sem a pasta com timestamp.

---

## D-007 — Limites atuais e próximos passos

**Estado:** fases 0–3 do multitask e a fase 3.5 (perfis/build) estão
implementadas. O núcleo do multitask funciona: fluxo, plano livre, quadro,
checagens, correção e retomada.

**Ainda não implementado / adiado:**

- **adiado:** `/quadro` e tools de gestão manual de tarefas;
- **próximo:** status do run atual no `/multitask` e `--retomar` capaz de
  refazer tasks falhas (com confirmação);
- auto-execução de plano no build (por tool, não por mensagem);
- perfil build no `--task` headless, server e bots;
- imagens no build;
- Fase 4 (fluxo `web_projeto` + entrevista) e Fase 5 (TUI, revisão por fase,
  replanejamento automático).

**Ordem recomendada:** testar o multitask nos casos reais de
[testes-multitask.md](testes-multitask.md); corrigir o que falhar; depois
status/retomada com refazer falhas; só então reavaliar `/quadro`. Fase 4/5
depois disso.

---

## D-008 — Limites de execução do build

**Decisão:** o `max_tokens` do `ciel_config.json` vale também para o cliente
do build (antes só o `secondary_model` usava). No build, o orçamento padrão é
12 steps por task; se os steps esgotarem e a checagem por código passar, a
task é aceita (o trabalho estava pronto, só não houve `done`).

**Por quê:** o log da primeira execução real mostrou três coisas: JSON de
`write_file` grande quebrando, 9 steps insuficientes para uma redação longa e
uma task de artigo grande demais. O `↑tokens` do relatório é a soma das
chamadas, não o contexto de uma única chamada; o problema era granularidade +
limite de steps, não necessariamente janela de contexto.

**Consequência:** escritas longas devem ser divididas em tasks menores (o
fluxo `artigo_matematica` virou 5 tasks). Tasks podem declarar `tools:` para
reduzir o schema (de ~20k para ~1,3k caracteres nos fluxos de texto). O
`read_file` ganhou `offset`/`limit` e existe `edit_file` para correções pontuais,
evitando scripts de leitura/edição. Respostas DSML do DeepSeek são convertidas
para tool call como fallback; o parser também aceita prosa/múltiplos JSONs e
pega o primeiro objeto completo. No multitask, steps esgotados não pedem
proposta de tool: a checagem da task decide (evita o status `needs_tool` sem
handler). Ainda não há compactação automática de histórico; se uma task
legítima passar de ~12 steps, o próximo passo é implementar compactação ou um
`max_steps` por task.

---

## D-009 — Custo de tarefa longa: uma escrita por arquivo

**Experimento:** o mesmo artigo (5 tasks, tema “introdução à teoria dos
grupos”) foi executado em uma cópia isolada do fluxo (`artigo_bench`, paths
`data/user/artigos_bench`) para medir custo sem tocar no artigo do usuário.

| Versão | Chamadas | Tokens | Resultado |
|---|---:|---:|---|
| Loop por ação, chunks de 2k | ~34 | ~320k | 5/5 |
| Lote + chunks de 2k | ~45 | ~499k | 5/5 (pior) |
| Uma escrita por arquivo + compactação | 19 | **146,4k** | 5/5, 1m36 |

**Decisão:** a maior alavanca não foi batch, foi **não fatiar cada arquivo em
chunks de 2.000**. O modelo deve escrever cada seção/arquivo em uma chamada
quando couber em ~8.000 caracteres. Batch de leituras continua disponível
(`actions`, até 4), mas o modelo não é obrigado a usar. A compactação de
histórico (30k caracteres, últimas 6 mensagens) fica como rede de segurança.

**Consequência:** para artigo/site, o custo fica na casa de 150k, não 300k+.
O próximo passo só se precisar: `write_files` (manifesto) para criar vários
arquivos em uma chamada, ou compactação mais agressiva. Não aumentar steps.

---

---

## D-010 — Perfil `nuvem`, modo `build`, processos nativos

**Decisão:** separar definitivamente as três camadas:

| Camada | Valores | Papel |
|---|---|---|
| Perfil | `local`, `nuvem` | quem executa (Ollama ou API) |
| Modo | `chat`, `build` | como executa |
| Processo | `app_web`, `landing_page`… | o que está sendo construído |

`build` deixa de ser perfil e passa a ser o **modo de construção**. O perfil
antigo `build` vira `nuvem` (aliases `build`/`cloud` continuam aceitos).
`multitask` deixa de ser comando de usuário e vira motor interno dos processos.

**Por quê:** o usuário precisa lembrar se está no Ollama ou numa API externa
(perfil), mas “build” deve significar construção — escolher um processo,
gerar spec, executar e verificar. O nome anterior misturava as duas coisas.

**Consequência:** `/processo` e o modo build por linguagem natural passam a
ser a superfície; o `/multitask` some da ajuda. O modo build exige perfil
nuvem. A saída final de um processo é um resumo curto; o detalhe fica em
`data/runs/<id>/`.

---

---

## D-011 — O caso econômico é verificação, não geração

**Experimento:** `corrigir_bug` em um demo com `media([])` quebrada.

| Caso | Tokens | Resultado |
|---|---:|---|
| App greenfield (`app_web`) | ~1,5M | funciona, mas inviável |
| Bugfix (`corrigir_bug`) | **~50k** | 3/3, correção mínima validada |

**Decisão:** processos de verificação/correção (bugfix, testes, auditoria,
migração) são o caso de uso econômico do motor. Greenfield continua possível,
mas exige scaffold/manifesto e orçamento — não é o caso que valida o modo.

**Consequência:** o próximo processo nativo deve ser de verificação
(`corrigir_bug` já entrou; depois `gerar_testes`/`auditar_repo`), não outro
gerador de app.

---

## Onde isso aparece no código

| Área | Arquivo |
|---|---|
| Perfis e papéis | `llm/roles.py`, `llm/client.py` |
| Perfil da CLI | `cli.py` (`_SESSION`, `/perfil`, `--perfil`) |
| Perfil da TUI | `ciel_tui.py` (`_configure_perfil`, `/perfil`) |
| Prompt do build | `system/core_build.md`, `agent_loop._build_system_prompt` |
| Multitask | `multitask/flow.py`, `planner.py`, `runner.py`, `checks.py`, `report.py` |
| Quadro | `board.py` (`data/runs/<id>/board.json`) |

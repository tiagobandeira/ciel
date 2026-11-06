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

---

## D-012 — Patch antes de tool calling nativo

**Decisão:** a próxima alavanca de custo é edição parcial, não tool calling
nativo. `apply_patch` aplica vários hunks `{old,new}` atomicamente; `read_file`
ganhou `start_line`/`end_line` e `numbered`. Tool calling nativo fica para
depois, atrás de capability flag, porque não reduz geração por si só.

**Por quê:** o custo dominante em app/landing é gerar e reenviar conteúdo de
arquivo; patch reduz output e leitura, enquanto tool nativo ataca protocolo e
round-trips. O adaptador DSML já cobre o caso atual.

**Consequência:** medir `tokens_out`/`tool_calls` depois de patch; só então
avaliar nativo/parallel calls e scaffold.

---

---

## D-013 — Tarefas idempotentes e scaffold determinístico

**Decisão:** tasks podem declarar `pular_se_ok: true`; antes de executar, o
runner roda a checagem e, se ela já passar, marca a task como concluída com
`pulada=True` e custo zero.

**Decisão:** `copy_template` + `templates/` (app_web, landing, game) criam o
boilerplate deterministicamente; o modelo edita as features em vez de gerar
estrutura.

**Por quê:** reruns de landing/app não devem pagar de novo pelo que já está
pronto, e boilerplate não é o lugar onde o modelo agrega valor.

**Consequência:** `pular_se_ok` é opt-in (checks específicos); templates são
versionados. Medir `tokens_in`/`steps` depois disso antes de avaliar tool
nativo.

---

---

## D-014 — Resposta final de processo

**Decisão:** ao concluir um processo, a resposta amigável deve mostrar:

- o que foi feito, em linguagem direta;
- a estrutura do projeto (arquivos/pastas principais);
- onde ele está (`data/user/...`);
- como testar/abrir;
- informações úteis já existentes no processo (checks, arquivos, decisões).

Nada de despejar todo o relatório técnico. O detalhe completo continua em
`data/runs/<id>/relatorio.md`; a resposta é o resumo acionável.

**Por quê:** o usuário quer saber “o que tenho em mãos e onde”, não ler o log.

---

---

## D-015 — Tool calls nativos atrás de flag

**Decisão:** clientes OpenAI-compatible podem enviar `tools` nativos e ler
`message.tool_calls` quando `native_tools: true` está no config. Por enquanto,
o caminho nativo executa **apenas leituras independentes em lote**; escrita
continua no JSON, com fallback automático.

**Por quê:** reduz protocolo/round-trips sem apostar a qualidade de escrita em
um suporte de provider que varia. JSON/DSML continua sendo o caminho padrão.

**Consequência:** medir `tool_calls`/`batch_calls`/steps antes de expandir
nativo para escrita.

---

---

## D-016 — Revisão por fase no nuvem

**Decisão:** ao fim de cada fase no perfil `nuvem`, o secundário revisa o
quadro e pode adicionar/atualizar/pular/reordenar **tasks pendentes**. Tasks
concluídas, falhas ou em andamento nunca são alteradas.

**Por quê:** o check por task valida o artefato, mas não a coerência da fase;
um revisor read-only com o quadro inteiro pega dependência faltando e escopo
errado antes de gastar nas próximas tasks.

**Consequência:** revisão é opt-in no runner e ligada no `/processo` nuvem;
eventos `fase_revisada` e `fase_revisao_falhou`; o custo do revisor entra no
run.

---

---

## D-017 — Preview estático e entrega do app

**Decisão:** `app_web` ganhou uma fase de entrega com `start_preview`: um
servidor estático em `127.0.0.1:8765`, mais `COMO_RODAR.md` e um check HTTP.
O preview continua ativo após o run e pode ser encerrado com `stop_preview`.

**Por quê:** o usuário precisa abrir o app no navegador, não só receber
arquivos. O servidor é determinístico, local e não executa código do projeto;
a entrega é um artefato verificável.

**Consequência:** porta fixa por app (8765) para o check HTTP; se estiver em
uso, o `start_preview` falha de forma explícita. `list_previews` mostra os
ativos.

---

---

## D-018 — Entrevista como processo separado

**Decisão:** `web_projeto` é um processo próprio, com uma task `briefing`
usando `entrevista_interativa` antes da spec. `app_web` continua o caminho
direto, sem interação, para benchmarks e pedidos já claros.

**Por quê:** entrevista é interativa e não pode quebrar o fluxo automático.
Separar os processos mantém os dois previsíveis.

**Consequência:** `web_projeto` tem 7 tasks e grava `BRIEFING.md`; `app_web`
tem 6 e vai direto para `SPEC.md`.

---

---

## D-019 — Analisar o quadro, não o log

**Decisão:** `/processo --analisar [id]` lê o quadro (tasks, checks, resumos e
métricas) e produz uma análise curta. No `local` é determinístico e não chama
modelo; no `nuvem` usa o secundário e informa os tokens.

**Por quê:** o usuário precisa de “o que funcionou, o que falhou e o próximo
passo”, não de outro despejo do relatório. E análise local não deve gastar
API.

**Consequência:** a análise é read-only; não altera o quadro nem retoma a
execução.

---

---

## D-020 — Fluxo de análise de dados

**Decisão:** `analise_dados` é um fluxo de quatro fases — inspecionar, limpar,
analisar e verificar — com scripts Python reproduzíveis e um check de comando
no final.

**Por quê:** análise de dados precisa de números reproduzíveis; um relatório
gerado direto pelo modelo não é confiável. O fluxo separa perfil/limpeza/análise
e obriga `verificar.py` a passar.

**Consequência:** o objetivo precisa apontar o dataset; os artefatos ficam em
`data/user/analise_dados/`.

---

---

## D-021 — Build na TUI usa o mesmo runner

**Decisão:** a TUI ganhou `/modo build`; a linguagem natural detecta o
processo, monta o `Board` do fluxo e chama o mesmo `run_board` da CLI em uma
worker thread. Eventos, checks, correção, revisão e preview são os mesmos.

**Por quê:** duplicar o motor na TUI criaria dois comportamentos. A TUI é uma
camada de apresentação; o harness continua sendo a fonte de verdade.

**Consequência:** `--tui --modo build` sobe com perfil `nuvem`; o painel é
atualizado via eventos sem bloquear a interface.

---

---

## D-022 — Auditoria read-only como processo

**Decisão:** `auditar_repo` é um fluxo de três fases (inventário, riscos,
relatório) que escreve apenas em `data/user/auditoria/`; o código auditado não
é alterado.

**Por quê:** auditoria precisa ser barata e segura. O valor está em achar
evidência e priorizar, não em aplicar patch na hora; correção é outro processo.

**Consequência:** os checks são de artefato de relatório; o alvo pode ser o
workspace ou um caminho citado no objetivo.

---

---

## D-023 — Gerar testes sem alterar o fonte

**Decisão:** `gerar_testes` escreve testes e runner em `data/user/gerar_testes/`,
executa contra o alvo via `sys.path` e registra bugs reais em `RESULTADO.md`
sem editar o código-fonte.

**Por quê:** gerar e corrigir ao mesmo tempo mistura responsabilidades e pode
mascarar o bug. Teste é o contrato; correção é o próximo processo.

**Consequência:** o check do processo é `python rodar.py`; o usuário pode
copiar os testes gerados para o repositório depois.

---

---

## D-024 — Corrigir bug parametrizado por ALVO

**Decisão:** `corrigir_bug` deixou de ser amarrado ao `bugfix_demo`. A primeira
task grava `data/user/corrigir_bug/ALVO.json` com projeto, comando, cwd e
arquivo; o runner `verificar.py` executa esse comando. Sem objetivo explícito,
o alvo padrão continua sendo o demo.

**Por quê:** correção verificável é o nicho mais forte do Ciel; um fluxo que
só funciona no demo não serve para uso real. O ALVO mantém os checks
determinísticos mesmo com caminhos variáveis.

**Consequência:** saídas em `data/user/corrigir_bug/`; o template do runner é
copiado do repositório, não gerado pelo modelo.

---

---

## D-025 — `/replicar` liga skill absorvida ao board

**Decisão:** `/replicar <skill>` lê `skills/<nome>_meta.json`, carrega as tasks
geradas por `/analisar` e monta um `Board` do multitask, com dependências
sequenciais para skills do tipo `pipeline`.

**Por quê:** o `/analisar` já produzia as primitivas, mas elas ficavam soltas
em `tasks/`; o roadmap pede que o plano venha da skill e use o mesmo quadro,
checks e limites.

**Consequência:** skills `plugin`/`context` continuam usando tools/instruções
diretamente; só `pipeline` vira board.

---

---

## D-026 — `/skill` como interface única

**Decisão:** a família de skills passa a ser:

- `/skill import <path> [--executar] [--forcar]` — compila;
- `/skill run <nome>` — executa o board;
- `/multitask --skill <nome>` — executa pelo multitask;
- `/replicar <nome>` — alias de `/skill run`;
- `/analisar <path>` — alias legado de import.

**Por quê:** `analisar` + `replicar` eram nomes desconexos para compilar e
executar. O `/multitask` é o executor; a skill é só mais uma fonte de plano.

**Consequência:** `--executar` faz o fluxo completo; sem ele, compila uma vez
e reutiliza. Skills `plugin`/`context` não viram board.

---

---

## D-027 — Kernel como ambiente base

**Decisão:** ambientes reutilizáveis ficam em `kernels/<nome>/kernel.yaml` com
variantes, template, variáveis e smoke de arquivos. `prepare_kernel` aplica o
kernel e grava `.ciel/kernel.json` no projeto.

**Por quê:** `copy_template` resolvia arquivos, mas não expressava ambiente,
variante, versão nem smoke. O kernel separa “terreno” de “feature”, que é a
base para scaffold e, depois, para subagentes paralelos.

**Consequência:** `web_static` cobre app/landing/jogo; os fluxos usam
`prepare_kernel` na estrutura. `copy_template` continua como tool de baixo
nível.

---

---

## D-028 — Paralelismo só para leitura

**Decisão:** tasks com `parallel: true` podem rodar juntas somente se todas as
tools declaradas forem de leitura. Cada uma usa um board isolado; o resultado
é mesclado no quadro principal.

**Por quê:** o runner atual compartilha board, workspace e callbacks; rodar
escrita concorrente sem isolamento corromperia estado. Leitura paralela já
reduz latência em pesquisa/inspeção sem esse risco.

**Consequência:** `max_parallel` padrão 2; revisão de fase após lote paralelo
fica pendente; escrita paralela exige locks/arquivos disjuntos em uma próxima
fase.

---

---

## D-029 — Subagente como unidade de sistema

**Decisão:** cada task é tratada como subagente: persona, modelo, tools,
limite, contexto e resultado próprios. O resultado é persistido em
`data/runs/<id>/subagents/<task_id>.json`.

**Por quê:** “task” era só uma linha do quadro; faltava o contrato de execução
isolada e observável. Subagente precisa de identidade, permissões e resultado,
não de acesso ao log bruto.

**Consequência:** `subagente` é alias de `agente`; `modelo`, `read_only` e
`parallel` são campos de task. Paralelo continua read-only; escrita exige
arquivos disjuntos/locks.

---

---

## D-030 — Perfil por subagente

**Decisão:** cada task pode declarar `perfil: local|nuvem`. O runner resolve
papéis e cliente para aquela task; o prompt do subagente usa o `core_prompt`
ou `core_build` correspondente.

**Por quê:** misturar tarefas mecânicas no local com tarefas difíceis no
nuvem é o ponto de “modelo por subagente”. Antes, o board nuvem executava as
tasks com prompt local por engano.

**Consequência:** o cliente por task é criado sob demanda; o resultado registra
o perfil em `subagents/<task>.json`.

---

---

## D-031 — Cancelamento cooperativo de subagente

**Decisão:** `run_agent` aceita `cancel_event` e `deadline`; o runner pausa a
execução e devolve a task para `pendente` quando o evento é disparado.

**Por quê:** cancelar no meio de uma chamada HTTP não é seguro sem matar a
thread; a parada no próximo step é previsível e preserva o quadro.

**Consequência:** TUI expõe `/subagente stop`; timeout e cancelamento não
interrompem uma requisição em andamento, mas evitam novos steps.

---

---

## D-032 — Escrita paralela com `writes` e locks

**Decisão:** tasks de escrita só entram no mesmo lote se declararem `writes:`
disjuntos; tools de escrita usam lock por caminho; `run_script` fica fora do
paralelo.

**Por quê:** locks sozinhos evitam colisão, mas não sabem o que a task escreve.
`writes` torna a intenção explícita e o runner consegue recusar lotes que se
sobrepõem.

**Consequência:** falha ainda pode deixar escrita parcial; rollback/overlay
fica para uma fase posterior. Cada branch grava checkpoint em
`subagents/<task>.json`, aplicado na retomada.

---

---

## D-033 — Laboratório de notebook como processo

**Decisão:** criar `laboratorio_notebook`, um fluxo genérico que recebe
PDF/Markdown/ideia e produz projeto em `data/labs/estudo` com hipótese,
formalização, script, notebook Colab, execução, relatório e nota.

**Por quê:** tasks comuns não davam estrutura para “testar uma ideia”: faltava
separar fonte, hipótese, experimento, evidência e formalismo. O fluxo serve
para matemática, dados e simulações, não para um tema específico.

**Consequência:** `write_notebook` e `run_notebook` entram no core. O notebook
é nbformat 4 com metadados Colab e caminhos relativos, sem depender do Ciel.

---

---

## D-034 — Lab limpo por execução

**Decisão:** o laboratório começa com `prepare_lab`, que arquiva o lab anterior
em `data/labs/_arquivo/` e cria um diretório vazio.

**Por quê:** a segunda execução do artigo leu `src/experimento.py` e
`FORMALIZACAO.md` da tentativa anterior, gastou steps relendo e tentou editar
arquivos velhos; o experimento nunca rodou.

**Consequência:** execuções são idempotentes do zero; o histórico fica em
`_arquivo/`. A fonte externa continua exigindo `/workspace`.

---

---

## D-035 — Notebook executado com outputs reais

**Decisão:** `run_notebook` executa as células code no mesmo namespace e grava
`stdout`, `execute_result`, `error` e imagens PNG como outputs nbformat no
próprio `.ipynb`.

**Por quê:** executar como script linear não deixava evidência no notebook; o
relatório citava números que o notebook não mostrava. Outputs persistidos
tornam a análise auditável e o arquivo útil no Colab.

**Consequência:** a verificação exige outputs, `metricas.json` e `VERIFICACAO`.
O executor é local, não é um kernel Jupyter completo; timeout é checado entre
células.

---

---

## D-036 — Auditoria neutra, não refutação competitiva

**Decisão:** a etapa de verificação é uma auditoria de evidência. Cada
afirmação precisa de script, saída e status (`suportado`, `contraexemplo`,
`inconclusivo`, `erro`). Refutação sem execução é inválida; falha lógica exige
trecho exato e passo questionado.

**Por quê:** um agente com incentivo para “ganhar” pode inventar objeções ou
argumentos que ele mesmo não verifica. O foco é análise, não debate.

**Consequência:** `verificacao/contraexemplos.py` é obrigatório; o JSON de
status é a fonte da verdade; “inconclusivo” é uma conclusão legítima.

---

---

## D-037 — Lab atual + histórico nomeado

**Decisão:** o processo sempre trabalha em `data/labs/estudo`; ao iniciar, o
lab anterior é arquivado em `data/labs/_arquivo/`. O comando `/lab salvar
<nome>` copia o estudo atual para `data/labs/estudos/<nome>/`.

**Por quê:** um caminho fixo simplifica checks e retomada, mas não serve para
consultar estudos antigos. O arquivo automático evita conflito; a cópia
nomeada preserva o estudo sem transformar o processo em algo específico.

**Consequência:** `/lab` lista atual, arquivo e salvos; `/lab salvar` usa
`copytree` e nunca sobrescreve por padrão.

---

## D-038 — Visualizador do site: página gerada roda em origem própria

**Decisão:** o site (`/`) ganhou um painel de visualização ao lado do chat.
Arquivos vêm de `data/` por `/preview/<path>` (inline, com MIME); pastas são
listadas por `/api/files`. Página gerada — projeto com `index.html` ou `html`
avulso — é servida por um **servidor estático efêmero por pasta**, em porta
própria e com token no caminho (`/p/<token>/...`), e aparece num iframe sem
sandbox.

**Por quê:** as duas alternativas falharam na prática. Servir pelo próprio
Flask coloca a página na origem do Ciel (pode chamar `/api/chat` com o cookie).
Servir num iframe com `sandbox` (origem opaca) faz os subrecursos saírem sem
cookie: `style.css`/`script.js` voltam 401 e a página abre **crua** — foi o que
aconteceu com a calculadora. Além disso, origem opaca não tem `localStorage`,
`type="module"` nem `fetch()` local. O servidor estático por pasta resolve os
três: CSS/JS irmãos carregam, a página tem origem de verdade e, por ser outra
origem, continua sem acesso à API e ao cookie do Ciel.

**Consequência:** html/css/js roda de verdade (jogo, calculadora, landing
page) e a página não precisa ser aberta em outra janela. App com backend
(Flask/Django/Java/C++) continua precisando de processo próprio e cai no
download; `docx`/`xlsx`/zip mostram cartão de download. O servidor estático só
escuta loopback (ou `0.0.0.0` com `--lan`), só serve a pasta de um projeto em
`data/`, exige token e não lista diretório.

A detecção do que o turno gerou é um **retrato de `data/user` antes/depois**
(mtime), não o texto da resposta nem o metadata da tool: funciona com
`secondary_model`, `write_files`, `run_script` e tools de MCP igualmente. Pasta
com `index.html` vira uma entrada só (abre como site), em vez de um chip por
arquivo.

---

## D-039 — Contexto medido em tokens, por perfil e por modelo

**Decisão:** o teto de contexto sai de `contexto.py` (bloco `contexto` do
`ciel_config.json`): **32k tokens** no perfil local, **128k** na nuvem, com
override por modelo (nome exato ou família). `chars_por_token` (3) converte para
os pontos que ainda cortam em caracteres. A compactação de histórico passa a
rodar em **todos** os perfis, e o Ollama recebe `options.num_ctx` = teto.

**Por quê:** medição real no histórico — "oi" = 13.082 tokens de entrada (system
+ schema de 50+ tools), "valeu" = 13.546 e uma task de 2 steps = 26.7k. O
prompt fixo come o orçamento antes da conversa; 16k é piso, 32k cobre a task.
Sem `num_ctx` valia o default do servidor Ollama (bem menor que a janela) e o
corte acontecia sem aviso; sem compactação no local, cada turno reenviava a
conversa inteira.

**Consequência:** o orçamento do histórico é a janela em chars menos 25% de
reserva (no Ollama, `num_ctx` cobre entrada e saída); `keep_last` 4 no local e 6
na nuvem; `run_agent` aceita `history_max_chars`/`history_keep_last`/`num_ctx`
explícitos para CLI e testes. Como o `run_agent` é compartilhado, CLI/TUI também
passam a compactar no perfil local. A cota do secundário também foi para tokens
(D-040).

---

## D-040 — Duas cotas: janela do turno x orçamento da sessão

**Decisão:** separar o que estava junto.

- `teto_tokens` (`contexto.py`) é a janela de **uma** chamada — 32k local,
  override por modelo (`gemma4:cloud` 64k), 128k nuvem. É físico: compacta e,
  perto do limite, sugere branch.
- `cota_sessao_tokens` é o **acumulado de tokens de entrada** da sessão (1M
  local / 2M nuvem). Serve de último recurso contra um loop que lê um livro
  inteiro, repete a mesma tool ou reenvia o mesmo prompt caro várias vezes.
- a cota do secundário segue a mesma lógica: 1M de entrada por sessão, avisos
  em 80/95% e bloqueio só no teto.

**Por quê:** com `gemma4:cloud` (modelo remoto via Ollama), o 32k não é limite
de RAM — mas 32k **por sessão** daria dois ou três turnos, porque cada turno
reenvia system + tools + histórico (13k+). A cota de sessão é sobre **entrada
acumulada**, não sobre a janela; usar a janela como cota transformava um
orçamento de custo em bloqueio precoce.

**Consequência:** uso persistido em `data/session_usage.json`; o turno que cruza
o teto termina (não mata trabalho no meio) e o próximo é bloqueado, com saída
por `/history salvar` e branch. Avisos 80/95 no painel e no SSE; o painel mostra
sessão, contexto do envio e secundário (só no perfil local). Números antigos em
chars são convertidos por `chars_por_token`.

---

## D-041 — Compressão na mesma sessão (`compressed_upto`), branch como fallback

**Decisão:** quando a cota da sessão chega perto do teto, o painel oferece
**continuar nesta sessão** (comprimir) ou **começar uma nova** (branch).

- **Continuar nesta sessão**: gera o resumo pelo mesmo caminho do
  `/history salvar`, grava `summary` + `compressed_upto = último turno` e zera o
  acumulado da cota. O contexto enviado ao modelo passa a ser o **resumo** (os
  turnos antigos saem do prompt, mas continuam visíveis no histórico); o
  contador começa de novo e volta a encher.
- **Começar uma nova**: branch com o resumo do pai (o id muda e a cota é nova).
- Se o resumo falhar (Ollama fora, provider sem resumo), o front cai
  automaticamente para a branch.

**Por quê:** só resetar o contador sem trocar o contexto enviado faria a barra
voltar a 100% no turno seguinte — a compressão precisa mexer no que vai para o
modelo, não só no número. Manter o id preserva a thread; a branch fica como
saída quando não há como resumir.

**Consequência:** coluna `compressed_upto` em `sessions` (ALTER automático em
banco antigo); `HistoryStore.compress_session`/`turnos_para_contexto`; endpoint
`POST /api/session/compress` (409 com turno em execução). O resumo custa tokens,
por isso o reset já parte do resumo no próximo envio. Sessão reaberta depois
disso ainda entra pelo fluxo de branch ("retomar"), não pelo mesmo id.

---

## D-042 — Anexo do chat no disco: orquestrador vê prévia, secundário vê o arquivo

**Decisão:** o anexo do chat vai para `data/user/uploads/<id>/` e o prompt do
orquestrador recebe `<arquivo nome=...>` com **2k chars de prévia** + o caminho.
O conteúdo completo fica no disco para `read_file` e para
`secondary_model(files=[...])`.

**Por quê:** antes o PDF era extraído em memória e 12k chars entravam no
histórico — o anexo competia com system/tools/histórico e o secundário só
recebia o texto que o orquestrador repassasse, com corte. Com o arquivo em
disco, o orquestrador gasta ~2k e o secundário lê o documento inteiro (até
`files_max_chars`), sem passar pelo contexto do orquestrador. É o que sustenta o
fluxo "artigo → artigo interativo" com o preview abrindo a saída.

**Consequência:** `uploads.py` (índice, prévia, limpeza por sessão e órfãos);
`/api/file/upload` (login, 25 MB, PDF/DOCX/texto); `_aplicar_anexos` no chat;
`_inject_files` extrai PDF/DOCX com orçamento total; anexos apagados com a
sessão. O legado (`file_text` e `/api/file/extrair`) continua aceito.

**Risco conhecido:** `secondary_model(files=[...])` aceita qualquer caminho
legível (sem guarda de workspace/credenciais) — é a spec de segurança separada;
não misturar com esta mudança.

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
| Orçamento de contexto | `contexto.py`, `agent_loop.py`, `llm/client.py` |
| Cota da sessão (persistida) | `server.py` (`USO_PATH`, `_registrar_uso`), `data/session_usage.json` |
| Compressão | `server.py` (`/api/session/compress`), `history_store.py` (`compressed_upto`) |
| Anexo do chat | `uploads.py`, `server.py` (`/api/file/upload`, `_aplicar_anexos`), `tools/secondary_model.py` (`_inject_files`) |
| Visualizador do site | `server.py` (`/preview`, `/api/files`, `/api/preview_site`), `preview_sites.py`, `web/static/preview.js` |

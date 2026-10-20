# Registro de decisões — Ciel

Decisões de arquitetura e nomenclatura tomadas durante a implementação dos
modos local/build e do multitask. Cada entrada registra a decisão e o porquê,
para não rediscutir o mesmo ponto depois.

Data de referência: 2026-10-19.

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

## D-003 — `/quadro` é o nome canônico do quadro

**Decisão:** o comando de visão/gestão do quadro é **`/quadro`**.
`/tarefas` pode existir como alias opcional, mas não como comando principal.
`/tasks` é rejeitado.

**Por quê:** `/task` e `/tarefas` diferem por uma letra e têm significados
diferentes; `/tasks` piora a colisão. `/quadro` não colide com `/task` nem com
`/multitask`, é o termo do roadmap (“quadro de tarefas”) e comunica estado, não
execução.

**Semântica dos comandos:**

| Comando | O que faz |
|---|---|
| `/task <arquivo>` | executa **uma** task `.md` (unidade isolada) |
| `/quadro` | lista tarefas e status do quadro atual; **não executa** |
| `/quadro nova <título>` | cria uma tarefa no quadro |
| `/quadro concluir <id>` | atualiza o status de uma tarefa |
| `/multitask <fluxo\|objetivo>` | planeja/executa o quadro, com checagens e correção |
| `/multitask --retomar <id>` | retoma uma execução pausada |

---

## D-004 — Um quadro só, compartilhado por build e multitask

**Decisão:** existe **um** quadro por execução/sessão, persistido em
`data/runs/<id>/board.json`. Build e multitask leem e escrevem o mesmo quadro.

**Por quê:** dois estados separados (“todo da sessão” e “quadro do multitask”)
fazem o usuário perguntar por que uma tarefa criada no chat não aparece no
`/multitask --listar`. Um quadro, várias views.

**Consequência:** `/quadro` é visão/gestão; `/multitask` é execução. As tasks
criadas no build podem ser executadas depois pelo multitask sem migração.

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

**Ainda não implementado:**

- `/quadro` e tools de gestão de tarefas;
- auto-execução de plano no build (por tool, não por mensagem);
- perfil build no `--task` headless, server e bots;
- imagens no build;
- Fase 4 (fluxo `web_projeto` + entrevista) e Fase 5 (TUI, revisão por fase,
  replanejamento automático).

**Ordem recomendada:** `/quadro` + tools de tarefa; depois decidir a tool de
execução de plano; depois Fase 4/5.

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

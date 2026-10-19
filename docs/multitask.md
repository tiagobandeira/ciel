# Multitask

Modo de execução que divide um objetivo em tasks, mantém o progresso em um
quadro em disco e entrega uma mensagem final formatada.

> **Estado:** Fase 1. O plano vem de um fluxo escrito à mão. Planejador com
> modelo secundário, checagens automáticas e TUI dedicada ainda não entraram.

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
perfil: local                 # local | build (opcional)
formato: markdown             # markdown | resumo | whatsapp | bullets
como_testar: abra index.html

## task: estrutura
fase: estrutura               # default: "geral"
agente: dev_helper            # persona opcional
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

Campos aceitos em cada task: `fase`, `agente`, `objetivo`, `ações`,
`resultado esperado`, `depende_de`, `checagem`. O parser é o mesmo de
`tasks/*.md` (`task_defs.parse_task_text`).

O `formato:` do cabeçalho define a mensagem final. Se o objetivo do usuário
pedir explicitamente ("em tópicos", "um resumo", "no WhatsApp"), o formato é
ajustado automaticamente; um `formato:` explícito no fluxo vence a heurística.

## Comandos

```
/multitask                          # visão geral (fluxos + execuções)
/multitask --fluxos                 # lista flows/
/multitask --listar                 # execuções e status
/multitask <fluxo> <objetivo>       # executa
/multitask <fluxo>                  # usa o objetivo do fluxo
/multitask --retomar <id>           # retoma tasks pendentes
```

Na CLI, o plano é mostrado antes de executar e pede confirmação.

## Como a execução funciona

1. O fluxo vira um `Board` (`multitask/flow.py`).
2. O runner (`multitask/runner.py`) pega a próxima task pendente cuja
   dependência já terminou.
3. Monta um contexto mínimo: objetivo geral, fase, task, ações, dependências
   e o que já foi concluído na fase.
4. Chama `run_agent` com `history=[]`, `context_injection=...` e um limite de
   steps por task.
5. Grava status, resumo, tokens, duração e artefatos detectados no quadro.
6. Repete até concluir, falhar, pausar (Ctrl+C) ou esgotar o orçamento.
7. Gera o relatório final (`multitask/report.py`) no formato do fluxo.

Artefatos são detectados pelos arquivos modificados/criados durante a task
(ignorando `.git`, `venv`, `__pycache__`, `data/runs`, banco de histórico etc.).

## Perfis de modelo

O fluxo pode declarar `perfil: build` para usar o provider secundário como
executor (o mesmo salvo por `/connect`). Sem provider configurado, cai no
Ollama local. O perfil `local` usa o modelo de `--model`.

## Limites desta fase

- Sem planejador: `/multitask <objetivo>` livre ainda exige um fluxo.
- Sem checagem automática: `checagem` é enviada ao modelo como critério, mas
  ainda não é validada por código (Fase 2).
- Sem correção automática de task falha: a execução para e o relatório mostra
  a falha e as pendências.
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

1. **Fase 2** — checagens por código (`arquivo`, `cmd`, `http`, `json`) e task
   de correção com limite.
2. **Fase 3** — planejador no modelo secundário, validação do plano, aprovação
   e replanejamento; `/multitask <objetivo>` livre.
3. **Fase 4** — fluxo `web_projeto` completo, entrevista, servidor e entrega.
4. **Fase 5** — painel na TUI, revisão por fase e retomada com mais garantias.

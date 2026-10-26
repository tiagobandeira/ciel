# Subagentes

Um subagente é a execução de uma task com contexto isolado, persona, tools,
modelo e limite próprios. O quadro é o supervisor; o subagente não vê o log
bruto dos outros, só o que a task declara como dependência.

## Campos da task

```markdown
## task: pesquisar-a
fase: Pesquisa
subagente: pesquisador
modelo: modelo-especifico
tools: read_file, list_directory
read_only: true
parallel: true
max_steps: 4
```

- `subagente` (ou `agente`): persona de `agents/`;
- `modelo`: modelo específico da task; vazio usa o modelo do papel;
- `tools`: restringe o schema;
- `read_only`: declara intenção somente leitura;
- `parallel`: pode rodar junto com tasks irmãs read-only;
- `max_steps`: orçamento de steps.

## Observar

```text
/subagente                  # lista da última execução
/subagente <run_id>         # lista de uma execução
/subagente <run_id> t1      # detalhe do subagente t1
```

Cada task grava `data/runs/<id>/subagents/<task_id>.json`.
O `/subagente` lê esses arquivos e mostra agente, status, tokens e se foi
paralelo — sem chamar o modelo.

## Ciclo de vida

1. O runner monta o contexto da task a partir do quadro.
2. Executa em board isolado quando é paralela.
3. Aplica o resultado no quadro principal.
4. Persiste `data/runs/<id>/subagents/<task_id>.json` com status, resumo,
   tokens, artefatos, erro, modelo, tools e `parallel`.

## Regras

- O subagente nunca tem mais permissão que a execução que o chamou.
- Limites de tokens/steps valem para a task.
- Paralelo só é permitido para tools de leitura.
- Escrita paralela ainda não existe: exige arquivos disjuntos e locks.

## Exemplo

```markdown
## task: fonte-a
fase: Pesquisa
parallel: true
tools: read_file, list_directory
read_only: true

## task: fonte-b
fase: Pesquisa
parallel: true
tools: read_file, list_directory
read_only: true
```

As duas rodam em threads; o quadro recebe dois resultados separados.

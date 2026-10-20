# Testes práticos do multitask

> **Nota:** o multitask virou motor interno. A superfície de usuário é
> `/processo` (ou o modo `build` em linguagem natural). Os comandos
> `/multitask ...` abaixo continuam funcionando como debug/deprecated, mas o
> fluxo normal é `/processo <nome> "objetivo"`.

Objetivo: exercitar o **motor** (plano, quadro, ferramentas, checagens,
correção, relatório, retomada) em projetos reais, não comparar qualidade de
modelo. A pergunta é: o Ciel consegue conduzir o trabalho sem o usuário
microgerenciar, e onde ele quebra?

## Preparo

```powershell
python ciel.py --cli --perfil nuvem --modo build
```

Se ainda não configurou o provider:

```text
/connect
/perfil nuvem
```

Para comparar com o modo otimizado, rode o mesmo caso em `/perfil local`.
O perfil fica visível no banner e no prompt (`build ❯` / `local ❯`).

## Casos prontos

Os fluxos ficam em `flows/` e podem ser executados direto. O objetivo do fluxo
pode ser sobrescrito pelo texto depois do nome.

| Caso | Comando | O que testa | Artefatos |
|---|---|---|---|
| Landing page | `/processo landing_page` | HTML/CSS/JS, skill de frontend, checagens de conteúdo | `data/user/landing_page/` |
| Jogo da cobrinha | `/processo jogo_web` | projeto multi-arquivo, lógica JS, checagens | `data/user/jogo_snake/` |
| Artigo de matemática | `/processo artigo_matematica "teorema de Bayes"` | texto longo, estrutura, revisão | `data/user/artigos/` |
| Notebook de matemática | `/processo notebook_matematica "teorema de Bayes"` | JSON `.ipynb`, checagem por comando, correção | `data/user/notebooks/` |

### 1. Landing page

```text
/processo landing_page
```

Espere: 3 tasks, checagens de arquivo e conteúdo. É o caso mais fácil; serve
para validar o caminho feliz.

### 2. Jogo da cobrinha

```text
/processo jogo_web
```

Espere: 4 tasks, criação de pasta/arquivos, HTML/CSS/JS, checagens de
`canvas`, `addEventListener`, `requestAnimationFrame` e `gameOver`.
É o melhor teste de **use tools de verdade** e de correção quando o JS sai
incompleto.

### 3. Artigo de matemática

```text
/processo artigo_matematica "uma introdução à teoria dos grupos"
```

Espere: 5 tasks (escopo, abertura, corpo, fechamento, revisão), arquivos
`escopo.md`, `artigo.md` e `revisao.md`, checagens de tamanho, headings e
referências. Testa contexto longo e se o modelo mantém o fio entre tasks; a
divisão em partes evita estourar steps e contexto em uma única redação.

### 4. Notebook de matemática

```text
/processo notebook_matematica "distribuição normal e teorema central do limite"
```

Espere: 3 tasks, `.ipynb` em JSON nbformat 4, checagem por comando que carrega
o JSON e exige células `code`. É o caso mais duro: o modelo precisa escrever
JSON válido com código dentro. Se falhar, observe a correção.

## Caso livre (planejador) — debug interno

O objetivo livre não é mais a superfície do produto; use um processo. Os
comandos `/multitask <objetivo>` abaixo ficam como debug do planejador.

```text
/multitask crie um notebook Jupyter em data/user/notebooks/bayes.ipynb explicando o teorema de Bayes, com células markdown e code, e valide que o JSON é válido
```

```text
/multitask escreva um artigo em data/user/artigos/derivadas.md sobre regras de derivação, com definições, exemplos e referências
```

```text
/multitask monte uma landing page para um app de finanças em data/user/financas e valide os arquivos
```

Espere: o planejador propõe fases/tasks, o harness valida (resultado esperado,
dependências, checagens), você aprova com `[s]` e acompanha. Se o plano vier
ruim, `[r]` e escreva o ajuste.

## Critérios de avaliação

**Motor (o que estamos testando):**

- o plano tem tasks pequenas e `resultado_esperado` verificável;
- cada task usa `create_directory`/`write_file`/tools reais;
- as checagens são executadas por código e batem com o que a task promete;
- falha de checagem tenta correção com o erro e os arquivos, sem repetir o
  mesmo erro mais de 2 vezes;
- o relatório final lista artefatos, verificações, falhas e pendências;
- `--retomar` continua de onde parou.

**Conteúdo (qualidade do modelo):** avaliado à parte. Um artigo raso ou um
jogo feio não é necessariamente falha do motor; anote, mas não misture com
bug de orquestração.

## Onde olhar quando falhar

| Sintoma | Onde olhar |
|---|---|
| Plano rejeitado / muitas tentativas | painel de erros do planejador; `prompts/planejamento.md` |
| Modelo tentou `run_script`/`create_tool` para pasta | tool `create_directory`, contexto da task |
| Parse errors com `<｜｜DSML｜｜ ...>` | adaptador DSML em `agent_loop`; modelo pode estar preso ao protocolo nativo |
| Modelo criando scripts para ler/editar arquivo | `read_file` com `offset`/`limit`, `edit_file`; reduzir `tools:` da task |
| Checagem falhou com o mesmo erro 2x | a checagem pode estar errada para a task |
| Task grande demais / estourou steps | dividir o fluxo ou ajustar o plano |
| Status `needs_tool` no fim da task | a checagem deveria decidir; runner agora desativa tool proposal |
| Arquivo salvo em pasta com timestamp | `output_dir` no `secondary_model` |
| `--retomar` não refaz task falha | limitação atual: só tasks pendentes |

Quadro e eventos de cada execução:

```text
data/runs/<id>/board.json
data/runs/<id>/eventos.jsonl
```

```text
/multitask --listar
/multitask --retomar <id>
```

## Registro dos testes

Preencha uma linha por execução:

| Data | Caso | Run id | Status | Tasks | Correções | Tokens | O que falhou |
|---|---|---|---|---|---|---|---|
| | landing_page | | | | | | |
| | jogo_snake | | | | | | |
| | artigo_matematica | | | | | | |
| | notebook_matematica | | | | | | |
| | livre | | | | | | |

## Benchmark de custo (artigo)

O fluxo `artigo_matematica` (5 tasks) foi medido em uma cópia isolada:

| Versão | Chamadas | Tokens | Resultado |
|---|---:|---:|---|
| Chunks de 2k por arquivo | ~34 | ~320k | 5/5 |
| Lote + chunks de 2k | ~45 | ~499k | 5/5 |
| Uma escrita por arquivo + compactação | 19 | **146,4k** | 5/5 |

A lição: **não fatiar arquivo em chunks de 2k**. Batch ajuda em leituras, mas
o custo dominante em artigo é a quantidade de `write_file`/`edit_file`.

### Bugfix (verificação)

O processo `corrigir_bug` (demo em `data/user/bugfix_demo`) fechou **3/3 tasks
com ~50k tokens** (47,4k input + 2,4k output). É o contraponto econômico ao
greenfield: quando o trabalho é achar/corrigir uma falha com check, o motor se
paga; quando é gerar um app inteiro, ainda não.

## Depois dos testes

Levar os resultados para o registro de decisões
([decisoes.md](decisoes.md)) e decidir, com evidência:

- o que é bug de motor (plano, check, contexto, ferramenta);
- o que é limitação de modelo (conteúdo, matemática, código);
- se `/quadro` realmente faz falta ou se status + retomada bastam.

Não implemente `/quadro` antes de sentir falta dele em pelo menos dois casos
reais.


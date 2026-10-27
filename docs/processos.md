# Perfis, modos e processos

O Ciel separa três camadas:

| Camada | Valores | Responde |
|---|---|---|
| **Perfil** | `local`, `nuvem` | Quem executa? |
| **Modo** | `chat`, `build` | Como executa? |
| **Processo** | `app_web`, `landing_page`, `jogo_web`… | O que está sendo construído? |

## Perfil

- **`local`**: orquestrador no Ollama. É o comportamento histórico, otimizado
  para modelos locais/menores e para a tool `secondary_model`.
- **`nuvem`**: orquestrador no provider configurado por `/connect` (API
  externa). Mais rápido, contexto maior e sem a tool `secondary_model` — o
  modelo da API é o próprio orquestrador.

O banner mostra `perfil: nuvem` e o modelo real. O perfil não muda o modo.

```text
/perfil              # mostra perfil, modo e orquestrador
/perfil local
/perfil nuvem
```

`build` e `cloud` continuam aceitos como aliases antigos de `nuvem`, mas a
partir desta versão o nome canônico é **`nuvem`**.

## Modo

- **`chat`**: conversa e tarefas normais.
- **`build`**: construção. O Ciel escolhe um **processo nativo** a partir da
  linguagem natural, mostra a spec/plano e executa com checagens.

```text
/modo chat
/modo build
```

O modo `build` exige o perfil `nuvem`. No prompt, ele aparece como `build ❯`;
no banner, `modo: build`.

## Processos

Processos são receitas nativas do Ciel. Eles usam o motor do multitask por
baixo (quadro, checks, correção, retomada), mas o usuário não precisa conhecer
esse motor.

```text
/processo                         # lista
/processo app_web "app de notas em markdown"
/processo web_projeto "app de notas com entrevista"
/processo landing_page
/processo analise_dados "analise data/vendas.csv"
/processo auditar_repo "audite src/ e o pyproject"
/processo gerar_testes "teste data/user/bugfix_demo"
/processo --retomar <id>          # retoma um processo pausado
/processo --analisar [id]         # analisa a execução (última por padrão)
```

No modo build, basta falar:

```text
quero um app de notas em markdown com preview e salvamento local
```

O Ciel detecta `app_web`, mostra o processo e segue para a spec/plano. Se não
reconhecer, responde como chat normal.

Processos iniciais:

| Processo | O que faz |
|---|---|
| `web_projeto` | app web com briefing entrevistado, spec, implementação e preview |
| `app_web` | app local com spec, interface, persistência e critérios de aceite |
| `landing_page` | página responsiva com hero, features e CTA |
| `jogo_web` | jogo simples em HTML/canvas/JavaScript |
| `analise_dados` | perfil, limpeza e análise de um dataset com relatório |
| `auditar_repo` | inventário, riscos e relatório de auditoria sem alterar código |
| `gerar_testes` | escreve e roda testes para um módulo sem alterar o fonte |
| `artigo_matematica` | artigo em Markdown com definições, teoremas e referências |
| `notebook_matematica` | notebook Jupyter sobre um tema matemático |
| `laboratorio_notebook` | testa hipótese/fonte com notebook Colab, execução e relatório |
| `corrigir_bug` | corrige uma falha reproduzível com correção mínima e check |

Os fluxos de exemplo (artigo, landing, jogo, notebook) continuam em `flows/`;
`app_web` é o primeiro processo com fase de spec explícita.

## Laboratório de notebook

`laboratorio_notebook` é o fluxo genérico para testar uma ideia:

- fonte PDF ou Markdown;
- hipótese/formalização;
- experimento em `src/experimento.py`;
- notebook Colab em `laboratorio.ipynb`;
- execução registrada;
- relatório e nota curta.

```text
/processo laboratorio_notebook "teste a hipótese do artigo data/artigo.pdf"
```

Saída:

```text
data/labs/estudo/
  fonte/artigo.md
  PLANO.md
  FORMALIZACAO.md
  src/experimento.py
  laboratorio.ipynb
  resultados/
  figuras/
  EXECUCAO.md
  RELATORIO.md
  NOTA.md
  VERIFICACAO.md
```

Serve para matemática, dados ou simulação; não é específico de Goldbach.
O notebook usa caminhos relativos e metadados Colab, sem depender do Ciel.

Se a fonte estiver fora do workspace:

```text
/workspace "C:\Users\tiago\Workspace\Conjectura Goldback"
```

Sem isso o `read_pdf`/`read_file` é negado. Alternativa: copie o PDF para
`data/labs/estudo/fonte/` e passe esse caminho no objetivo.

Cada execução chama `prepare_lab`: o lab anterior é movido para
`data/labs/_arquivo/` e o novo começa limpo. Isso evita herdar experimento e
notebook de uma tentativa anterior.

O lab atual fica em `data/labs/estudo`. Para guardar uma cópia nomeada:

```text
/lab salvar goldbach_12
/lab                  # lista atual, arquivo e estudos salvos
```

As cópias vão para `data/labs/estudos/<nome>/`.

O `run_notebook` executa célula a célula e grava `stdout`, expressões, erros e
figuras dentro do `.ipynb`; a verificação exige outputs reais, não apenas
`nbformat`.

A etapa `verificar` é uma **auditoria neutra**, não um debate: cada afirmação
precisa de um script em `verificacao/contraexemplos.py` e de status em
`resultados/verificacao.json` (`suportado`, `contraexemplo`, `inconclusivo`,
`erro`). Refutar sem saída de execução não é aceito, e não há recompensa por
achar erro.

## Corrigir bug

O `corrigir_bug` é parametrizado por um `ALVO.json`:

- projeto;
- comando de teste;
- diretório de execução;
- arquivo afetado, quando conhecido.

Sem objetivo explícito, usa o demo em `data/user/bugfix_demo` com
`media([])` falhando. Ele diagnostica, aplica a correção mínima e valida pelo
runner em `data/user/corrigir_bug/verificar.py`.

```text
/processo corrigir_bug
/processo corrigir_bug "corrija data/meu_projeto; teste python -m pytest -q"
```

Saídas:

```text
data/user/corrigir_bug/ALVO.json
data/user/corrigir_bug/DIAGNOSTICO.md
data/user/corrigir_bug/VERIFICACAO.md
```

Para rodar o demo de novo depois de corrigido:

```text
python examples/reset_bugfix_demo.py
```

Resultado histórico do demo: **3/3 tasks, ~50k tokens** (47,4k input + 2,4k
output), contra 1,5M de um app greenfield. É o caso onde o motor de checks se
paga.

## Gerar testes

O `gerar_testes` cria testes em `data/user/gerar_testes/` e executa contra o
alvo indicado, sem alterar o código-fonte:

- `ALVO.json` — alvo, módulo e comando;
- `tests/test_gerado.py` — casos de comportamento;
- `rodar.py` — runner que adiciona o alvo ao `sys.path`;
- `RESULTADO.md` — comando, saída e limitações.

O check executa `python rodar.py`. Se um teste falhar por bug real do código,
o processo registra isso em vez de corrigir o fonte.

## Auditoria

O `auditar_repo` é somente leitura no código auditado. Ele produz em
`data/user/auditoria/`:

- `INVENTARIO.md` — estrutura, stack, entradas e comandos;
- `RISCOS.md` — riscos com severidade e evidência;
- `RELATORIO.md` — resumo, top 5 e próximos passos.

Use quando quiser “o que está perigoso/frágil neste repo?” sem aplicar
correções. Para corrigir, encadeie com `corrigir_bug`.

## Análise de dados

O `analise_dados` espera um dataset (CSV/JSON/XLSX) citado no objetivo. Ele
produz em `data/user/analise_dados/`:

- `PERFIL.md` — shape, colunas, tipos e nulos;
- `dados_limpos.csv` + `LIMPEZA.md`;
- `ANALISE.md` — achados e limitações;
- `VERIFICACAO.md` — como reproduzir.

Os checks rodam `verificar.py`; números do relatório devem vir do script, não
da imaginação do modelo.

## Entrevista

O `web_projeto` começa com a task `briefing`: o Ciel faz 4 perguntas
(objetivo, público, funcionalidades e estilo), grava `BRIEFING.md` e só então
escreve a spec. Use `app_web` quando quiser o caminho direto, sem entrevista.

## Scaffold e tarefas idempotentes

Os processos `app_web`, `landing_page` e `jogo_web` começam copiando um
template de `templates/` (`copy_template`) em vez de gerar o boilerplate. Isso
reduz geração e deixa o modelo focar nas features.

Tasks com `pular_se_ok: true` verificam o critério antes de executar. Se já
passa, a task é marcada como concluída com `pulada=True` e custo zero. Use só
quando o check for realmente específico da task.

## Saída

O detalhe fica no log:

- steps, tools, checagens e correções no terminal;
- `data/runs/<id>/board.json` e `eventos.jsonl`.

A resposta final de um processo é curta: o que foi feito, arquivos, como
testar, verificação e pendências. O relatório completo fica no run.

## O que ainda falta

- `app_web` é um processo inicial; os checks de comportamento ainda são
  majoritariamente estáticos (arquivo/JS), não um navegador real.
- Processos de backend, análise de dados e LaTeX ainda não existem.
- A TUI ainda não executa o modo build; use `--cli`.
- `/quadro` continua adiado; o foco é processo + verificação.

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
/processo landing_page
/processo --retomar <id>          # retoma um processo pausado
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
| `app_web` | app local com spec, interface, persistência e critérios de aceite |
| `landing_page` | página responsiva com hero, features e CTA |
| `jogo_web` | jogo simples em HTML/canvas/JavaScript |
| `artigo_matematica` | artigo em Markdown com definições, teoremas e referências |
| `notebook_matematica` | notebook Jupyter sobre um tema matemático |
| `corrigir_bug` | corrige uma falha reproduzível com correção mínima e check |

Os fluxos de exemplo (artigo, landing, jogo, notebook) continuam em `flows/`;
`app_web` é o primeiro processo com fase de spec explícita.

## Corrigir bug (demo)

O processo `corrigir_bug` usa um demo em `data/user/bugfix_demo` com um teste
falhando (`media([])` levanta `ZeroDivisionError`). Ele diagnostica, aplica a
correção mínima e valida por comando.

```text
/processo corrigir_bug
```

Para rodar de novo depois de corrigido:

```text
python examples/reset_bugfix_demo.py
```

Resultado do primeiro teste: **3/3 tasks, ~50k tokens** (47,4k input + 2,4k
output), contra 1,5M de um app greenfield. É o caso onde o motor de checks se
paga.

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

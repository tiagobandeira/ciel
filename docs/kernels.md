# Kernels

Um kernel é um **ambiente base reutilizável**: template, variante, manifesto e
smoke test. Ele não é o produto final; é o terreno onde o modelo implementa.

## Estrutura

```text
kernels/
  web_static/
    kernel.yaml
```

```yaml
name: web_static
version: 1
description: apps, landings e jogos estáticos
variables:
  title: "Ciel"
variants:
  app:
    template: app_web
    checks: [index.html, style.css, app.js]
  landing:
    template: landing
    checks: [index.html, style.css, script.js]
  game:
    template: game
    checks: [index.html, style.css, game.js]
```

- `template`: pasta em `templates/`.
- `variant`: seleciona o template/checks.
- `variables`: substitui `{{chave}}` nos arquivos.
- `checks`: smoke de arquivos obrigatórios.

## Tool

```json
{"kernel": "web_static", "variant": "app", "dest": "data/user/app_web"}
```

`prepare_kernel`:

1. valida o kernel e a variante;
2. copia o template;
3. substitui variáveis;
4. roda o smoke de arquivos;
5. grava `.ciel/kernel.json` no destino.

Se o smoke falhar, retorna erro e não finge sucesso.

## Fluxos

`app_web`, `web_projeto`, `landing_page` e `jogo_snake` usam
`prepare_kernel` na task de estrutura:

```text
kernel="web_static", variant="app", dest="data/user/app_web"
```

## Adicionar um kernel

1. Crie `kernels/<nome>/kernel.yaml`.
2. Aponte `template` para uma pasta de `templates/`.
3. Liste `checks` de arquivos que precisam existir.
4. Adicione variáveis se o template tiver `{{placeholders}}`.
5. Teste com `python -m pytest tests/test_tools/test_prepare_kernel.py`.

## Próximos kernels

- `python_api`: venv, deps, src/tests, health check.
- `notebook`: ipykernel, template executável.
- `web_static` já cobre app/landing/jogo.

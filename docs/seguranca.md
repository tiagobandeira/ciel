# Segurança

O Ciel executa ações na sua máquina em nome do modelo. Esta página reúne as
proteções existentes e o que cada uma cobre — leia antes de rodar com modelos
menos confiáveis ou com input externo.

## Modelo de confiança

O agente pode ler/escrever arquivos, executar scripts e instalar pacotes. A
defesa é em camadas:

| Camada | Protege contra | Como |
|---|---|---|
| `venv` | instalação de pacote sujando o Python global | ambiente isolado, descartável |
| `--safe` | execução arbitrária de código | remove `run_script`, `create_tool` e `create_temp_tool` do schema |
| confirmação de tool | tool nova gerada pelo modelo | mostra o código e pede `[s]`/`[n]`/`[a]` |
| workspace guard | leitura/escrita fora do projeto | pede permissão explícita e persiste o grant |
| login do server | uso anônimo das tools completas | cookie assinado; sem login, modo seguro |
| senha do server | acesso à interface web | hash em `~/.ciel/secrets.json` |

## Execução de código

### `run_script`

Executa qualquer arquivo `.py` que o modelo solicitar. Use `--safe` para
desabilitar:

```bash
python ciel.py --safe
```

Recomendado com modelos pequenos propensos a alucinação, ou quando a CLI recebe
input de terceiros.

### `create_tool` / `create_temp_tool`

O agente pode criar tools novas dinamicamente e, dependendo do modelo, tentar
instalar pacotes via pip. Por isso o `venv` é essencial: a instalação fica
isolada do Python global e some junto com o ambiente. Tools criadas
dinamicamente ficam em `tools/temp/` e não são versionadas.

Antes de executar, a CLI mostra o código com syntax highlight e pede
confirmação:

```text
[s] sim   [n] nao   [a] auto (confia pro resto da sessão)
```

`[a]` (ou a flag `--auto`) dispensa novas confirmações até o fim da sessão. Em
modo headless (`--task`), a criação de tools é recusada automaticamente, a
menos que `--auto` seja passado de propósito.

### O que `--safe` remove

`--safe` tira do schema as tools de execução arbitrária — o modelo nunca as
vê:

- `run_script`
- `create_tool`
- `create_temp_tool`

A lista fica centralizada em `tool_dispatch.py` (`UNSAFE_TOOLS`). O `--safe` do
server e da TUI têm o mesmo efeito. No server, `--safe` vale para o processo
inteiro e ignora a autenticação.

## Workspace guard

Toda tool que recebe caminho de arquivo é validada contra o **diretório de onde
o Ciel foi iniciado** (o workspace, não a pasta de instalação). Se o modelo
tentar ler ou escrever fora dele, a CLI pede confirmação:

```text
[s] sim, só essa vez   [a] sim, e lembrar   [n] não
```

`[a]` persiste o grant em `.ciel_workspace.json` (gitignored) na raiz do
projeto; o path passa a aparecer no `/workspace` nas próximas sessões.

Para liberar um caminho antes de começar:

```bash
/workspace ~/projetos/outro-repo   # [l] leitura  [e] leitura+escrita  [n] cancelar
```

Em sessões headless (`--task`), qualquer acesso fora do workspace é recusado
sem prompt. Processos e fluxos também resolvem paths e `cwd` dentro do
workspace.

### Credenciais são sempre negadas

`~/.ciel/secrets.json` (chaves de provider + hash da senha) fica fora do
workspace por design. Se `CIEL_SECRETS_PATH` apontar para dentro do projeto, o
workspace guard sozinho liberaria o arquivo — por isso o caminho de segredos é
**sempre negado**, mesmo com grant do usuário.

## Server web

- O server escuta em `127.0.0.1` por padrão; `--lan` expõe na rede local **sem
  HTTPS** — use só em rede confiável.
- Sem login, as tools de execução ficam bloqueadas (modo seguro). Depois do
  login, valem as tools do agente.
- A senha é gerada na primeira execução e pode ser trocada no cadeado da
  página. Se esquecer, use `--reset-password` (operação de nível de sistema,
  executada no terminal).
- Downloads servem apenas arquivos de `data/`; indexar fonte local exige login.

Detalhes de login, reset e da interface `/ui`: [server.md](server.md).

## Limitações

- Modelos locais pequenos (< 8B) podem falhar em raciocínio complexo e alucinar
  chamadas — considere configurar um [modelo secundário](secondary-model.md).
- `--safe` reduz a superfície, mas não impede o modelo de ler/gravar dentro do
  workspace ou de fazer requisições HTTP.
- O workspace guard é sobre **caminhos**, não sobre conteúdo: um script
  executado com permissão pode fazer qualquer coisa que o seu usuário faz.
- Conteúdo vindo de páginas web (via `read_url`/`web_search`) é entrada não
  confiável; trate instruções embutidas em páginas como dados, não como ordens.
- A janela de contexto é otimizada por design: sessões típicas ficam em torno
  de 20k–30k tokens totais.

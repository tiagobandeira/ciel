# Modelo Secundário — CIEL

Documentação completa do recurso de modelo secundário: o que é, como funciona,
como configurar e como usar na prática.

---

## O que é o modelo secundário

O CIEL opera com dois modelos distintos com papéis complementares:

| Papel | Modelo | Responsabilidade |
|---|---|---|
| **Orquestrador** | Gemma4 via Ollama (local) | Recebe o input do usuário, decide quais tools usar, gerencia o loop agêntico |
| **Secundário** | Qualquer API OpenAI-compatible (externo) | Resolve tarefas que exigem raciocínio complexo ou contexto extenso |

O orquestrador **não é substituído** — ele continua no controle. O modelo secundário
é chamado como uma tool quando o orquestrador julga necessário, retorna o resultado,
e o orquestrador decide o que fazer com ele.

---

## Por que ter um modelo secundário

Modelos locais pequenos têm limitações conhecidas:

- Dificuldade com raciocínio em múltiplas etapas interdependentes
- Janela de contexto reduzida
- Qualidade variável em tarefas de código complexo

Em vez de trocar o orquestrador por um modelo maior (mais lento, mais caro),
o CIEL mantém o orquestrador local e leve, delegando apenas o que for necessário
para um modelo externo mais capaz.

**Resultado:** velocidade e economia no dia a dia, com capacidade extra disponível
quando o problema exigir.

---

## Como funciona o fluxo

```
Usuário
  ↓ input
Orquestrador (Gemma4 / Ollama)
  ↓ julga que o problema é complexo
  ↓ chama a tool secondary_model
Tool secondary_model
  ↓ verifica cota da sessão
  ↓ lê ciel_config.json (provider_id, base_url, model)
  ↓ resolve a api_key (env var → secrets.json → ciel_config.json)
  ↓ faz POST para a API (padrão OpenAI-compatible)
Modelo secundário (DeepSeek, GPT-4, Claude, etc.)
  ↓ retorna resposta
Tool secondary_model
  ↓ resposta curta → retorna inline
  ↓ resposta longa → salva em data/user/ e retorna caminho
Orquestrador
  ↓ usa o resultado para continuar o loop
Usuário
  ↓ recebe resposta final
```

### Comportamento observado na prática

Um detalhe não intencional mas valioso: o orquestrador age como
**prompt engineer automático**. O usuário manda algo vago, e o orquestrador
reformula num prompt mais estruturado e detalhado antes de passar ao secundário.

O usuário não precisa saber escrever bons prompts — o orquestrador faz isso
por ele.

---

## Arquivos envolvidos

| Arquivo | Papel |
|---|---|
| `tools/secondary_model.py` | a tool em si — lógica de chamada, cota e resposta |
| `ciel_config.json` | provider ativo — `provider_id`, `base_url`, `model` (sem chave; não commitado) |
| `providers.json` | catálogo de providers conhecidos, usado pelo `/connect` |
| `~/.ciel/secrets.json` | credenciais dos providers configurados — gerenciado por `trust/secrets.py`, fora do repositório |
| `trust/model_manager.py` | lógica de listagem/ativação de provider usada por `/model` |
| `ciel_config.example.json` | template público de referência (formato legado) |
| `data/secondary_quota.json` | controle de caracteres consumidos por sessão |
| `data/user/secondary_response_*.md` | respostas longas salvas automaticamente |

---

## Configuração passo a passo

### 1. Escolha um provider

O modelo secundário funciona com qualquer API que siga o padrão OpenAI-compatible.
Opções gratuitas para começar:

| Provider | URL base | Obs |
|---|---|---|
| **NVIDIA Build** | `https://integrate.api.nvidia.com/v1` | Gratuito, vários modelos disponíveis |
| **OpenRouter** | `https://openrouter.ai/api/v1` | Modelos gratuitos com `:free` no nome |
| **9router** | `http://localhost:20128/v1` | Proxy local, requer instalação separada |

### 2. Obtenha uma API key

**NVIDIA Build (recomendado para começar):**
1. Acesse [build.nvidia.com](https://build.nvidia.com)
2. Crie uma conta (sem necessidade de cartão)
3. Gere uma API key no dashboard
4. Escolha um modelo disponível (ex: `deepseek-ai/deepseek-v4-flash-0731`)

### 3. Configure com `/connect`

Dentro do Ciel (CLI ou TUI), rode `/connect` — não precisa mais editar `ciel_config.json` na mão. O comando lista os providers de `providers.json`, você escolhe um número, confirma (ou edita) a URL e o modelo, e cola a API key quando pedido:

```
> /connect

 1  NVIDIA Build       (gratuito, vários modelos disponíveis)
 2  OpenRouter         (modelos gratuitos com :free no nome)
 3  9router            (proxy local)
 4  Custom             (qualquer endpoint OpenAI-compatible)

 Número do provedor (Enter = cancelar): 1

 url: https://integrate.api.nvidia.com/v1

 Modelo (Enter = deepseek-ai/deepseek-v4-flash-0731)
 ❯ 

 obtenha sua chave em: https://build.nvidia.com
 API key (oculta): ****************

 ✓ NVIDIA Build configurado — modelo: deepseek-ai/deepseek-v4-flash-0731
 credenciais salvas em ~/.ciel/secrets.json (chave não exibida)
```

A chave nunca aparece na tela nem é salva em `ciel_config.json` — ela fica em `~/.ciel/secrets.json`, fora do repositório. Providers que não precisam de chave (locais, como o 9router) pulam essa etapa.

> A lista que aparece no `/connect` vem de `providers.json`, na raiz do projeto — a tabela do passo 1 é só um resumo dos mais comuns. Na TUI, `/connect` (ou `F5`) abre o mesmo fluxo como um modal, com os mesmos campos.

### 4. Ative com `/model`

`/connect` só salva a credencial — quem decide qual provider está ativo é o `/model`:

```
> /model

  local        gemma4:e2b-it-qat
  secundário   não configurado

  providers configurados:
   1  nvidia          deepseek-v4-flash-0731
   2  openrouter      qwen3-235b-a22b:free

  /connect  adicionar ou atualizar provider

 Número para ativar (Enter = manter atual): 1

 ✓ modelo secundário atualizado  nvidia · deepseek-v4-flash-0731
 salvo em ciel_config.json · chave lida de ~/.ciel/secrets.json
```

`/model` sem argumento também serve pra conferir o status a qualquer momento — mostra o modelo local, o secundário ativo (ou `não configurado`) e todos os providers já conectados, com `← ativo` marcando o atual. `/model <nome>` continua trocando o modelo **local** (Ollama) direto, sem abrir esse painel. Na TUI, o mesmo comando (ou `F5`) abre um modal equivalente — selecionar um provider na lista já ativa na hora.

> Como a chave não precisa mais ficar em `ciel_config.json` pra usar um provider configurado via `/connect`, o arquivo passou a guardar só `provider_id`, `base_url` e `model` nesse fluxo. Ele continua no `.gitignore` por ser config específica de cada ambiente — e ainda pode guardar a chave direto, se você preferir (ver abaixo).

---

## Parâmetros do ciel_config.json

Os três primeiros são escritos automaticamente pelo `/model` ao ativar um provider; os demais são só pra ajuste fino:

| Campo | Tipo | O que faz |
|---|---|---|
| `provider_id` | string | id do provider ativo (o mesmo usado no `/connect`, ex: `nvidia`, `openrouter`) |
| `base_url` | string | Endpoint da API do provider ativo |
| `model` | string | ID do modelo a ser usado |
| `api_key` | string | Chave direto no arquivo — fallback manual, sem passar por `/connect` (ver abaixo) |
| `api_key_env` | string | Nome da variável de ambiente a checar (padrão: `SECONDARY_MODEL_API_KEY`) |
| `timeout` | int | Segundos de espera pela resposta (padrão: 120) |
| `max_chars_per_session` | int | Limite de caracteres de input por sessão (padrão: 40000) |
| `max_response_chars` | int | Respostas maiores que isso são salvas em arquivo (padrão: 8000) |
| `max_tokens` | int | Máximo de tokens na resposta do modelo secundário (padrão: 16384) |

### De onde vem a API key

`/connect` é o caminho recomendado, mas não é o único — a tool resolve a chave nesta ordem, parando na primeira que encontrar:

1. Variável de ambiente, com o nome definido em `api_key_env` (padrão `SECONDARY_MODEL_API_KEY`)
2. `~/.ciel/secrets.json`, pelo par `provider_id` + `model` (o que o `/connect` salva)
3. `~/.ciel/secrets.json`, só pelo `provider_id` (se não achar o modelo específico)
4. `api_key` direto no `ciel_config.json`

Então colocar a chave direto no `api_key` do config continua funcionando — é um fallback manual intencional, não uma opção descontinuada, bom pra testar um provider rápido sem cadastrá-lo formalmente com `/connect`. Se nenhuma das quatro opções resolver, a tool retorna erro pedindo pra configurar a variável de ambiente ou adicionar `api_key` no config.

Pra não deixar a chave em disco nenhum (ex: CI, deploy), a variável de ambiente é a opção mais indicada — tem prioridade sobre tudo:

```bash
# Linux/macOS
export SECONDARY_MODEL_API_KEY="nvapi-..."

# Windows (PowerShell)
$env:SECONDARY_MODEL_API_KEY="nvapi-..."
```

---


## Trocando de provider

O provider é intercambiável — não precisa editar nada no código nem no `ciel_config.json` na mão. O fluxo é sempre o mesmo: `/connect` uma vez por provider (salva a credencial em `~/.ciel/secrets.json`), depois `/model` pra escolher qual fica ativo. Como cada provider conectado fica salvo, trocar entre eles depois é só rodar `/model` de novo e escolher outro número — sem passar pelo `/connect` de novo.

Alguns exemplos do que dá pra conectar:

- **OpenRouter** — bom pra testar modelos gratuitos (sufixo `:free` no nome do modelo)
- **9router** — proxy local; se estiver rodando sem exigir autenticação própria, o `/connect` pula direto o campo de API key
- **OpenAI** — `gpt-4o` e outros, com sua chave da OpenAI
- **Custom** — qualquer outro endpoint OpenAI-compatible que não esteja na lista (Anthropic via proxy, Azure OpenAI, etc.) — o `/connect` pede a URL manualmente nesse caso

Pra ver todos os providers já conectados e qual está ativo, rode `/model` a qualquer momento.

---

## Controle de cota

A tool rastreia quantos caracteres de input foram enviados ao modelo secundário
por sessão, armazenando em `data/secondary_quota.json`:

```json
{
  "70": 1285,
  "71": 358
}
```

Cada chave é um `session_id`. Quando o total da sessão ultrapassa
`max_chars_per_session`, a tool retorna uma mensagem de cota esgotada
sem fazer a chamada.

O `session_id` é injetado automaticamente pelo `run_agent()` em `cli.py`,
seguindo o mesmo padrão das tools RAG — o modelo não precisa passá-lo
explicitamente.

---

## Respostas longas

Quando a resposta do modelo secundário ultrapassa `max_response_chars` (padrão: 8000),
a tool salva automaticamente em `data/user/secondary_response_TIMESTAMP.md`
e retorna o caminho + uma prévia:

```
Resposta completa salva em: data/user/secondary_response_20260823_212950.md

Prévia:
# Implementação do Algoritmo de Dijkstra...
…

Use read_file com o caminho acima para ler a resposta completa.
```

O orquestrador então usa `read_file` para carregar o conteúdo e entregá-lo
ao usuário. Esse fluxo evita entupir o contexto do orquestrador com respostas
muito longas.

---

## Quando o modelo secundário é chamado

O critério de delegação está no `system/core_prompt.md`. O orquestrador
é instruído a chamar `secondary_model` quando identificar:

- Raciocínio em múltiplas etapas interdependentes
- Contexto muito longo para processar com precisão
- Código ou lógica complexa que exige análise profunda
- Falha repetida na mesma tarefa

E a **não** chamar quando:
- A tarefa é simples e as tools disponíveis já resolvem
- A pergunta é factual (use RAG)
- Uma tool específica já cobre o caso

O usuário também pode forçar a delegação explicitamente:
```
Use o modelo secundário para...
```

---

## Degradação graciosa

Se o modelo secundário falhar (API key inválida, timeout, provider fora),
o orquestrador não trava — ele recebe o erro como retorno da tool e
decide por conta própria como continuar, usando as tools disponíveis.

Na prática isso significa que o CIEL funciona normalmente mesmo sem
o modelo secundário configurado. O recurso é uma adição, não uma dependência.

---

## Arquitetura da tool

```python
# tools/secondary_model.py

def run(prompt, session_id, system, save_response) -> str:
    # 1. carrega ciel_config.json (provider_id, base_url, model)
    # 2. verifica cota da sessão (secondary_quota.json)
    # 3. resolve api_key: env var → secrets.json (provider:model) →
    #    secrets.json (provider) → api_key inline no config
    # 4. POST /chat/completions (padrão OpenAI)
    # 5. atualiza cota
    # 6. resposta curta → retorna str
    #    resposta longa → salva em data/user/ → retorna caminho + prévia
```

Parâmetros da tool:

| Parâmetro | Tipo | Padrão | O que faz |
|---|---|---|---|
| `prompt` | str | — | Descrição completa do problema |
| `session_id` | str | `_nosession` | Controle de cota (injetado automaticamente) |
| `system` | str | prompt padrão | Instrução de sistema para o modelo secundário |
| `save_response` | bool | `False` | Força salvar em arquivo mesmo se resposta for curta |

---

## Validação do setup

A forma mais rápida é rodar `/model` dentro do Ciel: o painel já mostra se a chave foi encontrada, e sinaliza `(chave não encontrada — use /connect)` quando falta algo.

Pra testar a chamada HTTP isolada, sem passar pelo Ciel:

```bash
python -c "
import json, os, requests
from pathlib import Path
from trust.secrets import secrets as sm

cfg = json.loads(Path('ciel_config.json').read_text())
pid, model, base_url = cfg.get('provider_id'), cfg.get('model'), cfg.get('base_url')
print('Provider:', pid)
print('Model:', model)

api_key_env = cfg.get('api_key_env', 'SECONDARY_MODEL_API_KEY')
api_key = sm.resolve_api_key(pid, model=model, env_var=api_key_env) or cfg.get('api_key', '').strip()
print('API key:', 'OK' if api_key else 'NAO ENCONTRADA')

resp = requests.post(
    base_url.rstrip('/') + '/chat/completions',
    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    json={'model': model, 'messages': [{'role': 'user', 'content': 'responda apenas: ok'}]},
    timeout=30,
)
print('Status:', resp.status_code)
print('Resposta:', resp.json()['choices'][0]['message']['content'])
"
```
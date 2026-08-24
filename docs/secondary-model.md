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
  ↓ lê ciel_config.json (provider, model, api_key)
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
| `ciel_config.json` | configuração local com provider, model e api_key (não commitado) |
| `ciel_config.example.json` | template público sem chave real |
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

### 3. Configure o ciel_config.json

Copie o arquivo de exemplo e preencha com suas credenciais:

```bash
cp ciel_config.example.json ciel_config.json
```

Edite `ciel_config.json`:

```json
{
  "base_url": "https://integrate.api.nvidia.com/v1",
  "model":    "deepseek-ai/deepseek-v4-flash-0731",
  "api_key":  "nvapi-SUA_CHAVE_AQUI",

  "timeout":               120,
  "max_chars_per_session": 40000,
  "max_response_chars":    8000
}
```

### 4. Verifique o .gitignore

O `ciel_config.json` já deve estar no `.gitignore` para proteger sua chave:

```
ciel_config.json
```

---

## Parâmetros do ciel_config.json

| Campo | Tipo | O que faz |
|---|---|---|
| `base_url` | string | Endpoint da API do provider |
| `model` | string | ID do modelo a ser usado |
| `api_key` | string | Chave de autenticação (inline) |
| `api_key_env` | string | Nome da variável de ambiente com a chave (alternativa ao `api_key`) |
| `timeout` | int | Segundos de espera pela resposta (padrão: 120) |
| `max_chars_per_session` | int | Limite de caracteres de input por sessão (padrão: 40000) |
| `max_response_chars` | int | Respostas maiores que isso são salvas em arquivo (padrão: 8000) |

### api_key vs api_key_env

**`api_key` direto no config** — mais simples, recomendado para uso pessoal:
```json
{ "api_key": "nvapi-..." }
```

**`api_key_env`** — a tool busca a chave em uma variável de ambiente:
```json
{ "api_key_env": "SECONDARY_MODEL_API_KEY" }
```
```bash
# Linux/macOS
export SECONDARY_MODEL_API_KEY="nvapi-..."

# Windows (PowerShell)
$env:SECONDARY_MODEL_API_KEY="nvapi-..."
```

---

## Trocando de provider

O provider é intercambiável — basta editar `ciel_config.json`.
Exemplos prontos:

**OpenRouter (modelos gratuitos):**
```json
{
  "base_url": "https://openrouter.ai/api/v1",
  "model":    "qwen/qwen3-235b-a22b:free",
  "api_key":  "sk-or-SUA_CHAVE_AQUI"
}
```

**9router (proxy local):**
```json
{
  "base_url": "http://localhost:20128/v1",
  "model":    "kr/claude-sonnet-4.5",
  "api_key":  "sua-api-key-do-9router"
}
```

**OpenAI:**
```json
{
  "base_url": "https://api.openai.com/v1",
  "model":    "gpt-4o",
  "api_key":  "sk-SUA_CHAVE_AQUI"
}
```

Nenhuma alteração no código é necessária — só o config muda.

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
    # 1. carrega ciel_config.json
    # 2. verifica cota da sessão (secondary_quota.json)
    # 3. obtém api_key (env ou config)
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

Para verificar se tudo está configurado corretamente antes de usar no CIEL:

```bash
python -c "
import json, os, requests
from pathlib import Path

cfg = json.loads(Path('ciel_config.json').read_text())
print('Provider:', cfg.get('base_url'))
print('Model:', cfg.get('model'))

api_key = cfg.get('api_key') or os.environ.get(cfg.get('api_key_env', ''), '')
print('API key:', 'OK' if api_key else 'NAO ENCONTRADA')

resp = requests.post(
    cfg['base_url'].rstrip('/') + '/chat/completions',
    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    json={'model': cfg['model'], 'messages': [{'role': 'user', 'content': 'responda apenas: ok'}]},
    timeout=30,
)
print('Status:', resp.status_code)
print('Resposta:', resp.json()['choices'][0]['message']['content'])
"
```

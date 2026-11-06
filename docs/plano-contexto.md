# Plano — limites de contexto por perfil

Status: **proposta**, nada implementado ainda.
Origem: sessão do RPG (#438), em que um PDF anexado no chat entrou como binário
de 12k chars. O bug do anexo já foi corrigido; isto aqui trata do problema de
fundo — **quanto do conteúdo a sessão manda para o orquestrador**.

## Status da implementação (2026-11-05)

Já entrou (incremento 1, Parte 1):

- `contexto.py` — defaults por perfil (local **32k** / nuvem **128k** tokens),
  override por modelo (nome ou família), `chars_por_token` (3), `keep_last`,
  bloco do anexo e `avisar_truncamento`; config corrompida cai no default.
- Compactação de histórico roda em **todos os perfis** (antes só nuvem), com
  orçamento = janela em chars − 25% de reserva para a resposta.
- `options.num_ctx` no payload do Ollama = teto do perfil/modelo (antes não
  mandávamos nada e valia o default do servidor) — inclusive o `_call_model`
  histórico.
- Testes: `tests/test_core/test_contexto.py` e casos novos em
  `tests/test_integration/test_agent_loop_batch.py`.

Ainda não (próximos incrementos): upload do anexo com prévia em disco (Parte 2),
cota do secundário em tokens + atribuição de limite e tela de Consumo (Parte 3),
e `source_ids`/`files` por tipo no secundário.

## Objetivo

Impedir que o contexto do orquestrador estoure, respeitando o perfil:

- **local** (Ollama): janela curta, conteúdo precisa ser bem menor;
- **nuvem** (provider): janela grande, pode receber mais — mas ainda com teto,
  porque cada turno é pago.

Regra de ouro: o modelo **nunca** deve receber mais do que cabe; e quando algo
for cortado, o usuário e o modelo precisam saber que foi cortado.

## Estado atual (verificado no código)

| Ponto | Hoje | Perfil |
|---|---|---|
| Anexo do chat (`file_text`) | cortado em 12.000 chars ([server.py](../server.py)) | local + nuvem, igual |
| Extração de PDF | teto de 12.000 chars | local + nuvem, igual |
| Histórico enviado ao `run_agent` | `state.history[:-1]` **sem corte** | ambos |
| Compactação de histórico | `_compact_history`, 30k chars, mantém últimas 6 ([agent_loop.py](../agent_loop.py)) | **só nuvem** |
| Resultado de lote de leitura | 12.000 chars | ambos |
| `num_ctx` do Ollama | não é enviado (vale o default do modelo) | local |
| Modelo secundário | cota de 40k chars por sessão; `files` injetados **inteiros** | só local |
| Upload do chat no disco | **não é salvo** — só o texto (≤12k) entra no histórico | ambos |
| Fonte (upload/URL) | fica em `data/user/sources/` + `knowledge.db` (id, chunks) | ambos |

Consequências:

1. O perfil **local** é o mais exposto: sem compactação, cada turno reenvia a
   conversa inteira **mais** o anexo de 12k. Quem corta é o Ollama, e o corte
   não é controlado por nós — pode comer o começo do prompt (system prompt).
2. O anexo de 12k fica no histórico para sempre e é reenviado em todo turno.
3. O corte do anexo é **silencioso**: nem o usuário nem o modelo sabem que
   faltou conteúdo (um PDF de 60 páginas vira 12k chars sem aviso).
4. No perfil nuvem a compactação existe, mas o anexo continua com o mesmo teto
   do local — não há ganho de janela.

## Proposta

### 1. Orçamento por perfil **e por modelo**, configurável

O teto é a janela útil do modelo (número que aparece no card dele), não um
número mágico nosso. Medição no histórico real (perfil local, `gemma4:cloud`):
"oi" = **13.082 tokens** de entrada, "valeu" = 13.546, e uma task simples de
2 steps = **26.7k–26.9k**. O prompt fixo (system + schema de 50+ tools) come o
orçamento antes da conversa começar — por isso o default local é **32k tokens**
(16k é o piso: cabe um turno de chat, não uma task; 32k cobre a task simples) e
**128k na nuvem** — sobrescrevível por modelo e depois editável no painel de
configurações do site.

```json
{
  "contexto": {
    "teto_tokens":  { "local": 32000, "nuvem": 128000 },
    "por_modelo":   { "gemma4:cloud": 32000, "deepseek-chat": 128000 },
    "chars_por_token": 3,
    "anexo": {
      "previa_chars": 2000,
      "teto_tokens": 8000
    },
    "history_keep_last": { "local": 4, "nuvem": 6 },
    "avisar_truncamento": true
  }
}
```

- O código ainda trabalha em **chars** em alguns pontos; a conversão é
  `tokens × chars_por_token` (3 é conservador para PT/EN). A Parte 3 troca isso
  por tokens reais onde já dá para medir.
- Leitura num único helper (`contexto_config()`), com fallback para os defaults
  se a chave não existir (config antigo continua funcionando).
- O `server.py` usa o orçamento do modelo ativo (override > perfil) no lugar do
  12.000 fixo.
- O `run_agent` recebe `history_max_chars` / `history_keep_last` e chama a
  compactação **em qualquer perfil** (hoje só nuvem), com o orçamento do perfil.
- Para o teto ser real no local, o payload do Ollama passa a levar
  `options.num_ctx` = `teto_tokens` (hoje não mandamos nada e vale o default do
  servidor).
- O orçamento tem três parcelas: **fixo** (system + schema, ~13k),
  **histórico** e **anexo**. O trace mostra a quebra, para não parecer que a
  conversa está consumindo o que na verdade é prompt fixo.
- No perfil nuvem o `run_agent` recebe `model=""` (o cliente injetado já carrega
  o modelo), então o override por modelo ainda não se aplica ali: vale o default
  do perfil. Ajuste futuro: expor o id do modelo no cliente e repassar como
  `contexto_model`.

### 2. Compactação também no local

`_compact_history` já existe e não destrói o histórico salvo (ela mexe só na
lista `messages` do turno). A mudança é tirar o `if profile == PERFIL_NUVEM`
([agent_loop.py](../agent_loop.py)) e passar os parâmetros do perfil.

**Feito:** a compactação roda em qualquer perfil. O orçamento é
`teto_tokens × chars_por_token − 25%` (reserva para a resposta, porque no Ollama
`num_ctx` cobre entrada e saída) e `keep_last` vem do perfil
(local 4 / nuvem 6). `run_agent` ainda aceita `history_max_chars` e
`history_keep_last` explícitos, para CLI e testes.

Cuidado: `run_agent` é o mesmo para CLI, TUI, web e bot — ligar a compactação no
local muda o comportamento de todos. É desejável, mas entra com teste e nota em
`docs/decisoes.md`.

### 3. Aviso de truncamento + leitura parcial (sem recusar)

Truncar, nunca recusar — recusar gera frustração e o usuário só queria uma
resposta.

- **Usuário**: quando o anexo for cortado, o chat mostra
  `anexo truncado: 2.000 de 38.000 caracteres (prévia do início)`.
- **Modelo**: o bloco termina com
  `[... prévia truncada em 2.000 de 38.000 caracteres; conteúdo completo em <caminho>]`
  e com uma instrução curta: *se a pergunta exigir o material inteiro, diga que
  leu só a prévia e ofereça (a) aprofundar com o secundário ou (b) apontar o
  trecho que interessa*. É o "meio termo": o modelo não inventa que leu tudo e
  pode pesquisar o trecho via tool (`read_file` com trecho, `search_knowledge`,
  `secondary_model` com o arquivo).
- **Análise completa**: quando o usuário pedir explicitamente "leia tudo",
  isso vira caso de capacidade e cai no secundário (perfil local) ou no próprio
  orquestrador grande (perfil nuvem).
- **Trace**: o `AgentResult` já carrega `context_peak_chars` e `compactions`;
  expor isso no painel de sessão (`contexto: 12k chars · 2 compactações`).

### 4. Fase 2 (avaliar depois)

- **`num_ctx` explícito no perfil local**: mandar `options.num_ctx` no payload
  do Ollama (ex.: 8192), para o corte deixar de ser uma surpresa do servidor.
  Alternativa mais fraca: estimar tokens (`chars/4`) e recusar o turno acima do
  orçamento com mensagem clara.
- **PDF por páginas**: extrair até atingir o orçamento e informar
  `páginas 1–12 de 40` no aviso.
- **Resumo do anexo grande** via `secondary_model` sob demanda (caro; só quando
  o usuário pedir).

## Parte 2 — passar arquivos para o secundário sem carregar no orquestrador

Requisito: com orquestrador pequeno (ex.: `gemma4:cloud`, janela curta no
Ollama) e secundário maior (ex.: DeepSeek por API), os arquivos devem ir
**direto** para o secundário. O orquestrador só precisa carregar o *nome*, o
*caminho* ou o *id* — nunca o conteúdo.

### Quem é quem em cada perfil

| Perfil | Orquestrador | Secundário | Como o arquivo deve chegar |
|---|---|---|---|
| `local` | Ollama (janela curta) | tool `secondary_model` (API) | caminho/`source_id` → a tool lê e manda ao secundário; orquestrador recebe só prévia curta + referência |
| `local` sem provider | Ollama | **não existe** (sem chave) | não há para onde descarregar: vale o orçamento pequeno da Parte 1, com aviso |
| `nuvem` | o próprio provider (grande) | **não existe** — o `secondary_model` é removido | o orquestrador lê o arquivo direto pelo caminho; orçamento maior, sem offload |

Ou seja: o fluxo "descarregar no secundário" só existe no perfil `local` com
provider configurado. No `nuvem` não há secundário para receber — o ganho é
apenas o orçamento maior e não reenviar o arquivo no histórico.

### Como está hoje

A tool já foi desenhada para receber **caminhos**: `secondary_model(files=[...])`
é quem lê o conteúdo ([secondary_model.py](../tools/secondary_model.py)). Pelo
contexto do orquestrador passa só a string do caminho. Até aí, funciona.

Os problemas estão nos fluxos que alimentam a tool:

1. **`knowledge.db` só tem fontes.** Anexo do chat não é indexado nem salvo em
   disco: vira `file_text` e mora no histórico. Fonte é outra coisa (fica em
   `data/user/sources/` e tem `id`).
2. **Fonte não expõe caminho.** `list_sources` devolve `[id=N] arquivo.pdf`,
   sem `filepath` ([list_sources.py](../tools/list_sources.py)). Sem caminho, o
   orquestrador só consegue `read_source(id)` — até 6.000 chars no contexto dele
   ([read_source.py](../tools/read_source.py)) — e depois repassa no `prompt`.
3. **Anexo do chat carrega no orquestrador por definição** (12k no histórico,
   reenviado a cada turno).
4. **PDF em `files` quebra**: `_inject_files` usa `read_text`, então binário vira
   lixo. Falta rotear por tipo e pôr teto por arquivo.
5. **Cota manda mais que a janela do provedor**: 40.000 chars por sessão
   (prompt + arquivos), fixos — independente do modelo secundário.

### Proposta

1. **Anexo do chat vira arquivo + prévia do início (sem `knowledge.db`).**
   Endpoint de upload grava em `data/user/uploads/<sessão>/<nome>` e devolve
   `{caminho, nome, chars, preview}`. A mensagem leva só a **prévia**
   (primeiros `anexo.previa_chars`, default 2.000) **e o caminho**; o conteúdo
   completo fica em disco e **não** conta no orçamento do histórico.
   - A prévia é o começo do documento de propósito: resumo, sumário e
     introdução ficam nas primeiras páginas — mesma lógica usada ao preparar
     as fontes.
   - `local` com provider: o orquestrador passa `files=[caminho]` e o
     secundário lê o inteiro; o turno guarda a prévia e o resumo que voltou.
   - `nuvem`: o orquestrador lê o caminho direto quando precisar (janela maior).
   - Sem texto extraível (PDF escaneado): avisa o usuário e mantém o caminho;
     não injeta bytes. OCR fica para outra feature.
2. **`secondary_model(source_ids=[...])`** para fontes: a tool resolve
   `id → filepath` no `knowledge.db` e injeta. O orquestrador continua vendo só
   `[id=N] nome`.
3. **Leitura por tipo em `_inject_files`**: `.pdf` → PyPDF2, `.docx` →
   python-docx, texto → `read_text`; tipo desconhecido ou PDF sem texto → aviso
   inline, não lixo. Teto por arquivo (default = orçamento de anexo) e o retorno
   informa quanto foi injetado.
4. **Cota por provider/modelo**: hoje 40k fixos; passa a aceitar override por
   entrada de provider, para aproveitar janela grande do secundário.
5. **Visibilidade**: o retorno da tool e o trace dizem "enviado 38k/40k chars ·
   2 arquivos", para o usuário saber o que o secundário recebeu.

### Limpeza dos arquivos (estado atual verificado)

A memória de que "apagar a sessão apaga os arquivos" está **só parcialmente
certa** ([history_store.py](../history_store.py)):

| Arquivo | Apaga com a sessão? | Apaga com a fonte? |
|---|---|---|
| Fonte indexada de URL (cache) | **sim** (`delete_session_cache`) | sim |
| Fonte enviada em `data/user/sources/` | **não** | **não** (só remove do `knowledge.db`) |
| `secondary_response_*.md` (respostas grandes do secundário) | **não** (nome sem sessão) | — |
| Projeto gerado em `data/user/<slug>_<ts>/` | **não** | — |
| Anexo do chat (proposto: `data/user/uploads/<sessão>/`) | a implementar | — |

Proposta: uploads do chat são por sessão e saem junto com ela; fonte enviada
(arquivo em `data/user/sources/`) sai quando a fonte é removida **se não for
global**; `secondary_response_*` passa a levar sufixo de sessão e entra na
limpeza; projeto gerado **nunca** é apagado (é entrega do usuário).

### Fora do escopo (segurança, tarefa separada)

`files`/`source_ids` não passam pelo guard de workspace — hoje o modelo poderia
injetar `~/.ciel/secrets.json` e o secundário mandaria o conteúdo para a API.
Isso é **exfiltração**, não contexto, e merece spec próprio (denylist de
credenciais + `workspace.check` por caminho dentro da tool). Fica registrado
aqui para não ser esquecido, mas não bloqueia a funcionalidade.

### Testes

- `secondary_model(files=[...])` injeta o conteúdo no prompt enviado ao
  secundário, sem passar pelo `prompt` do orquestrador (HTTP capturado).
- `.pdf` em `files` injeta texto extraído, não binário; PDF sem texto vira aviso.
- `source_ids` resolve id → arquivo; id inexistente vira aviso.
- Anexo do chat: arquivo salvo no caminho informado, mensagem leva só prévia +
  caminho, e o histórico não guarda o conteúdo completo.
- Cota: soma dos arquivos injetados é contada e recusa com mensagem clara.
- Limpeza: apagar a sessão remove `data/user/uploads/<sessão>/`.

## Parte 3 — medir e limitar em tokens (não em chars)

### O que já existe

- **Orquestrador**: tokens reais por chamada, direto do provedor — Ollama
  (`prompt_eval_count`/`eval_count`) e OpenAI-compatível
  (`usage.prompt_tokens`/`completion_tokens`) em [llm/client.py](../llm/client.py).
  O server soma por sessão e mostra no painel (↑/↓).
- **Secundário**: o stream pede `stream_options.include_usage` e guarda o
  `usage` ([secondary_model.py](../tools/secondary_model.py)) — hoje usado para
  exibir e para o `token_tracker`.
- **A cota do secundário ainda conta chars**: `_load_quota`/`_save_quota`
  guardam `len(prompt)` e `max_chars_per_session` (40k). Quando estoura, a
  mensagem é a mesma família de um erro do provedor — não dá para saber quem
  barrou.

### Proposta

1. **Cota do secundário em tokens**: `max_tokens_per_session` (migrando o
   efetivo atual: 40k chars ≈ 12k tokens), debitada com
   `usage.prompt_tokens + completion_tokens` depois da chamada; admissão
   pré-call por estimativa (`chars/3`) e fallback em chars quando o provedor não
   devolver `usage`.
2. **Orçamentos do contexto em tokens**: teto, histórico e anexo comparados em
   tokens (estimativa pré-call; medição real pós-call para trace e painel).
3. **Atribuição do limite** (o ponto que você levantou): o retorno passa a
   dizer qual limite bateu —
   - `limite: usuario` — cota da sessão definida no config;
   - `limite: provedor` — 429 (rate limit), 400 `context_length_exceeded` /
     "maximum context length", 402 `insufficient_quota` (crédito).
   Erro de provedor deixa de ser um "Erro HTTP 429" cru.
4. **Alerta visual na sessão**: mensagem de sistema no chat com o tipo
   (`⚠ limite do provedor` / `⚠ limite definido por você`), o uso
   (`38k/40k tokens`, `92%`) e onde ajustar; selo discreto no painel de sessão
   quando o turno termina por limite.
5. **Configurações → Consumo (web)**: seção com teto de contexto por
   perfil/modelo, cota do secundário, uso da sessão (tokens ↑/↓, compactações,
   pico), custo estimado (já existe `token_cost_per_1k` no config) e aviso
   quando o limite é o que está travando.
6. **Painel de sessão**: trocar o par ↑/↓ por algo que explique o orçamento —
   `contexto: 13k fixo + 2k histórico + 2k anexo · 2 compactações`.

### Migração

- Chaves antigas (`max_chars_per_session`, `anexo_max_chars`) continuam aceitas
  e são convertidas por `chars_por_token`, marcadas como legado no painel de
  configs. Ninguém precisa editar o arquivo à mão.
- Providers sem `usage`: a cota cai para chars, com o mesmo comportamento de
  hoje (sem quebrar).

### Testes

- `usage` do secundário debita a cota em tokens; sem `usage`, fallback em chars.
- 429 / 400-context / 402 mapeados para `limite: provedor` com subtipo; cota
  local → `limite: usuario`.
- Config legado (`max_chars_per_session`) convertido e aceito.
- Endpoint de consumo expõe teto/uso para a UI (`/api/config/consumo` ou seção
  do `/api/settings`), com teste de contrato.

## Testes (o que precisa existir antes do merge)

- Unit: `contexto_config()` com config completo, parcial e ausente.
- Unit: `_limite_anexo("local")`/`("nuvem")` e o corte com sufixo informativo.
- Unit: `/api/chat` corta o `file_text` no orçamento do perfil ativo.
- Unit: `_compact_history` respeita `max_chars`/`keep_last` e não toca no
  histórico original.
- Integração: turno com histórico acima do orçamento no perfil local não envia
  mais que `history_max_chars` (medir somando `content` das mensagens).
- Manual: perfil local, anexo de 12k + 10 turnos; conferir no trace o
  `context_peak_chars` e perguntar "repita sua persona" para validar que o
  system prompt sobreviveu.

## Riscos

- Compactar cedo demais no local pode apagar detalhe que o modelo pequeno
  precisa para a task. Mitigação: `keep_last` generoso e orçamento que só age
  quando estoura.
- Mudança de comportamento em CLI/TUI sem aviso. Mitigação: entrar junto com a
  nota em `docs/decisoes.md` e defaults que não mudam nada para quem já está
  abaixo do orçamento.
- O sufixo de truncamento consome contexto; manter curto.
- Conversão token→char é estimativa (3 chars/token é conservador, mas não exato):
  se ficar otimista, o Ollama trunca por conta própria. Mitigação: mandar
  `num_ctx` e acompanhar `context_peak_chars` no trace.
- Subir `num_ctx` no perfil local consome RAM/VRAM; deixar configurável e
  documentar o custo em vez de fixar um valor alto.

## Decisões (respondidas em 2026-11-05)

1. **Teto por perfil e por modelo, em tokens.** Medição: "oi" ≈ 13k tokens de
   entrada (system + schema). Default local **32k** (16k é o piso, sobra pouca
   folga) e nuvem **128k**; override por modelo no `ciel_config.json` e, na
   versão web, no painel de configurações. O código converte para chars com
   `chars_por_token` (3) só onde ainda não mede tokens.
2. **Anexo separado do orçamento do histórico.** No perfil local o turno carrega
   só a prévia; o conteúdo completo fica em disco e quem lê é o secundário. Se
   precisar de detalhe, o orquestrador pesquisa (na resposta do secundário, no
   próprio arquivo por trecho, ou via tools) — não recarrega tudo.
3. **Truncar, não recusar.** O modelo pode dizer que leu uma parte e perguntar
   qual trecho interessa; "análise completa" é caso de capacidade e cai no
   secundário (local) ou no orquestrador grande (nuvem).
4. **Limpeza**: a suposição de que apagar a sessão apaga os arquivos vale só
   para cache de URL. Fonte enviada, `secondary_response_*.md` e projeto gerado
   ficam (tabela na Parte 2). Proposta: uploads por sessão saem com ela; fonte
   enviada sai com a fonte (se não for global); `secondary_response_*` passa a
   ter sufixo de sessão e entra na limpeza; projeto gerado nunca é apagado.
5. **Prévia do início** (~2.000 chars): resumo, sumário e introdução ficam nas
   primeiras páginas — mesma lógica das fontes. Sem OCR por enquanto: arquivo
   sem texto extraível avisa o usuário e mantém o caminho; não injeta bytes.
   Hoje o `_inject_files` do secundário leria binário — a leitura por tipo
   (item 3 da Parte 2) resolve com aviso em vez de lixo.
6. **Medição em tokens de verdade** (Parte 3): trocar as cotas/cortes em chars
   por tokens reais (`usage` do provedor), com estimativa `chars/3` só na
   admissão pré-call; e separar **limite do usuário** de **limite do provedor**
   na mensagem, no alerta da sessão e na tela de configurações → Consumo.


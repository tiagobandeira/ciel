# Knowledge Sources — Roadmap e Specs

Sistema de gerenciamento de fontes do Agent CLI.
Inspirado no NotebookLM: fontes persistentes + recuperação seletiva + síntese contextual.

---

## Status atual (funcionando)

- [x] `knowledge/db.py` — schema SQLite + FTS5 com triggers de sincronização
- [x] `knowledge/ingest.py` — extração PDF/TXT/MD, chunking por parágrafos com overlap
- [x] `knowledge/retriever.py` — busca FTS5, escopo por agente/sessão/branch, formato pronto pro contexto
- [x] `tools/search_knowledge.py` — tool do agente para buscar nas fontes
- [x] `tools/list_sources.py` — tool do agente para listar fontes disponíveis
- [x] `tools/read_source.py` — tool do agente para ler fonte completa por ID
- [x] `/source <arquivo>` — indexa arquivo na sessão atual
- [x] `/source --global <arquivo>` — indexa como fonte compartilhada do agente
- [x] `/source --listar` — lista fontes com IDs e resumos
- [x] `/source --remover <id>` — remove fonte pelo ID (com validação de agente)
- [x] `/source --limpar-orfas` — remove fontes de sessões já deletadas
- [x] Cascade automático — deletar sessão remove suas fontes do knowledge.db
- [x] Branch herda fontes do pai — `get_session_chain()` percorre ancestrais
- [x] `agent_id` e `session_id` injetados via interceptação no `run_agent()` (não via modelo)

---

## O que falta implementar

### P1 — Qualidade de busca

- [ ] **`expand_query()` automático antes do FTS5**

  Hoje o agente manda a query direto pro FTS5. Queries muito técnicas ou longas
  não batem nos chunks. A expansão resolve:

  ```
  query do usuário
       ↓
  LLM extrai palavras-chave simples   ← chamada extra barata
       ↓
  FTS5 com termos expandidos
       ↓
  chunks mais relevantes
  ```

  Implementar em `retriever.py` como chamada opcional ao Ollama antes da busca.
  O agente pode fazer isso ele mesmo se o system prompt instruir a sempre
  simplificar a query antes de chamar `search_knowledge`.

- [ ] **Resumo via LLM na ingestão**

  Hoje `_quick_summary()` usa apenas os primeiros parágrafos do texto.
  Substituir por chamada ao modelo local para gerar um resumo real.
  Útil especialmente para PDFs onde os primeiros parágrafos são capa/índice.

  ```python
  # em ingest.py
  def llm_summary(text: str, model: str) -> str:
      # chama Ollama com prompt de resumo
      # fallback para _quick_summary() se falhar
  ```

- [ ] **Extração de tópicos via LLM**

  O campo `topics` em `sources` está sempre vazio (`[]`).
  Preencher via LLM na ingestão melhora o `list_sources` —
  o agente vê os tópicos de cada fonte antes de buscar.

### P2 — Novos formatos

- [ ] **DOCX** — extração via python-docx

### P3 — Otimizações futuras

- [ ] **Embeddings + busca semântica** — substituir ou complementar FTS5
  com vetores (sentence-transformers local). Melhora recall em queries
  sem termos exatos. Adicionar como camada opcional, não substituição.

- [ ] **Reranker** — após FTS5 retornar N chunks, um modelo pequeno reordena
  por relevância real antes de mandar pro contexto.

- [ ] **Chunk adaptativo** — ajustar `CHUNK_SIZE` automaticamente baseado
  no tamanho da janela de contexto do modelo ativo.

---

## Integração com versão server

O sistema é compatível com a versão web — as tools funcionam igual,
só muda de onde vem o `session_id` e `agent_id`:

```
CLI    → injetados via interceptação no run_agent()
Server → vêm do request/usuário autenticado
```

O `ingest()` pode ser chamado diretamente no endpoint de upload:

```python
@app.post("/upload")
def upload_source(file, agent_id, session_id):
    path = salvar_arquivo(file)
    source_id = ingest(path, agent_id, session_id)
    return {"source_id": source_id}
```

Sem necessidade de reescrever nada do `knowledge/` — só adaptar a chamada.
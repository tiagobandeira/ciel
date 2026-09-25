# Roadmap de Testes — Ciel

Estado atual: **667 passed** · cobertura **58.1%** (2088/3592) · meta CI: **60%**

---

## Cobertura por módulo

| Módulo | Stmts | Miss | Cover | |
|---|---|---|---|---|
| `agent_loader.py` | 113 | 2 | 98% | ✅ |
| `agent_loop.py` | 213 | 82 | 62% | 🔶 |
| `auth/manager.py` | 113 | 113 | 0% | ❌ sem testes |
| `history_store.py` | 100 | 4 | 96% | ✅ |
| `knowledge/db.py` | 102 | 44 | 57% | 🔶 |
| `knowledge/ingest.py` | 109 | 42 | 61% | 🔶 |
| `knowledge/ingest_url.py` | 124 | 22 | 82% | ✅ |
| `knowledge/retriever.py` | 66 | 25 | 62% | 🔶 |
| `mcp/adapter.py` | 73 | 60 | 18% | ❌ sem testes |
| `mcp/client.py` | 308 | 239 | 22% | ❌ sem testes |
| `mcp/manager.py` | 200 | 161 | 20% | ❌ sem testes |
| `task_runner.py` | 266 | 88 | 67% | 🔶 |
| `tool_dispatch.py` | 20 | 0 | 100% | ✅ |
| `tools/_ssrf_guard.py` | 33 | 6 | 82% | ✅ |
| `tools/calculator.py` | 21 | 0 | 100% | ✅ |
| `tools/create_temp_tool.py` | 113 | 32 | 72% | 🔶 |
| `tools/create_tool.py` | 127 | 37 | 71% | 🔶 |
| `tools/get_local_datetime.py` | 4 | 2 | 50% | 🔶 |
| `tools/http_request.py` | 21 | 0 | 100% | ✅ |
| `tools/list_directory.py` | 38 | 2 | 95% | ✅ |
| `tools/list_skills.py` | 48 | 43 | 10% | ❌ sem testes |
| `tools/list_sources.py` | 17 | 15 | 12% | ❌ sem testes |
| `tools/mcp_add_server.py` | 28 | 25 | 11% | ❌ sem testes |
| `tools/mcp_list_servers.py` | 28 | 25 | 11% | ❌ sem testes |
| `tools/mcp_remove_server.py` | 10 | 7 | 30% | ❌ sem testes |
| `tools/read_file.py` | 18 | 2 | 89% | ✅ |
| `tools/read_pdf.py` | 20 | 15 | 25% | ❌ sem testes |
| `tools/read_source.py` | 17 | 14 | 18% | ❌ sem testes |
| `tools/read_url.py` | 41 | 37 | 10% | ❌ sem testes |
| `tools/run_script.py` | 22 | 2 | 91% | ✅ |
| `tools/search_knowledge.py` | 7 | 5 | 29% | ❌ sem testes |
| `tools/secondary_model.py` | 439 | 262 | 40% | 🔶 |
| `tools/skill_import.py` | 236 | 31 | 87% | ✅ |
| `tools/web_search_extended.py` | 53 | 1 | 98% | ✅ |
| `tools/write_file.py` | 15 | 2 | 87% | ✅ |
| `tools_registry.py` | 93 | 23 | 75% | 🔶 |
| `trust/` (todos) | 157 | 2 | 99% | ✅ |
| `workspace.py` | 97 | 18 | 81% | ✅ |
| **TOTAL** | **3592** | **1504** | **58.1%** | meta: 60% |

---

## O que falta (priorizado)

### Prioritário — bate o threshold de 60% do CI

#### `tests/test_tools/test_list_skills.py` — a fazer (estimativa: +36 linhas)
Cobre `tools/list_skills.py` (43 miss).

Casos a cobrir:
- `_extract_metadata`: frontmatter YAML com `description` e `mode`
- `_extract_metadata`: fallback via chave `description:` no corpo
- `_extract_metadata`: fallback via primeiro parágrafo após título
- `_extract_metadata`: texto vazio sem erros; truncagem em 120 chars
- `run()`: pasta inexistente → mensagem de erro
- `run()`: pasta vazia → mensagem de vazio
- `run()`: skill com frontmatter listada com mode correto
- `run()`: múltiplas skills ordenadas alfabeticamente
- `run()`: skill sem descrição usa fallback `"sem descrição"`
- `run()`: erro de leitura de arquivo retorna graciosamente

#### `tests/test_tools/test_list_and_read_source.py` — a fazer (estimativa: +23 linhas)
Cobre `tools/list_sources.py` (15 miss) e `tools/read_source.py` (14 miss).

**list_sources:**
- Sem fontes → mensagem de vazio
- Fonte compartilhada (`_shared`) → label "compartilhada"
- Fonte de sessão → label "desta sessão"
- Resumo exibido quando presente
- `session_id` em branco normalizado para `None`
- Exceção de DB → mensagem de erro
- Contagem de fontes no cabeçalho

**read_source:**
- ID inexistente → erro gracioso
- Fonte sem chunks → erro gracioso
- Conteúdo correto com chunks concatenados
- Cabeçalho inclui filename, n_chunks, session_id
- Conteúdo longo truncado em `MAX_CHARS` (6000)
- Exceção de DB → mensagem de erro

#### `tests/test_tools/test_search_and_datetime.py` — a fazer (estimativa: +6 linhas)
Cobre `tools/search_knowledge.py` (5 miss) e `tools/get_local_datetime.py` (2 miss).

**search_knowledge:**
- Retorna resultado da busca
- `session_id` vazio normalizado para `None`
- `top_k=0` corrigido para mínimo 1
- `top_k=999` limitado a máximo 10
- Exceção → mensagem de erro

**get_local_datetime:**
- Retorna dict com chaves `datetime`, `date`, `time`
- Formatos corretos: `YYYY-MM-DD HH:MM:SS`, `YYYY-MM-DD`, `HH:MM:SS`

> **Projeção:** os três arquivos juntos cobrem ~65 linhas → cobertura estimada **60.0%** ✅

---

### Backlog — média complexidade

#### `tools/read_url.py` — 37 miss, 10%
Mock de `requests`. Cobre fetch, timeout, erros HTTP, integração com SSRF guard.

#### `tools/read_pdf.py` — 15 miss, 25%
Mock de `PyPDF2.PdfReader`. Cobre PDF com texto, PDF vazio (escaneado), truncagem, erro de leitura.

#### `tools/mcp_add_server.py` / `mcp_list_servers.py` / `mcp_remove_server.py`
~57 miss combinados. Mock de `mcp.manager`. Ganho de ~50 linhas com poucos casos.

#### `tools/secondary_model.py` — 262 miss, 40%
Já tem base em `test_secondary_and_web.py`. Expandir com mock de chamadas LLM de 40% → 70%+ cobre ~130 linhas.

---

### Backlog — alta complexidade / infra

#### `mcp/` (client, manager, adapter) — ~460 miss
Requerem mock de servidor MCP e protocolo de rede. Priorizar quando MCP estiver estável em produção.

#### `auth/manager.py` — 113 miss, 0%
Requer mock de infra de autenticação (OAuth, tokens).

---

## Como rodar

```bash
# tudo
pytest tests/ -v

# sem Ollama ou rede (rápido)
pytest tests/ -v -m "not slow"

# com cobertura completa
pytest tests/ --cov=. --cov-report=term-missing

# arquivo específico
pytest tests/test_tools/test_list_skills.py -v
```

---

## Estrutura de pastas

```
tests/
├── pytest.ini
├── test_core/
│   ├── test_agent_loader.py
│   ├── test_history_store.py
│   ├── test_ingest_url.py
│   ├── test_knowledge.py
│   ├── test_secondary_and_web.py
│   ├── test_task_guard_extended.py
│   └── test_task_runner.py
├── test_integration/
│   ├── test_agent_loop.py
│   ├── test_skill_import.py
│   └── test_tool_dispatch.py
├── test_security/
│   ├── test_redaction.py
│   ├── test_secrets.py
│   ├── test_ssrf_guard.py
│   ├── test_task_guard.py
│   ├── test_trust.py
│   └── test_workspace.py
└── test_tools/
    ├── test_calculator.py
    ├── test_create_temp_tool.py
    ├── test_create_tool.py
    ├── test_http_request.py
    ├── test_list_directory.py
    ├── test_list_skills.py           ← a fazer
    ├── test_list_and_read_source.py  ← a fazer
    ├── test_read_write_file.py
    ├── test_registry.py
    ├── test_run_script.py
    └── test_search_and_datetime.py   ← a fazer
```
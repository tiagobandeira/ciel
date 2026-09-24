# Roadmap de Testes — Ciel

Estado atual: **238 passed** de 238 testes (execução: `pytest tests/ -v`).

---

## Cobertura atual (o que já existe)

| Pasta | O que cobre |
|---|---|
| `test_tools/test_calculator.py` | Operações básicas, funções matemáticas, modo rad/deg, proteções (MAX_POWER, expressão longa, builtins) |
| `test_tools/test_registry.py` | Metadados de tools (permissions, output_type, interactive), shadow warning, path checks |
| `test_security/test_workspace.py` | Acesso dentro/fora do workspace, path traversal, grants (leitura/escrita/persistência/remoção) |
| `test_security/test_ssrf_guard.py` | Bloqueio de loopback, redes locais, metadata endpoint AWS, schemes inválidos; permissão de domínios públicos |
| `test_security/test_trust.py` | InputVerifier (terminal trusted, fonte desconhecida), wrap_tool_output (marcação EXTERNAL_DATA), SOURCE_REGISTRY |
| `test_security/test_redaction.py` | Redação de API keys (OpenAI, Anthropic, NVIDIA, GitHub, Bearer), connection strings, falsos positivos |
| `test_security/test_secrets.py` | SecretsManager: save/load/delete, múltiplos modelos por provider, chmod 600, persistência, resolve_api_key |
| `test_security/test_task_guard.py` | is_trusted_task_path: paths internos, externos, traversal, .ciel/ interno |
| `test_integration/test_agent_loop.py` | Loop com modelo mockado: resposta direta, tool call, max_steps, on_confirm_tool/path, EXTERNAL_DATA no contexto |
| `test_integration/test_tool_dispatch.py` | filter_unsafe (--safe), needs_confirmation, get_path_checks |
| `test_integration/test_skill_import.py` | _call_secondary: resolução de api_key via secrets, fallback sem chave (1 teste falhando — ver bugs acima) |
| `test_core/test_agent_loader.py` | Parsing dos `.md` de persona, filtragem de tools e servidores MCP, níveis de skill, injeção de formato |
| `test_core/test_task_runner.py` | Carregamento de tasks, construção de prompt, validação de grupos de tools, checkpoint, fila determinística |

---

## O que falta (priorizado)

### Prioridade média — funcionalidades com estado

#### `tests/test_core/test_history_store.py`
Sessões persistentes — garante que salvar/retomar/branchar não perde dados.

Casos a cobrir:
- `save_session` / `load_session`: round-trip do histórico
- Branch herda histórico e sources da sessão pai
- Sessão deletada remove suas sources (não remove fontes `_shared`)
- `list_sessions` retorna sessões ordenadas por data
- `_redact` aplicado ao salvar (não salva chaves em disco)
- Sessão com ID inexistente retorna `None` graciosamente

#### `tests/test_core/test_knowledge.py`
RAG — ingestão e busca por relevância.

Casos a cobrir:
- Ingestão de `.txt`, `.md` e `.pdf` (se pymupdf disponível)
- `search_knowledge` retorna trecho relevante dado query
- Fonte de sessão só visível na sessão correta (não vaza para `_shared`)
- Fonte `--global` visível em sessões diferentes do mesmo agente
- `--remover <id>` remove a fonte e não aparece na busca
- `--limpar-orfas` remove fontes de sessões deletadas

#### `tests/test_core/test_task_guard_extended.py`
Extensão do `test_task_guard.py` existente — casos de borda não cobertos.

Casos a cobrir:
- `find_tasks`: busca por nome parcial, case-insensitive
- `find_tasks`: match exato tem prioridade sobre parcial
- `find_tasks`: diretório inexistente retorna lista vazia
- `find_tasks`: múltiplos resultados retornados em ordem

### Prioridade baixa — cobertura de tools individuais

#### `tests/test_tools/test_read_write_file.py`
- `read_file`: arquivo existente, inexistente, binário (não-UTF-8)
- `write_file`: cria arquivo, sobrescreve, cria diretórios intermediários

#### `tests/test_tools/test_http_request.py`
- Bloqueio via SSRF guard (integração com `_ssrf_guard`)
- Resposta mockada com `requests_mock` ou `unittest.mock`

#### `tests/test_tools/test_list_directory.py`
- Lista arquivos em diretório, ignora ocultos se configurado
- Diretório inexistente retorna erro gracioso

#### `tests/test_tools/test_create_tool.py`
- `_validate`: nome inválido, sem docstring, sem `run()`, shadow de tool permanente
- `_sanitize_code`: remoção de padrões proibidos
- `_extract_requirements`: presença e ausência do bloco REQUIREMENTS
- `_check_permission_coverage`: paths sem cobertura em PERMISSIONS geram aviso
- `run()`: criação bem-sucedida, falha de validação AST

#### `tests/test_tools/test_create_temp_tool.py`
- Mesmos casos de `_validate`, `_sanitize_code`, `_extract_requirements`
- Shadow de tool permanente bloqueia — temp não substitui permanente
- Tool temporária não persiste após encerramento da sessão

#### `tests/test_tools/test_run_script.py`
- Script existente executa e retorna stdout
- Script inexistente retorna erro gracioso
- Arquivo não-`.py` é rejeitado
- Timeout estourado retorna status adequado
- Exit code != 0 propagado corretamente
- Separação entre stdout e stderr

---

## Como rodar

```bash
# tudo
pytest tests/ -v

# só os rápidos (sem Ollama ou rede)
pytest tests/ -v -m "not slow"

# um arquivo específico
pytest tests/test_core/test_task_runner.py -v

# com cobertura (requer pytest-cov)
pytest tests/ --cov=. --cov-report=term-missing
```

---

## Estrutura de pastas sugerida (estado final)

```
tests/
├── pytest.ini
├── test_core/
│   ├── test_agent_loader.py         ← existente
│   ├── test_task_runner.py          ← existente
│   ├── test_history_store.py        ← a fazer
│   ├── test_knowledge.py            ← a fazer
│   └── test_task_guard_extended.py  ← a fazer
├── test_integration/
│   ├── test_agent_loop.py           ← existente
│   ├── test_skill_import.py         ← existente
│   └── test_tool_dispatch.py        ← existente
├── test_security/
│   ├── test_redaction.py            ← existente
│   ├── test_secrets.py              ← existente
│   ├── test_ssrf_guard.py           ← existente
│   ├── test_task_guard.py           ← existente
│   ├── test_trust.py                ← existente
│   └── test_workspace.py            ← existente
└── test_tools/
    ├── test_calculator.py            ← existente
    ├── test_registry.py              ← existente
    ├── test_read_write_file.py       ← a fazer
    ├── test_http_request.py          ← a fazer
    ├── test_list_directory.py        ← a fazer
    ├── test_create_tool.py           ← a fazer
    ├── test_create_temp_tool.py      ← a fazer
    └── test_run_script.py            ← a fazer
```

# Guia de Testes — Ciel

## Comandos principais

```bash
# Roda todos os testes
pytest

# Roda uma pasta específica
pytest tests/test_core/ -v

# Roda um arquivo específico
pytest tests/test_core/test_agent_loader.py -v

# Roda um teste específico
pytest tests/test_core/test_agent_loader.py::TestLoadAgent::test_campos_obrigatorios -v

# Pula testes lentos (Ollama, rede)
pytest -m "not slow"

# Gera relatório de cobertura no terminal
pytest --cov=. --cov-report=term-missing

# Gera relatório de cobertura em HTML
pytest --cov=. --cov-report=html
# → abre htmlcov/index.html no browser
```

---

## Fluxo antes de modificar um módulo

1. Abre `htmlcov/index.html` e localiza o módulo que vai mexer
2. Vê quais linhas estão cobertas (verde) e quais não estão (vermelho)
3. Se a cobertura estiver baixa → escreve o teste antes de modificar
   - O teste documenta o comportamento esperado atual
   - Serve de proteção caso a modificação quebre algo
4. Faz a modificação
5. Roda `pytest` para confirmar que nada quebrou
6. Roda `pytest --cov=. --cov-report=html` para atualizar o relatório

---

## Arquivos e o que ignorar

| Arquivo/Pasta | Repositório |
|---|---|
| `pytest.ini` | ✅ commitar — configuração do projeto |
| `conftest.py` | ✅ commitar — fixtures compartilhadas |
| `.coverage` | ❌ `.gitignore` — artefato gerado localmente |
| `htmlcov/` | ❌ `.gitignore` — artefato gerado localmente |
| `.pytest_cache/` | ❌ `.gitignore` — artefato gerado localmente |

---

## Estrutura de configuração

**`pytest.ini`** (raiz do projeto) — configura o pytest: onde procurar testes, flags padrão, markers.

**`conftest.py`** (raiz do projeto) — fixtures e hooks compartilhados entre todos os testes. Conforme a suite crescer, é aqui que entram fixtures reutilizáveis (workspace temporário, agente mockado, SecretsManager limpo) e hooks como pular testes `slow` se o Ollama não estiver acessível.

---

## Cobertura atual

Ver `docs/ROADMAP_TESTES.md` para o estado completo da suite e o que falta cobrir.

Módulos com cobertura baixa e lógica real a testar (prioridade):

| Módulo | Cobertura |
|---|---|
| `tools/create_tool.py` | 10% |
| `tools/create_temp_tool.py` | 14% |
| `tools/run_script.py` | 23% |
| `history_store.py` | 26% |
| `task_runner.py` | 67% |
| `agent_loop.py` | 61% |

> `cli.py`, `ciel_tui.py` e `server.py` têm cobertura baixa intencionalmente — são interfaces interativas, custo de teste alto e ganho baixo.

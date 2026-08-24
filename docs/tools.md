# Tools — PyAgentCLI

Referência das tools do projeto: quais fazem parte do core, quais vão para
repositório externo e quais ainda precisam ser criadas.

---

## Core — tools essenciais (não remover)

Presentes em todo agente, independente do caso de uso.

| Tool | O que faz |
|---|---|
| `read_file.py` | lê arquivos de texto locais |
| `write_file.py` | escreve/cria arquivos de texto |
| `list_sources.py` | RAG — lista fontes indexadas com IDs |
| `search_knowledge.py` | RAG — busca trechos relevantes por query |
| `read_source.py` | RAG — lê fonte completa por ID |
| `calculator.py` | operações matemáticas básicas |
| `get_local_datetime.py` | data e hora local do sistema |
| `create_tool.py` | o agente cria suas próprias tools em runtime |
| `run_script.py` | executa scripts Python locais (`--safe` pra desabilitar) |
| `secondary_model.py` | delega tarefas complexas a modelo externo via API (requer ciel_config.json) |

---

## Repositório externo — tools específicas

Úteis em casos concretos, mas não fazem parte do core.
Candidatas ao marketplace de tools instaláveis via `install_tool`.

| Tool | Por quê é externa |
|---|---|
| `web_search.py` | depende do DDG, nem sempre necessário |
| `web_search_extended.py` | idem |
| `get_hardware_info.py` | situacional |
| `get_network_info.py` | situacional |

---

## A criar — tools que fecham o core

O que falta para o projeto ficar autossuficiente na maioria dos casos de uso.

### Prioritárias

| Tool | O que faz | Por que é necessária |
|---|---|---|
| `list_directory.py` | lista arquivos de um diretório com filtro por extensão | o agente precisa saber o que existe antes de ler ou indexar |
| `search_files.py` | busca texto dentro de arquivos (grep simples) | complementa o RAG para arquivos ainda não indexados |
| `install_tool.py` | baixa tool do repositório externo via URL ou nome | peça central do marketplace de tools |
| `http_request.py` | GET/POST simples com headers e body | substitui `web_search` para casos de API pura |

### Secundárias

| Tool | O que faz | Observação |
|---|---|---|
| `summarize_file.py` | resume arquivo longo via LLM antes de indexar | melhora o `_quick_summary` do ingest (roadmap de fontes) |
| `env_manager.py` | lê/escreve variáveis de ambiente ou arquivo `.env` | o agente gerenciar configs sem hardcode |
| `clipboard.py` | lê/escreve o clipboard do sistema | fluxo rápido: copia algo, pede pro agente processar |

---

## Core mínimo fechado

Essenciais atuais + as quatro prioritárias acima:

```
read_file         write_file        list_directory    search_files
list_sources      search_knowledge  read_source
calculator        get_local_datetime
create_tool       run_script        install_tool      http_request
```

Com esse conjunto, o agente consegue:
- ler, escrever e buscar em arquivos locais
- consultar base de conhecimento por sessão
- fazer chamadas HTTP para APIs externas
- criar e instalar novas tools em runtime
- realizar cálculos e ter consciência temporal

---

## Como criar uma nova tool

Siga o padrão do `tool_template.md`:

```python
"""Descrição em uma linha do que a tool faz."""

# opcional — libs externas necessárias
REQUIREMENTS = ["requests"]

def run(param: str) -> str:
    """
    param: descrição do parâmetro
    """
    try:
        resultado = ...
        return str(resultado)
    except Exception as e:
        return f"Erro: {e}"
```

Regras:
- `run()` sempre retorna `str`
- trata exceções internamente, nunca propaga
- uma tool, uma responsabilidade
- nome em `snake_case`

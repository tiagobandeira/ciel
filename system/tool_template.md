# Como criar uma Tool para o Agente CLI

Use a tool `create_tool` sempre que o usuário pedir uma nova capacidade
ou quando uma tarefa exigir uma operação que nenhuma tool existente cobre.

---

## Contrato obrigatório

Toda tool é um arquivo `.py` com esta estrutura (na ordem exata):

```
1. módulo-docstring        ← obrigatório, primeira linha
2. REQUIREMENTS = [...]    ← opcional, declara dependências pip
3. imports
4. funções auxiliares
5. def run(...)            ← obrigatório, ponto de entrada do agente
```

### 1. Módulo-docstring
Lida pelo `tools_registry` e exibida no painel do agente. Uma linha, clara.

```python
"""Busca o endereço completo de um CEP via API ViaCEP."""
```

### 2. REQUIREMENTS (opcional)
Declara pacotes externos que a tool precisa. O `create_tool` os instala via
`pip` antes de salvar o arquivo. Use especificadores de versão quando necessário.

```python
REQUIREMENTS = ["requests", "beautifulsoup4>=4.12", "pandas==2.2.0"]
```

- Prefira a stdlib quando possível (`urllib`, `csv`, `json`, `pathlib`…)
- Só declare o que a tool realmente importa — não inclua pacotes já disponíveis

### 3. Função `run()`
Ponto de entrada chamado pelo agente. Deve:
- Aceitar apenas tipos simples (`str`, `int`, `float`, `bool`, `list`)
- **Sempre retornar `str`** — resultado, confirmação ou mensagem de erro
- Nunca usar `print()` para comunicar resultado — o retorno é o canal
- Tratar exceções internamente e retornar a mensagem de erro como string

```python
def run(param_a: str, param_b: int = 10) -> str:
    try:
        ...
        return str(resultado)
    except Exception as e:
        return f"Erro: {e}"
```

---

## Template completo

```python
"""<descrição em uma linha do que a tool faz>"""

# Remova REQUIREMENTS se não precisar de libs externas
REQUIREMENTS = ["<pacote1>", "<pacote2>=<versão>"]

from pathlib import Path  # imports depois do REQUIREMENTS


def run(<param1>: str, <param2>: str = "<padrão>") -> str:
    """
    <param1>: <o que é>
    <param2>: <o que é> (padrão: <padrão>)
    """
    try:
        resultado = ...
        return str(resultado)
    except Exception as e:
        return f"Erro: {e}"
```

---

## Regras

| ✅ Faça | ❌ Não faça |
|---|---|
| Módulo-docstring como **primeira** linha | Colocar imports ou REQUIREMENTS antes do docstring |
| `REQUIREMENTS` para libs externas | Importar lib externa sem declará-la em REQUIREMENTS |
| `run()` retorna `str` sempre | `run()` retornar `None` ou lançar exceção |
| Tratar exceções dentro de `run()` | Deixar exceções propagarem pro agente |
| Nome em `snake_case` | Nome com espaços, hífens ou maiúsculas |
| Parâmetros simples (str, int, float, bool, list) | Parâmetros complexos (objetos, funções, dicts aninhados) |
| Stdlib quando suficiente | Dependência externa para algo que `urllib`/`json`/`csv` já fazem |

---

## Exemplos de chamada

### Sem dependências externas (só stdlib)

```json
{
  "tool": "create_tool",
  "args": {
    "tool_name": "buscar_cep",
    "tool_code": "\"\"\"Busca o endereço de um CEP via API ViaCEP.\"\"\"\n\nimport urllib.request\nimport json\n\n\ndef run(cep: str) -> str:\n    \"\"\"\n    cep: CEP a consultar (somente números ou formato 00000-000)\n    \"\"\"\n    cep_limpo = cep.replace('-', '').strip()\n    url = f'https://viacep.com.br/ws/{cep_limpo}/json/'\n    try:\n        with urllib.request.urlopen(url, timeout=5) as resp:\n            data = json.loads(resp.read())\n        if data.get('erro'):\n            return f'CEP {cep} não encontrado.'\n        return f\"{data['logradouro']}, {data['bairro']}, {data['localidade']}-{data['uf']}\"\n    except Exception as e:\n        return f'Erro ao consultar CEP: {e}'\n"
  }
}
```

### Com dependências externas (REQUIREMENTS)

```json
{
  "tool": "create_tool",
  "args": {
    "tool_name": "resumir_pagina",
    "tool_code": "\"\"\"Baixa uma página web e retorna o texto limpo (sem HTML).\"\"\"\n\nREQUIREMENTS = [\"requests\", \"beautifulsoup4\"]\n\nimport requests\nfrom bs4 import BeautifulSoup\n\n\ndef run(url: str) -> str:\n    \"\"\"\n    url: URL da página a baixar\n    \"\"\"\n    try:\n        resp = requests.get(url, timeout=10)\n        resp.raise_for_status()\n        soup = BeautifulSoup(resp.text, 'html.parser')\n        for tag in soup(['script', 'style', 'nav', 'footer']):\n            tag.decompose()\n        texto = ' '.join(soup.get_text().split())\n        return texto[:3000]\n    except Exception as e:\n        return f'Erro: {e}'\n"
  }
}
```

---

## Dicas para o modelo

- **Avalie antes de criar**: se a tarefa pode ser resolvida com tools existentes (`read_file`, `write_file`), use-as.
- **Uma tool, uma responsabilidade**: tools focadas são mais fáceis de reutilizar e depurar.
- **Nomeie pelo verbo + objeto**: `buscar_cep`, `listar_arquivos`, `converter_csv` — não `tool1`.
- **Prefira stdlib**: `urllib.request` funciona sem dependência; só use `requests` se precisar de features extras (sessões, auth, retry).
- **Após criar**: confirme ao usuário e avise que o agente precisa ser reiniciado para carregar a nova tool.

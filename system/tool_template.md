# Como criar uma Tool para o Agente CLI

Use a tool `create_tool` sempre que o usuário pedir uma nova capacidade
ou quando uma tarefa exigir uma operação que nenhuma tool existente cobre.

---

## Contrato obrigatório

Toda tool é um arquivo `.py` com esta estrutura **na ordem exata** —
o validador de `create_tool` rejeita qualquer desvio:

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

Ponto de entrada chamado pelo agente. Regras obrigatórias:

- **Anote os tipos dos parâmetros** — o registry usa `inspect.signature` para
  gerar o schema; sem anotação, o modelo não vê o tipo no prompt
- **Documente parâmetros no docstring de `run()`** no padrão `param: descrição`
  — o registry extrai as descrições linha a linha; sem isso, o schema fica sem `description`
- Aceitar apenas tipos simples (`str`, `int`, `float`, `bool`, `list`)
- **Sempre retornar `str`** — resultado, confirmação ou mensagem de erro
- Nunca usar `print()` para comunicar resultado — o retorno é o canal
- Tratar exceções internamente, nunca propagar

```python
def run(path: str, encoding: str = "utf-8") -> str:
    """
    path: caminho do arquivo a ler
    encoding: encoding do arquivo (padrão utf-8)
    """
    try:
        return Path(path).read_text(encoding=encoding)
    except Exception as e:
        return f"Erro: {e}"
```

**Schema gerado pelo registry para o exemplo acima:**
```json
{
  "name": "ler_arquivo",
  "parameters": [
    {"name": "path",     "type": "str",                        "description": "caminho do arquivo a ler"},
    {"name": "encoding", "type": "str", "default": "'utf-8'", "description": "encoding do arquivo (padrão utf-8)"}
  ]
}
```

> **Atenção:** aliases de compatibilidade retroativa devem usar `**kwargs`,
> não parâmetros explícitos. Parâmetros em `**kwargs` são ignorados pelo
> registry e não aparecem no schema — use isso intencionalmente quando
> quiser ocultar um parâmetro do modelo.

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
| Anotar tipos em `run()` | Parâmetros sem anotação de tipo |
| Docstring de parâmetros em `run()` no padrão `param: descrição` | Documentar parâmetros só no módulo-docstring |
| `run()` retorna `str` sempre | `run()` retornar `None` ou lançar exceção |
| Tratar exceções dentro de `run()` | Deixar exceções propagarem pro agente |
| Nome em `snake_case` | Nome com espaços, hífens ou maiúsculas |
| Parâmetros simples (str, int, float, bool, list) | Parâmetros complexos (objetos, funções, dicts aninhados) |
| Stdlib quando suficiente | Dependência externa para algo que `urllib`/`json`/`csv` já fazem |
| Aliases em `**kwargs` para compatibilidade retroativa | Parâmetros explícitos que não devem aparecer no schema |

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
- **Schema é o contrato**: o modelo só sabe usar a tool pelo que aparece no schema — tipos e descrições incompletos causam erros de args em runtime.
## flow: notebook_matematica
objetivo: criar um notebook Jupyter em data/user/notebooks/matematica.ipynb sobre o tema pedido
formato: markdown
como_testar: abra data/user/notebooks/matematica.ipynb no Jupyter ou VS Code e execute as células

## task: escopo
fase: Estrutura
tools: create_directory, write_file, read_file, list_directory
objetivo: definir o roteiro matemático do notebook
ações:
- criar a pasta data/user/notebooks [tool: create_directory]
- escrever data/user/notebooks/escopo.md com tema, pré-requisitos, definições e roteiro de células
- listar os exemplos e exercícios que o notebook vai conter
resultado esperado: escopo.md existe e cobre o tema do objetivo geral
checagem: [{"tipo": "arquivo", "path": "data/user/notebooks/escopo.md", "tamanho_min": 150}]

## task: notebook
fase: Notebook
depende_de: escopo
tools: create_directory, write_file, read_file, list_directory, run_script
objetivo: escrever o notebook como JSON nbformat 4 válido, com células markdown e code
ações:
- criar data/user/notebooks/matematica.ipynb com JSON nbformat 4 (metadados + lista cells)
- incluir células markdown explicando definições, teoremas e intuição
- incluir células code com exemplos executáveis e comentários
- incluir pelo menos um exercício e uma célula de conclusão
- garantir que todo o arquivo é JSON válido (sem markdown fora do JSON)
resultado esperado: matematica.ipynb existe, é JSON válido e tem células markdown e code
checagem: [{"tipo": "arquivo", "path": "data/user/notebooks/matematica.ipynb", "contem": "nbformat"}, {"tipo": "arquivo", "path": "data/user/notebooks/matematica.ipynb", "contem": "cells"}]

## task: validar
fase: Verificação
depende_de: notebook
tools: read_file, write_file, list_directory, run_script
objetivo: validar o JSON e a estrutura do notebook por código
ações:
- validar data/user/notebooks/matematica.ipynb com um comando Python que carrega o JSON
- confirmar que existe uma lista cells não vazia e pelo menos uma célula code
- se a validação falhar, corrigir o notebook e validar de novo
resultado esperado: o comando de validação retorna 0
checagem: {"tipo": "comando", "cmd": ["python", "-c", "import json; p='data/user/notebooks/matematica.ipynb'; d=json.load(open(p, encoding='utf-8')); cells=d.get('cells') or []; assert cells, 'sem cells'; assert any(c.get('cell_type')=='code' for c in cells), 'sem code'; print('ok')"], "cwd": ".", "esperado": 0, "timeout": 30}

## flow: paralelo_demo
objetivo: testar subagentes paralelos read-only

## task: ler-readme
fase: Leitura
parallel: true
tools: read_file
read_only: true
objetivo: ler o README
ações:
- ler README.md [tool: read_file]
resultado esperado: resumo do README

## task: ler-pytest
fase: Leitura
parallel: true
tools: read_file
read_only: true
objetivo: ler o pytest.ini
ações:
- ler pytest.ini [tool: read_file]
resultado esperado: resumo do pytest.ini
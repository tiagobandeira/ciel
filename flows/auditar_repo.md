## flow: auditar_repo
objetivo: auditar um repositório, mapear riscos e produzir um relatório acionável sem alterar o código auditado
formato: markdown
como_testar: leia data/user/auditoria/RELATORIO.md e confira os arquivos/linhas citados

## task: inventariar
fase: Inventário
tools: list_directory, read_file, write_file, run_script
max_steps: 7
objetivo: mapear estrutura, stack, pontos de entrada, dependências e testes
ações:
- listar a raiz e os diretórios principais do repositório indicado no objetivo; se não houver caminho, auditar o workspace atual
- ler README, pyproject/requirements/package.json e os arquivos de entrada
- identificar linguagem, framework, comandos de teste/build e onde está a lógica principal
- escrever data/user/auditoria/INVENTARIO.md com árvore resumida, stack, entradas e comandos
- não alterar nenhum arquivo do repositório auditado
resultado esperado: INVENTARIO.md existe com stack, estrutura e comandos
checagem: [{"tipo": "arquivo", "path": "data/user/auditoria/INVENTARIO.md", "tamanho_min": 200}]

## task: riscos
fase: Riscos
depende_de: inventariar
tools: list_directory, read_file, write_file, run_script
max_steps: 8
objetivo: procurar riscos de segurança, qualidade e manutenção no código
ações:
- procurar segredos/credenciais, eval/exec, shell=True, SQL concatenado, deserialização insegura e permissões amplas
- procurar TODO/FIXME, código morto, dependências sem lock e ausência de testes
- rodar testes/lint existentes quando forem seguros e somente leitura
- escrever data/user/auditoria/RISCOS.md com severidade, arquivo/linha e evidência
- não alterar nenhum arquivo do repositório auditado
resultado esperado: RISCOS.md lista riscos com evidência e severidade
checagem: [{"tipo": "arquivo", "path": "data/user/auditoria/RISCOS.md", "tamanho_min": 200}]

## task: relatorio
fase: Relatório
depende_de: riscos
tools: read_file, write_file, list_directory
max_steps: 5
objetivo: consolidar a auditoria em um relatório curto e priorizado
ações:
- ler INVENTARIO.md e RISCOS.md
- escrever data/user/auditoria/RELATORIO.md com resumo executivo, top 5 riscos e próximos passos
- citar arquivos/linhas e comandos de verificação
resultado esperado: RELATORIO.md tem resumo, prioridades e próximos passos
checagem: [{"tipo": "arquivo", "path": "data/user/auditoria/RELATORIO.md", "tamanho_min": 200}]

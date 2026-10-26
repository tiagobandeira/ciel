## flow: gerar_testes
objetivo: gerar testes reproduzíveis para um módulo ou repositório e executá-los sem alterar o código-fonte
formato: markdown
como_testar: leia data/user/gerar_testes/RESULTADO.md e rode python rodar.py na pasta de saída

## task: mapear
fase: Mapeamento
tools: list_directory, read_file, write_file, run_script
max_steps: 7
objetivo: identificar o alvo, o módulo e o framework de testes
ações:
- localizar o alvo indicado no objetivo; se não houver caminho, usar data/user/bugfix_demo
- ler os arquivos principais e identificar funções/classes públicas, entradas e comportamentos esperados
- verificar se já existe pytest e onde ficam os testes
- escrever data/user/gerar_testes/ALVO.json com alvo, módulo, arquivo de teste e comando
- não alterar o código-fonte do alvo
resultado esperado: ALVO.json existe com alvo, módulo e comando de teste
checagem: [{"tipo": "arquivo", "path": "data/user/gerar_testes/ALVO.json", "tamanho_min": 30}]

## task: escrever
fase: Escrita
depende_de: mapear
tools: read_file, write_file, edit_file, apply_patch, list_directory, run_script
max_steps: 8
objetivo: escrever testes de comportamento claros e independentes
ações:
- criar data/user/gerar_testes/tests/test_gerado.py
- cobrir caminho feliz, limites e pelo menos um caso de erro por função relevante
- usar pytest; não depender de rede, banco ou ordem de execução
- não alterar o código-fonte do alvo
resultado esperado: test_gerado.py existe e cobre os comportamentos principais
checagem: [{"tipo": "arquivo", "path": "data/user/gerar_testes/tests/test_gerado.py", "tamanho_min": 100}]

## task: rodar
fase: Execução
depende_de: escrever
tools: read_file, write_file, edit_file, apply_patch, list_directory, run_script
max_steps: 8
objetivo: executar os testes, corrigir os testes e registrar o resultado
ações:
- escrever data/user/gerar_testes/rodar.py que lê ALVO.json, adiciona o alvo ao sys.path e roda pytest em tests/test_gerado.py
- rodar rodar.py [tool: run_script]
- se um teste falhar por bug do teste, corrigir o teste; se for bug real do código, registrar no RESULTADO.md sem alterar o fonte
- escrever data/user/gerar_testes/RESULTADO.md com comando, saída e limitações
resultado esperado: rodar.py passa e RESULTADO.md registra o resultado
checagem: [{"tipo": "arquivo", "path": "data/user/gerar_testes/rodar.py", "tamanho_min": 80}, {"tipo": "comando", "cmd": ["python", "rodar.py"], "cwd": "data/user/gerar_testes", "esperado": 0, "timeout": 60}, {"tipo": "arquivo", "path": "data/user/gerar_testes/RESULTADO.md", "tamanho_min": 80}]

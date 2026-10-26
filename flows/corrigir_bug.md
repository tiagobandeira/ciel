## flow: corrigir_bug
objetivo: corrigir uma falha reproduzível com correção mínima e check
formato: markdown
como_testar: leia data/user/corrigir_bug/VERIFICACAO.md e rode python verificar.py na pasta de saída

## task: preparar
fase: Preparação
tools: copy_template, write_file, read_file, list_directory
max_steps: 6
objetivo: identificar o projeto-alvo e preparar o runner de verificação
ações:
- copiar o template corrigir_bug para data/user/corrigir_bug [tool: copy_template]
- ler o objetivo: se citar projeto e comando de teste, usar; senão usar data/user/bugfix_demo e python -m pytest -q
- escrever data/user/corrigir_bug/ALVO.json com projeto, comando, cwd e arquivo afetado (se conhecido)
- não alterar o código do projeto nesta task
resultado esperado: ALVO.json e verificar.py existem na pasta de saída
checagem: [{"tipo": "arquivo", "path": "data/user/corrigir_bug/ALVO.json", "tamanho_min": 40}, {"tipo": "arquivo", "path": "data/user/corrigir_bug/verificar.py", "tamanho_min": 100}]

## task: diagnosticar
fase: Diagnóstico
depende_de: preparar
tools: read_file, list_directory, write_file, run_script
max_steps: 8
objetivo: reproduzir a falha e registrar a causa sem alterar o código
ações:
- ler data/user/corrigir_bug/ALVO.json
- rodar data/user/corrigir_bug/verificar.py para reproduzir a falha [tool: run_script]
- ler o arquivo afetado e identificar a causa raiz
- escrever data/user/corrigir_bug/DIAGNOSTICO.md com causa, arquivo e correção mínima proposta
- não editar o código do projeto nesta task
resultado esperado: DIAGNOSTICO.md aponta a causa e a correção mínima
checagem: [{"tipo": "arquivo", "path": "data/user/corrigir_bug/DIAGNOSTICO.md", "tamanho_min": 100}]

## task: corrigir
fase: Correção
depende_de: diagnosticar
tools: read_file, write_file, edit_file, apply_patch, list_directory, run_script
max_steps: 9
objetivo: aplicar a correção mínima no projeto-alvo e fazer o teste passar
ações:
- ler data/user/corrigir_bug/ALVO.json e DIAGNOSTICO.md
- aplicar a menor edição possível no arquivo afetado; não alterar os testes
- rodar data/user/corrigir_bug/verificar.py [tool: run_script]
- não alterar outros arquivos sem necessidade
resultado esperado: a correção é mínima e o runner do projeto passa
checagem: [{"tipo": "comando", "cmd": ["python", "verificar.py"], "cwd": "data/user/corrigir_bug", "esperado": 0, "timeout": 120}]

## task: verificar
fase: Verificação
depende_de: corrigir
tools: read_file, write_file, list_directory, run_script
max_steps: 6
objetivo: confirmar a correção e registrar como reproduzir
ações:
- rodar data/user/corrigir_bug/verificar.py [tool: run_script]
- escrever data/user/corrigir_bug/VERIFICACAO.md com o que foi alterado, saída do teste e comando de reprodução
resultado esperado: VERIFICACAO.md existe e o runner passa
checagem: [{"tipo": "arquivo", "path": "data/user/corrigir_bug/VERIFICACAO.md", "tamanho_min": 80}, {"tipo": "comando", "cmd": ["python", "verificar.py"], "cwd": "data/user/corrigir_bug", "esperado": 0, "timeout": 120}]

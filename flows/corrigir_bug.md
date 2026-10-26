## flow: corrigir_bug
objetivo: corrigir uma falha reproduzível com correção mínima e check
formato: markdown
como_testar: leia data/user/corrigir_bug/VERIFICACAO.md e rode python verificar.py na pasta de saída

## task: preparar
fase: Preparação
tools: copy_template, read_file, edit_file
max_steps: 4
objetivo: preparar o ALVO e o runner de verificação
ações:
- copiar o template corrigir_bug para data/user/corrigir_bug com overwrite=true (inclui ALVO.json e verificar.py) [tool: copy_template]
- ler o objetivo; se citar outro projeto, comando, cwd ou arquivo, atualizar ALVO.json com edit_file
- se não citar nada, manter o ALVO default do template (demo)
- não listar a raiz inteira nem data/user; o template já traz o alvo default
- não alterar o código do projeto nesta task
resultado esperado: ALVO.json e verificar.py existem na pasta de saída
checagem: [{"tipo": "arquivo", "path": "data/user/corrigir_bug/ALVO.json", "tamanho_min": 40}, {"tipo": "arquivo", "path": "data/user/corrigir_bug/verificar.py", "tamanho_min": 100}]

## task: diagnosticar
fase: Diagnóstico
depende_de: preparar
tools: read_file, write_file, run_script
max_steps: 6
objetivo: reproduzir a falha e registrar a causa sem alterar o código
ações:
- ler data/user/corrigir_bug/ALVO.json
- rodar data/user/corrigir_bug/verificar.py uma vez para reproduzir a falha [tool: run_script]
- ler apenas o arquivo indicado em ALVO.json ("arquivo"); não listar a raiz, data/user ou venv
- escrever data/user/corrigir_bug/DIAGNOSTICO.md com causa, arquivo e correção mínima proposta
- não editar o código do projeto e não reescrever ALVO.json nesta task
resultado esperado: DIAGNOSTICO.md aponta a causa e a correção mínima
checagem: [{"tipo": "arquivo", "path": "data/user/corrigir_bug/DIAGNOSTICO.md", "tamanho_min": 100}]

## task: corrigir
fase: Correção
depende_de: diagnosticar
tools: read_file, write_file, edit_file, apply_patch, run_script
max_steps: 9
objetivo: aplicar a correção mínima no projeto-alvo e fazer o teste passar
ações:
- ler data/user/corrigir_bug/ALVO.json e DIAGNOSTICO.md
- aplicar a menor edição possível no arquivo indicado em ALVO.json; não alterar os testes
- rodar data/user/corrigir_bug/verificar.py [tool: run_script]
- não listar a raiz nem venv; não alterar outros arquivos sem necessidade
resultado esperado: a correção é mínima e o runner do projeto passa
checagem: [{"tipo": "comando", "cmd": ["python", "verificar.py"], "cwd": "data/user/corrigir_bug", "esperado": 0, "timeout": 120}]

## task: verificar
fase: Verificação
depende_de: corrigir
tools: read_file, write_file, run_script
max_steps: 6
objetivo: confirmar a correção e registrar como reproduzir
ações:
- rodar data/user/corrigir_bug/verificar.py [tool: run_script]
- escrever data/user/corrigir_bug/VERIFICACAO.md com o que foi alterado, saída do teste e comando de reprodução
resultado esperado: VERIFICACAO.md existe e o runner passa
checagem: [{"tipo": "arquivo", "path": "data/user/corrigir_bug/VERIFICACAO.md", "tamanho_min": 80}, {"tipo": "comando", "cmd": ["python", "verificar.py"], "cwd": "data/user/corrigir_bug", "esperado": 0, "timeout": 120}]

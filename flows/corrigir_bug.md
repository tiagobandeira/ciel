## flow: corrigir_bug
objetivo: corrigir o bug que faz data/user/bugfix_demo/test_media.py falhar
formato: markdown
como_testar: cd data/user/bugfix_demo && python -m pytest -q
## task: diagnosticar
fase: Diagnóstico
tools: read_file, list_directory, write_file
objetivo: encontrar a causa da falha sem alterar código
ações:
- ler data/user/bugfix_demo/calc.py [tool: read_file]
- ler data/user/bugfix_demo/test_media.py [tool: read_file]
- escrever data/user/bugfix_demo/BUG.md com causa, arquivo afetado e correção mínima proposta
- não editar calc.py nesta task
resultado esperado: BUG.md existe e aponta a causa correta
checagem: [{"tipo": "arquivo", "path": "data/user/bugfix_demo/BUG.md", "tamanho_min": 80}]
## task: corrigir
fase: Correção
depende_de: diagnosticar
tools: read_file, write_file, edit_file, list_directory
objetivo: aplicar a correção mínima em calc.py
ações:
- reler data/user/bugfix_demo/calc.py [tool: read_file]
- usar edit_file para tratar a lista vazia em media (retornar 0)
- não alterar test_media.py
resultado esperado: media([]) retorna 0 e os demais casos continuam passando
checagem: {"tipo": "comando", "cmd": ["python", "-c", "from calc import media; assert media([]) == 0; assert media([2,4,6]) == 4; print('ok')"], "cwd": "data/user/bugfix_demo", "esperado": 0, "timeout": 30}
## task: verificar
fase: Verificação
depende_de: corrigir
tools: read_file, write_file, list_directory
objetivo: confirmar a correção e registrar o resultado
ações:
- ler data/user/bugfix_demo/calc.py [tool: read_file]
- conferir que a correção é mínima e não quebrou os outros casos
- escrever data/user/bugfix_demo/VERIFICACAO.md com o que foi alterado e como testar
resultado esperado: VERIFICACAO.md existe e a checagem de comportamento passa
checagem: [{"tipo": "arquivo", "path": "data/user/bugfix_demo/VERIFICACAO.md", "tamanho_min": 50}, {"tipo": "comando", "cmd": ["python", "-c", "from calc import media; assert media([]) == 0; print('ok')"], "cwd": "data/user/bugfix_demo", "esperado": 0, "timeout": 30}]

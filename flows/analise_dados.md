## flow: analise_dados
objetivo: analisar um conjunto de dados indicado pelo usuário, gerar dados limpos e um relatório com achados
formato: markdown
como_testar: abra data/user/analise_dados/ANALISE.md e rode python data/user/analise_dados/verificar.py

## task: inspecionar
fase: Inspeção
tools: read_file, list_directory, write_file, edit_file, run_script
max_steps: 6
objetivo: localizar e perfilar o dataset citado no objetivo
ações:
- localizar o arquivo de dados (CSV, JSON ou XLSX) indicado no objetivo; se não houver caminho explícito, procurar em data/user
- escrever data/user/analise_dados/perfil.py que lê o dataset e imprime shape, colunas, tipos, nulos e 5 linhas
- rodar perfil.py [tool: run_script] e salvar a saída em data/user/analise_dados/PERFIL.md
- não alterar o arquivo original
resultado esperado: PERFIL.md existe com shape, colunas, tipos e nulos do dataset
checagem: [{"tipo": "arquivo", "path": "data/user/analise_dados/PERFIL.md", "tamanho_min": 80}, {"tipo": "arquivo", "path": "data/user/analise_dados/perfil.py", "tamanho_min": 50}]

## task: limpar
fase: Preparação
depende_de: inspecionar
tools: read_file, write_file, edit_file, apply_patch, list_directory, run_script
max_steps: 7
objetivo: gerar uma versão limpa do dataset com decisões registradas
ações:
- ler data/user/analise_dados/PERFIL.md
- escrever data/user/analise_dados/limpar.py que remove duplicatas, trata nulos e salva data/user/analise_dados/dados_limpos.csv
- rodar limpar.py [tool: run_script]
- escrever data/user/analise_dados/LIMPEZA.md com as decisões e a contagem antes/depois
resultado esperado: dados_limpos.csv existe e LIMPEZA.md registra as decisões
checagem: [{"tipo": "arquivo", "path": "data/user/analise_dados/dados_limpos.csv", "tamanho_min": 20}, {"tipo": "arquivo", "path": "data/user/analise_dados/LIMPEZA.md", "tamanho_min": 80}]

## task: analisar
fase: Análise
depende_de: limpar
tools: read_file, write_file, edit_file, apply_patch, list_directory, run_script
max_steps: 8
objetivo: produzir uma análise exploratória útil sobre os dados limpos
ações:
- escrever data/user/analise_dados/analisar.py com estatísticas descritivas, top categorias e correlações relevantes
- rodar analisar.py [tool: run_script]
- escrever data/user/analise_dados/ANALISE.md com achados, tabelas e limitações
- não inventar números: use apenas a saída do script
resultado esperado: ANALISE.md tem achados numéricos e limitações
checagem: [{"tipo": "arquivo", "path": "data/user/analise_dados/ANALISE.md", "tamanho_min": 200}, {"tipo": "arquivo", "path": "data/user/analise_dados/analisar.py", "tamanho_min": 100}]

## task: verificar
fase: Verificação
depende_de: analisar
tools: read_file, write_file, list_directory, run_script
max_steps: 6
objetivo: verificar os artefatos e registrar como reproduzir
ações:
- escrever data/user/analise_dados/verificar.py que lê dados_limpos.csv e confere shape e colunas
- rodar verificar.py [tool: run_script]
- escrever data/user/analise_dados/VERIFICACAO.md com o resultado e o comando de reprodução
resultado esperado: verificar.py passa e VERIFICACAO.md existe
checagem: [{"tipo": "arquivo", "path": "data/user/analise_dados/VERIFICACAO.md", "tamanho_min": 80}, {"tipo": "comando", "cmd": ["python", "verificar.py"], "cwd": "data/user/analise_dados", "esperado": 0, "timeout": 30}]

## flow: laboratorio_notebook
objetivo: transformar uma ideia/fonte (PDF, Markdown ou dataset) em um laboratório reproduzível com hipótese, experimento, notebook Colab, execução e relatório
formato: markdown
como_testar: abra data/labs/estudo/laboratorio.ipynb no Jupyter/Colab ou rode python src/experimento.py

## task: preparar
fase: Fonte
tools: create_directory, read_pdf, read_file, write_file, list_directory
max_steps: 8
objetivo: localizar a fonte, extrair o conteúdo e montar o esqueleto do laboratório
ações:
- criar data/labs/estudo, fonte, src, resultados e figuras [tool: create_directory]
- localizar no objetivo o PDF ou Markdown de origem; se for PDF, extrair com read_pdf [tool: read_pdf]; se for Markdown, ler com read_file
- se o caminho estiver fora do workspace e o acesso for negado, NÃO invente uma fonte substituta: escreva data/labs/estudo/FONTE_BLOQUEADA.md explicando que é preciso usar /workspace <pasta> ou copiar o arquivo para data/labs/estudo/fonte/ e encerre
- salvar o texto extraído em data/labs/estudo/fonte/artigo.md
- escrever data/labs/estudo/PLANO.md com pergunta, hipótese inicial, variáveis, dados e experimentos candidatos
- se não houver fonte, registrar a ideia do objetivo como fonte e seguir
resultado esperado: PLANO.md e fonte/artigo.md existem e descrevem a ideia a testar
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/PLANO.md", "tamanho_min": 150}, {"tipo": "arquivo", "path": "data/labs/estudo/fonte/artigo.md", "tamanho_min": 100}]

## task: formalizar
fase: Formalização
depende_de: preparar
tools: read_file, write_file, list_directory
max_steps: 5
objetivo: transformar a ideia em hipótese testável e desenho experimental
ações:
- ler fonte/artigo.md e PLANO.md
- escrever data/labs/estudo/FORMALIZACAO.md com definições, notação, hipótese nula/alternativa (ou pergunta), variáveis, experimento, métrica e critério de falseabilidade
- explicitar o que confirmaria, o que refutaria e o que seria inconclusivo
- sugerir uma formalização curta que possa virar nota/artigo
resultado esperado: FORMALIZACAO.md tem hipótese, desenho, métrica e critério de falseabilidade
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/FORMALIZACAO.md", "tamanho_min": 250}]

## task: implementar_script
fase: Implementação
depende_de: formalizar
tools: create_directory, write_file, edit_file, read_file, list_directory, run_script
max_steps: 8
objetivo: implementar e rodar o experimento em um script enxuto
ações:
- escrever data/labs/estudo/src/experimento.py com o experimento determinístico, parâmetros explícitos, sementes e saída em resultados/ e figuras/
- o script deve ser pequeno e focado: uma hipótese por execução, sem tentar gerar o notebook
- rodar src/experimento.py [tool: run_script] e salvar a saída em resultados/saida_experimento.txt
- salvar resultados numéricos em resultados/resultados.json ou CSV e gráficos em figuras/
resultado esperado: script executou e gerou saída, dados e pelo menos um artefato
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/src/experimento.py", "tamanho_min": 150}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/saida_experimento.txt", "tamanho_min": 40}]

## task: implementar_notebook
fase: Notebook
depende_de: implementar_script
tools: read_file, write_file, list_directory, write_notebook
max_steps: 8
objetivo: montar o notebook Colab e o README a partir dos resultados
ações:
- ler resultados/ e src/experimento.py
- criar data/labs/estudo/laboratorio.ipynb com write_notebook [tool: write_notebook], com células pequenas: hipótese, método, parâmetros, execução, tabela/gráfico e conclusão
- o notebook deve ser compatível com Colab, usar caminhos relativos e não depender do Ciel; se precisar do script, pode carregar resultados/ já gerados
- escrever data/labs/estudo/README.md com como rodar localmente e no Colab
resultado esperado: notebook nbformat 4 e README existem
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/laboratorio.ipynb", "contem": "nbformat"}, {"tipo": "arquivo", "path": "data/labs/estudo/laboratorio.ipynb", "contem": "colab"}, {"tipo": "arquivo", "path": "data/labs/estudo/README.md", "tamanho_min": 80}]

## task: executar
fase: Execução
depende_de: implementar_notebook
tools: read_file, write_file, list_directory, run_script, run_notebook
max_steps: 8
objetivo: executar o notebook e registrar a execução detalhada
ações:
- rodar laboratorio.ipynb com run_notebook, cwd data/labs/estudo e log_path resultados/execucao_notebook.log [tool: run_notebook]
- rodar src/experimento.py novamente se necessário [tool: run_script]
- escrever data/labs/estudo/EXECUCAO.md com comandos, stdout, erros, arquivos gerados e leitura dos resultados
- não inventar saída: copie/parafraseie apenas o que os comandos produziram
resultado esperado: EXECUCAO.md e log do notebook existem
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/EXECUCAO.md", "tamanho_min": 300}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/execucao_notebook.log", "tamanho_min": 40}]

## task: relatorio
fase: Relatório
depende_de: executar
tools: read_file, write_file, edit_file, list_directory
max_steps: 7
objetivo: produzir relatório e nota curta com o que foi aprendido
ações:
- ler FORMALIZACAO.md, EXECUCAO.md, resultados/ e figuras/
- escrever data/labs/estudo/RELATORIO.md com pergunta, método, resultados numéricos, evidências, limitações, o que confirma/refuta e próximos experimentos
- escrever data/labs/estudo/NOTA.md com uma formalização curta: definições, conjectura/hipótese, evidência e possível nota/artigo
- separar claramente evidência de interpretação
resultado esperado: RELATORIO.md e NOTA.md existem e citam os resultados
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/RELATORIO.md", "tamanho_min": 400}, {"tipo": "arquivo", "path": "data/labs/estudo/NOTA.md", "tamanho_min": 200}]

## task: verificar
fase: Verificação
depende_de: relatorio
tools: read_file, write_file, list_directory, run_script, run_notebook
max_steps: 7
objetivo: validar notebook, artefatos e reprodutibilidade
ações:
- validar laboratorio.ipynb como JSON nbformat 4 com um comando Python
- rodar o notebook de novo com run_notebook [tool: run_notebook]
- conferir que resultados/ e figuras/ têm arquivos e que RELATORIO.md cita números reais
- escrever data/labs/estudo/VERIFICACAO.md com comandos, resultados e como reproduzir
resultado esperado: notebook válido, execução sem erro e VERIFICACAO.md existe
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/VERIFICACAO.md", "tamanho_min": 200}, {"tipo": "comando", "cmd": ["python", "-c", "import json; p='data/labs/estudo/laboratorio.ipynb'; d=json.load(open(p, encoding='utf-8')); assert d['nbformat']==4; assert any(c.get('cell_type')=='code' for c in d['cells']); print('ok')"], "cwd": ".", "esperado": 0, "timeout": 30}]

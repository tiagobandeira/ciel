## flow: laboratorio_notebook
objetivo: transformar uma ideia/fonte (PDF, Markdown ou dataset) em um laboratório reproduzível com hipótese, experimento, notebook Colab, execução e relatório
formato: markdown
como_testar: abra data/labs/estudo/laboratorio.ipynb no Jupyter/Colab ou rode python src/experimento.py

## task: preparar
fase: Fonte
tools: prepare_lab, read_pdf, read_file, write_file
max_steps: 6
objetivo: criar um lab limpo, extrair a fonte e escrever o plano
ações:
- preparar data/labs/estudo com prepare_lab [tool: prepare_lab]; isso arquiva o lab anterior e evita herdar arquivos velhos
- ler o PDF do objetivo UMA vez com read_pdf [tool: read_pdf] ou o Markdown com read_file; não explore o workspace antes
- salvar o texto extraído em data/labs/estudo/fonte/artigo.md
- escrever data/labs/estudo/PLANO.md com pergunta, hipótese inicial, variáveis, dados e experimentos candidatos
- se o caminho estiver fora do workspace e o acesso for negado, escreva FONTE_BLOQUEADA.md e encerre; não substitua a fonte
resultado esperado: PLANO.md e fonte/artigo.md existem e descrevem a ideia a testar
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/PLANO.md", "tamanho_min": 150}, {"tipo": "arquivo", "path": "data/labs/estudo/fonte/artigo.md", "tamanho_min": 100}]

## task: formalizar
fase: Formalização
depende_de: preparar
tools: read_file, write_file
max_steps: 4
objetivo: transformar a ideia em hipótese testável e desenho experimental
ações:
- ler fonte/artigo.md e PLANO.md
- ignorar FORMALIZACAO.md antiga; sobrescrever com write_file
- escrever data/labs/estudo/FORMALIZACAO.md com definições, notação, hipótese, variáveis, experimento, métrica e critério de falseabilidade
- explicitar o que confirmaria, o que refutaria e o que seria inconclusivo
resultado esperado: FORMALIZACAO.md tem hipótese, desenho, métrica e critério de falseabilidade
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/FORMALIZACAO.md", "tamanho_min": 250}]

## task: implementar_script
fase: Implementação
depende_de: formalizar
tools: read_file, write_file, run_script
max_steps: 6
objetivo: escrever e rodar exatamente src/experimento.py, sem explorar o workspace
ações:
- ler SOMENTE data/labs/estudo/FORMALIZACAO.md; não use list_directory e não leia o artigo inteiro
- escrever exatamente data/labs/estudo/src/experimento.py com write_file; não crie explora_definicao.py, não use edit_file
- o script deve ser pequeno e focado: uma hipótese, parâmetros explícitos, semente e saída em resultados/ e figuras/
- rodar data/labs/estudo/src/experimento.py logo após escrever [tool: run_script]
- salvar a saída em resultados/saida_experimento.txt e resultados numéricos em resultados/resultados.json
resultado esperado: src/experimento.py executou e gerou saída/resultados
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/src/experimento.py", "tamanho_min": 150}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/saida_experimento.txt", "tamanho_min": 40}]

## task: implementar_notebook
fase: Notebook
depende_de: implementar_script
tools: read_file, write_file, write_notebook
max_steps: 6
objetivo: montar o notebook Colab e o README a partir dos resultados
ações:
- ler somente resultados/saida_experimento.txt e resultados/resultados.json; não use list_directory
- ignorar laboratorio.ipynb antigo; sobrescrever
- criar data/labs/estudo/laboratorio.ipynb com write_notebook [tool: write_notebook], com células pequenas: hipótese, método, parâmetros, execução, tabela/gráfico e conclusão
- o notebook deve ser compatível com Colab, usar caminhos relativos e não depender do Ciel; pode carregar resultados/ já gerados
- escrever data/labs/estudo/README.md com como rodar localmente e no Colab
resultado esperado: notebook nbformat 4 e README existem
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/laboratorio.ipynb", "contem": "nbformat"}, {"tipo": "arquivo", "path": "data/labs/estudo/laboratorio.ipynb", "contem": "colab"}, {"tipo": "arquivo", "path": "data/labs/estudo/README.md", "tamanho_min": 80}]

## task: executar
fase: Execução
depende_de: implementar_notebook
tools: read_file, write_file, write_notebook, run_notebook
max_steps: 8
objetivo: executar o notebook e registrar a execução detalhada
ações:
- rodar laboratorio.ipynb com run_notebook, cwd data/labs/estudo e log_path resultados/execucao_notebook.log [tool: run_notebook]
- se o notebook falhar, corrigir as células com write_notebook [tool: write_notebook] e rodar de novo; não sobrescrever o JSON cru com write_file
- depois da execução, escrever data/labs/estudo/EXECUCAO.md com comandos, stdout, erros, arquivos gerados e leitura dos resultados
- não inventar saída: copie/parafraseie apenas o que os comandos produziram
resultado esperado: EXECUCAO.md e log do notebook existem
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/EXECUCAO.md", "tamanho_min": 300}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/execucao_notebook.log", "tamanho_min": 40}]

## task: relatorio
fase: Relatório
depende_de: executar
tools: read_file, write_file
max_steps: 6
objetivo: produzir relatório e nota curta com o que foi aprendido
ações:
- ler FORMALIZACAO.md, EXECUCAO.md e resultados/resultados.json; não use list_directory
- escrever data/labs/estudo/RELATORIO.md com pergunta, método, resultados numéricos, evidências, limitações, o que confirma/refuta e próximos experimentos
- escrever data/labs/estudo/NOTA.md com uma formalização curta: definições, conjectura/hipótese, evidência e possível nota/artigo
- separar evidência de interpretação
resultado esperado: RELATORIO.md e NOTA.md existem e citam os resultados
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/RELATORIO.md", "tamanho_min": 400}, {"tipo": "arquivo", "path": "data/labs/estudo/NOTA.md", "tamanho_min": 200}]

## task: verificar
fase: Verificação
depende_de: relatorio
tools: read_file, write_file, run_notebook
max_steps: 6
objetivo: validar notebook, artefatos e reprodutibilidade
ações:
- validar laboratorio.ipynb como JSON nbformat 4 e rodar o notebook com run_notebook [tool: run_notebook]
- escrever data/labs/estudo/VERIFICACAO.md com comandos, resultados e como reproduzir
- não reescrever o notebook e não usar list_directory
resultado esperado: notebook válido, execução sem erro e VERIFICACAO.md existe
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/VERIFICACAO.md", "tamanho_min": 200}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/metricas.json", "tamanho_min": 40}, {"tipo": "comando", "cmd": ["python", "-c", "import json; p='data/labs/estudo/laboratorio.ipynb'; d=json.load(open(p, encoding='utf-8')); assert d['nbformat']==4; code=[c for c in d['cells'] if c.get('cell_type')=='code']; assert code; assert any(c.get('outputs') for c in code), 'sem outputs'; print('ok')"], "cwd": ".", "esperado": 0, "timeout": 30}]

## flow: laboratorio_notebook
objetivo: transformar uma ideia/fonte (PDF, Markdown ou dataset) em um laboratório reproduzível com hipótese, experimento, notebook Colab, execução e relatório
revisao: false
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
max_steps: 6
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
max_steps: 9
objetivo: escrever e rodar exatamente src/experimento.py, sem explorar o workspace
ações:
- ler SOMENTE data/labs/estudo/FORMALIZACAO.md UMA vez; não leia PLANO.md, não use list_directory e não leia o artigo inteiro
- escrever exatamente data/labs/estudo/src/experimento.py com write_file; não crie explora_definicao.py, não use edit_file e não verifique se o arquivo existe
- o script deve ser pequeno e focado: uma hipótese, parâmetros explícitos, semente e saída em resultados/ e figuras/
- rodar data/labs/estudo/src/experimento.py logo após escrever [tool: run_script]; não releia o script
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
max_steps: 9
objetivo: produzir relatório e nota curta com o que foi aprendido
ações:
- ler FORMALIZACAO.md, EXECUCAO.md e resultados/saida_experimento.txt; resultados/resultados.json é opcional
- não use list_directory e não invente números: use a saída do experimento e o log do notebook
- escrever data/labs/estudo/RELATORIO.md com pergunta, método, resultados numéricos, evidências, limitações, o que confirma/refuta e próximos experimentos
- escrever data/labs/estudo/NOTA.md com uma formalização curta: definições, conjectura/hipótese, evidência e possível nota/artigo
- separar evidência de interpretação
resultado esperado: RELATORIO.md e NOTA.md existem e citam os resultados
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/RELATORIO.md", "tamanho_min": 400}, {"tipo": "arquivo", "path": "data/labs/estudo/NOTA.md", "tamanho_min": 200}]

## task: auditar
fase: Verificação
depende_de: relatorio
tools: read_file, write_file, run_script
max_steps: 6
objetivo: escrever e rodar um script pequeno de auditoria de evidência
ações:
- ler NOTA.md, RELATORIO.md e resultados/saida_experimento.txt; leia no máximo 6.000 caracteres por arquivo e não use list_directory
- extrair de 3 a 4 afirmações verificáveis e escrever data/labs/estudo/verificacao/contraexemplos.py
- o script deve testar cada afirmação com aritmética exata, casos de borda e uma faixa pequena determinística; aleatoriedade só com semente fixa
- rodar o script [tool: run_script] e salvar data/labs/estudo/resultados/verificacao.json com status: suportado, contraexemplo, inconclusivo ou erro
- NÃO é um debate e não há recompensa por refutar: refutação sem saída de script é proibida; se não der para testar mecanicamente, use inconclusivo
- falha lógica só pode ser registrada com trecho exato da prova e o passo questionado; sem encenação e sem acusação
- não escrever VERIFICACAO.md aqui; isso é a próxima task
resultado esperado: script executado e verificacao.json com status
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/verificacao/contraexemplos.py", "tamanho_min": 150}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/verificacao.json", "tamanho_min": 40}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/saida_experimento.txt", "tamanho_min": 40}, {"tipo": "comando", "cmd": ["python", "data/labs/estudo/verificacao/contraexemplos.py"], "cwd": ".", "esperado": 0, "timeout": 120}]

## task: verificar
fase: Verificação
depende_de: auditar
tools: read_file, write_file
max_steps: 4
objetivo: consolidar a auditoria em VERIFICACAO.md, sem reexecutar nada
ações:
- ler resultados/verificacao.json
- escrever data/labs/estudo/VERIFICACAO.md com tabela: afirmação, método, comando, saída, status e limitações
- registrar explicitamente o que ficou inconclusivo e por quê
- não rodar notebook, não rodar script de novo e não usar list_directory
resultado esperado: VERIFICACAO.md existe e cita o JSON de status
checagem: [{"tipo": "arquivo", "path": "data/labs/estudo/VERIFICACAO.md", "tamanho_min": 250}, {"tipo": "arquivo", "path": "data/labs/estudo/resultados/verificacao.json", "tamanho_min": 40}]

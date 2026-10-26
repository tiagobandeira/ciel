## flow: artigo_matematica
objetivo: escrever um artigo de matemática em data/user/artigos/artigo.md sobre o tema pedido
formato: markdown
como_testar: abra data/user/artigos/artigo.md e confira definições, teoremas, demonstrações e referências

## task: escopo
fase: Estrutura
tools: create_directory, write_file, read_file, list_directory
objetivo: definir o escopo, as definições e o roteiro do artigo
ações:
- criar a pasta data/user/artigos [tool: create_directory]
- escrever data/user/artigos/escopo.md com tema, público, definições principais e roteiro de seções
- listar os resultados/teoremas que serão apresentados
resultado esperado: escopo.md existe e cobre o tema do objetivo geral
checagem: [{"tipo": "arquivo", "path": "data/user/artigos/escopo.md", "tamanho_min": 200}]

## task: artigo_base
fase: Redação
depende_de: escopo
tools: read_file, write_file, edit_file, apply_patch, list_directory
objetivo: escrever a abertura do artigo (título, resumo, introdução e definições)
ações:
- ler data/user/artigos/escopo.md [tool: read_file]
- escrever data/user/artigos/artigo.md com título, resumo, introdução e definições principais
- usar notação matemática clara e definir todo símbolo antes de usar
- manter esta parte com até ~6.000 caracteres; não tente escrever o artigo inteiro agora
resultado esperado: artigo.md existe com abertura completa e definições
checagem: [{"tipo": "arquivo", "path": "data/user/artigos/artigo.md", "contem": "##"}, {"tipo": "arquivo", "path": "data/user/artigos/artigo.md", "tamanho_min": 800}]

## task: artigo_corpo
fase: Redação
depende_de: artigo_base
tools: read_file, write_file, edit_file, apply_patch, list_directory
objetivo: acrescentar os teoremas, exemplos e discussão matemática
ações:
- ler data/user/artigos/artigo.md [tool: read_file]
- acrescentar ao artigo as seções de teoremas, exemplos e discussão (append)
- incluir pelo menos um teorema com demonstração ou justificativa
- manter esta parte com até ~8.000 caracteres
resultado esperado: artigo.md tem corpo matemático com teoremas e exemplos
checagem: [{"tipo": "arquivo", "path": "data/user/artigos/artigo.md", "contem": "##"}, {"tipo": "arquivo", "path": "data/user/artigos/artigo.md", "tamanho_min": 2500}]

## task: artigo_final
fase: Redação
depende_de: artigo_corpo
tools: read_file, write_file, edit_file, apply_patch, list_directory
objetivo: concluir o artigo com conclusão e referências
ações:
- ler data/user/artigos/artigo.md [tool: read_file]
- acrescentar conclusão, limitações e referências (append)
- revisar a coerência entre as seções já escritas
resultado esperado: artigo.md tem conclusão e referências
checagem: [{"tipo": "arquivo", "path": "data/user/artigos/artigo.md", "contem": "Refer"}, {"tipo": "arquivo", "path": "data/user/artigos/artigo.md", "tamanho_min": 3500}]

## task: revisao
fase: Verificação
depende_de: artigo_final
tools: read_file, write_file, list_directory
objetivo: revisar o artigo contra o escopo escrevendo um relatório, sem editar o artigo
ações:
- ler data/user/artigos/artigo.md [tool: read_file]
- conferir se cada seção do escopo aparece no artigo
- escrever data/user/artigos/revisao.md com 5 bullets: o que está bom, o que falta, riscos, ajustes recomendados e veredito
- NÃO editar artigo.md nesta task; NÃO criar scripts
resultado esperado: revisao.md existe e o artigo cobre o escopo
checagem: [{"tipo": "arquivo", "path": "data/user/artigos/revisao.md", "tamanho_min": 100}, {"tipo": "arquivo", "path": "data/user/artigos/artigo.md", "contem": "##"}]


## flow: landing_page
objetivo: criar uma landing page completa e responsiva em data/user/landing_page
formato: markdown
como_testar: abra data/user/landing_page/index.html no navegador e teste o CTA e o menu mobile

## task: estrutura
fase: Estrutura
tools: create_directory, write_file, read_file, list_directory
objetivo: criar a pasta e os três arquivos base da landing page
ações:
- criar a pasta data/user/landing_page [tool: create_directory]
- criar data/user/landing_page/index.html com estrutura HTML5, link para style.css e script.js
- criar data/user/landing_page/style.css com variáveis de cor e layout base
- criar data/user/landing_page/script.js com um handler simples de menu/CTA
resultado esperado: os três arquivos existem em data/user/landing_page
checagem: [{"tipo": "arquivo", "path": "data/user/landing_page/index.html"}, {"tipo": "arquivo", "path": "data/user/landing_page/style.css"}, {"tipo": "arquivo", "path": "data/user/landing_page/script.js"}]

## task: conteudo
fase: Conteúdo
depende_de: estrutura
agente: frontend
tools: read_file, write_file, list_directory
objetivo: preencher a landing page com hero, prova social, features e CTA
ações:
- escrever o hero com headline, subheadline e botão de CTA
- adicionar uma seção de features com 3 benefícios concretos
- adicionar uma seção de depoimento/prova social
- estilizar tudo em style.css com layout responsivo (mobile e desktop)
- implementar no script.js a interação do menu mobile e do CTA
resultado esperado: index.html tem hero, features e CTA; style.css cobre responsivo
checagem: [{"tipo": "arquivo", "path": "data/user/landing_page/index.html", "contem": "style.css"}, {"tipo": "arquivo", "path": "data/user/landing_page/index.html", "contem": "cta"}, {"tipo": "arquivo", "path": "data/user/landing_page/style.css", "tamanho_min": 200}]

## task: conferir
fase: Verificação
depende_de: conteudo
tools: read_file, list_directory
objetivo: listar os arquivos e confirmar que a página está completa
ações:
- listar data/user/landing_page [tool: list_directory]
- conferir que index.html referencia style.css e script.js
- conferir que não há placeholders óbvios (lorem ipsum, TODO)
resultado esperado: a listagem contém os três arquivos e o HTML está completo
checagem: [{"tipo": "arquivo", "path": "data/user/landing_page/index.html", "contem": "<!DOCTYPE"}, {"tipo": "arquivo", "path": "data/user/landing_page/index.html", "contem": "script.js"}]


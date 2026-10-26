## flow: app_web
objetivo: criar um app web local com interface, persistência e critérios de aceite
formato: markdown
como_testar: abra data/user/app_web/index.html no navegador, crie uma nota, recarregue e confira se ela continua listada

## task: spec
fase: Especificação
tools: create_directory, write_file, read_file, list_directory
pular_se_ok: true
objetivo: transformar a ideia em uma spec pequena e verificável
ações:
- criar a pasta data/user/app_web [tool: create_directory]
- escrever data/user/app_web/SPEC.md com: objetivo, requisitos, não-objetivos e critérios de aceite
- limitar o escopo: app local, um usuário, sem backend/login/sync
- listar os critérios de aceite que as próximas tasks devem cumprir
resultado esperado: SPEC.md existe, tem escopo e critérios de aceite
checagem: [{"tipo": "arquivo", "path": "data/user/app_web/SPEC.md", "contem": "aceit"}, {"tipo": "arquivo", "path": "data/user/app_web/SPEC.md", "tamanho_min": 300}]

## task: estrutura
fase: Estrutura
depende_de: spec
tools: copy_template, read_file, list_directory
pular_se_ok: true
objetivo: criar os arquivos base do app a partir do template
ações:
- copiar o template app_web para data/user/app_web (template="app_web", dest="data/user/app_web") [tool: copy_template]
- conferir index.html, style.css e app.js
resultado esperado: os três arquivos base existem em data/user/app_web
checagem: [{"tipo": "arquivo", "path": "data/user/app_web/index.html"}, {"tipo": "arquivo", "path": "data/user/app_web/style.css"}, {"tipo": "arquivo", "path": "data/user/app_web/app.js"}]

## task: editor
fase: Implementação
depende_de: estrutura
agente: frontend
tools: read_file, write_file, edit_file, apply_patch, list_directory
objetivo: implementar criar, editar, salvar, listar, abrir e excluir notas
ações:
- implementar em app.js o estado das notas e a persistência em localStorage
- implementar criar nota, editar título/conteúdo, salvar e excluir (função excluirNota)
- renderizar a lista de notas no menu e abrir a nota selecionada
- manter tudo no navegador; não usar backend
resultado esperado: o app salva, recarrega e exclui notas do localStorage
checagem: [{"tipo": "arquivo", "path": "data/user/app_web/app.js", "contem": "localStorage"}, {"tipo": "arquivo", "path": "data/user/app_web/app.js", "contem": "excluir"}, {"tipo": "arquivo", "path": "data/user/app_web/index.html", "contem": "app.js"}]

## task: preview
fase: Implementação
depende_de: editor
tools: read_file, write_file, edit_file, apply_patch, list_directory
objetivo: adicionar preview de Markdown e acabamento da interface
ações:
- implementar um preview simples de Markdown (títulos, negrito, listas e código)
- renderizar o Markdown em HTML (innerHTML), não apenas texto puro
- atualizar o preview enquanto o usuário edita
- estilizar o editor, a lista e o preview para ficarem legíveis
- exibir uma mensagem quando não houver notas
resultado esperado: o preview renderiza o Markdown da nota em HTML
checagem: [{"tipo": "arquivo", "path": "data/user/app_web/app.js", "contem": "innerHTML"}, {"tipo": "arquivo", "path": "data/user/app_web/style.css", "tamanho_min": 500}]

## task: verificar
fase: Verificação
depende_de: preview
tools: read_file, write_file, list_directory, run_script
objetivo: validar a estrutura e o comportamento básico do app por código
ações:
- listar data/user/app_web [tool: list_directory]
- verificar se index.html importa style.css e app.js
- verificar se app.js usa localStorage e tem os handlers principais
- escrever um relatório curto em data/user/app_web/VERIFICACAO.md
resultado esperado: VERIFICACAO.md existe e os arquivos estão integrados
checagem: [{"tipo": "arquivo", "path": "data/user/app_web/VERIFICACAO.md", "tamanho_min": 100}, {"tipo": "arquivo", "path": "data/user/app_web/app.js", "contem": "localStorage"}]

## task: publicar
fase: Entrega
depende_de: verificar
tools: start_preview, stop_preview, list_previews, write_file, read_file
objetivo: subir um preview local e documentar como abrir o app
ações:
- iniciar o preview de data/user/app_web na porta 8765 [tool: start_preview]
- escrever data/user/app_web/COMO_RODAR.md com a URL http://127.0.0.1:8765/ e o comando manual
- não alterar index.html, style.css nem app.js nesta task
resultado esperado: o preview responde e COMO_RODAR.md existe
checagem: [{"tipo": "arquivo", "path": "data/user/app_web/COMO_RODAR.md", "tamanho_min": 60}, {"tipo": "http", "url": "http://127.0.0.1:8765/", "esperado": 200}]


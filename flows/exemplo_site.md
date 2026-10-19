## flow: exemplo_site
objetivo: criar um site estático mínimo em data/user/exemplo_multitask e conferir os arquivos
perfil: local
formato: markdown
como_testar: abra data/user/exemplo_multitask/index.html no navegador ou rode `python -m http.server 8000` na pasta

## task: estrutura
fase: estrutura
agente: dev_helper
objetivo: criar os três arquivos base do site
ações:
- criar data/user/exemplo_multitask/index.html com uma página simples que importa style.css e script.js
- criar data/user/exemplo_multitask/style.css com um tema escuro simples e legível
- criar data/user/exemplo_multitask/script.js com uma saudação no console
resultado esperado: os três arquivos existem em data/user/exemplo_multitask

## task: conferir
fase: verificação
depende_de: estrutura
objetivo: listar a pasta e confirmar que os três arquivos existem
ações:
- listar data/user/exemplo_multitask [tool: list_directory]
- confirmar que index.html, style.css e script.js aparecem na listagem
resultado esperado: a listagem contém os três arquivos

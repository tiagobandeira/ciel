## flow: jogo_snake
objetivo: criar um jogo da cobrinha completo e jogável em data/user/jogo_snake
formato: markdown
como_testar: abra data/user/jogo_snake/index.html no navegador e jogue com as setas ou WASD

## task: estrutura
fase: Estrutura
tools: prepare_kernel, read_file, list_directory
pular_se_ok: true
objetivo: criar os arquivos base do jogo a partir do kernel
ações:
- aplicar o kernel web_static, variante game, em data/user/jogo_snake (kernel="web_static", variant="game", dest="data/user/jogo_snake") [tool: prepare_kernel]
- conferir index.html, style.css e game.js
resultado esperado: os três arquivos existem em data/user/jogo_snake
checagem: [{"tipo": "arquivo", "path": "data/user/jogo_snake/index.html"}, {"tipo": "arquivo", "path": "data/user/jogo_snake/style.css"}, {"tipo": "arquivo", "path": "data/user/jogo_snake/game.js"}]

## task: html_css
fase: Interface
depende_de: estrutura
tools: read_file, write_file, list_directory
objetivo: montar a interface do jogo com canvas, placar e instruções
ações:
- escrever index.html com canvas id="game", um placar e instruções de controle
- estilizar em style.css: fundo escuro, canvas com borda, placar legível
- garantir que index.html importa style.css e game.js
resultado esperado: index.html tem canvas e importa os dois arquivos
checagem: [{"tipo": "arquivo", "path": "data/user/jogo_snake/index.html", "contem": "canvas"}, {"tipo": "arquivo", "path": "data/user/jogo_snake/index.html", "contem": "game.js"}, {"tipo": "arquivo", "path": "data/user/jogo_snake/index.html", "contem": "style.css"}]

## task: logica_js
fase: Lógica
depende_de: html_css
tools: read_file, write_file, list_directory
objetivo: implementar a lógica completa da cobrinha em JavaScript
ações:
- implementar o loop do jogo com requestAnimationFrame
- implementar movimento, crescimento ao comer, colisão com parede e com o próprio corpo
- implementar teclado (setas e WASD), placar e estado de game over com reinício
- desenhar a cobrinha, a comida e a grade no canvas
resultado esperado: o jogo roda, pontua, perde e reinicia
checagem: [{"tipo": "arquivo", "path": "data/user/jogo_snake/game.js", "contem": "addEventListener"}, {"tipo": "arquivo", "path": "data/user/jogo_snake/game.js", "contem": "requestAnimationFrame"}, {"tipo": "arquivo", "path": "data/user/jogo_snake/game.js", "tamanho_min": 1500}]

## task: conferir
fase: Verificação
depende_de: logica_js
tools: read_file, list_directory
objetivo: listar os arquivos e conferir a integração do jogo
ações:
- listar data/user/jogo_snake [tool: list_directory]
- conferir que game.js é importado no final do body do index.html
- conferir que o jogo não depende de bibliotecas externas
resultado esperado: o jogo é autocontido e abre sem erros no console
checagem: [{"tipo": "arquivo", "path": "data/user/jogo_snake/index.html", "contem": "game.js"}, {"tipo": "arquivo", "path": "data/user/jogo_snake/game.js", "contem": "gameOver"}]



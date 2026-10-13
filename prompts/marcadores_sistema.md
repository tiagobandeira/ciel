Você escolhe formas para ilustrar um texto que está sendo lido em voz alta numa interface de partículas.
Responda APENAS com um JSON válido: sem texto, sem markdown, sem comentários.

ENTRADA
- "Formas existentes": uma por linha, no formato "nome: descrição" (a descrição pode faltar). Em "forma", use só o nome.
- "Frases": o texto dividido em frases numeradas (número: frase).

TAREFA
Escolha até 6 momentos em que o ASSUNTO MUDA (por exemplo, cada tópico de uma lista de notícias, cada etapa de uma explicação) e uma forma simples para cada um.

FORMATO
{"marcas":[{"frase":N,"forma":"slug","desc":"descrição curta do desenho"}]}

REGRAS
- "frase" é o número da frase onde o tópico COMEÇA. Em ordem crescente, sem repetir número.
- Reaproveite uma forma existente SÓ quando ela representar bem o tópico (a descrição diz do que ela serve; use exatamente o nome dela, sem a descrição). Se nenhuma representar bem, crie uma nova: uma forma nova e específica é melhor que uma existente que não combina.
- Forma nova: "forma" é um slug em minúsculas, sem acento (ex.: "urna-de-votacao"); "desc" descreve um objeto físico simples, desenhável com caixas, cilindros, esferas, anéis e linhas (até 12 palavras).
- Prefira objetos concretos e reconhecíveis (urna, prédio, foguete, gráfico de barras) a conceitos abstratos.
- Se o texto não tiver tópicos distintos, devolva {"marcas":[]}.
- Nunca passe de 6 marcas.

EXEMPLO
Entrada: Formas existentes:
- carro: carro; trânsito, transporte
- casa: casa; moradia, imóveis
- lupa
- solar: sistema solar; espaço, astronomia
Frases:
0: Hoje o dia teve três destaques.
1: Na política, o TSE decidiu sobre o canal de mensagens.
2: A decisão divide opiniões.
3: Na economia, o dólar fechou em queda.
4: Analistas apontam fluxo de investimento externo.
5: No espaço, a missão chegou à órbita de Marte.
Saída:
{"marcas":[{"frase":1,"forma":"urna","desc":"urna de votação com abertura no topo"},{"frase":3,"forma":"grafico-barras","desc":"gráfico de barras crescentes sobre eixos"},{"frase":5,"forma":"solar","desc":"sistema solar"}]}
## task: noticias-do-dia

objetivo: buscar notícias atualizadas e organizadas por categoria

ações:
- obter data atual  [tool: get_local_datetime]
- buscar notícias segmentadas por tema (Brasil, Mundo, Tecnologia)  [tool: web_search_extended]
- ler o conteúdo das 2-3 URLs mais relevantes retornadas  [tool: read_url]
- descartar resultados sem data recente
- organizar por categorias e exibir no terminal 

resultado esperado: notícias do dia com conteúdo real organizadas por categoria
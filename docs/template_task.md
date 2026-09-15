## task: nome-da-task
# obrigatório — identificador em kebab-case, sem espaços
# ex: noticias-do-dia, backup-semanal, resumo-reuniao

objetivo: descrição curta do que a task faz
# obrigatório — uma linha explicando o propósito

ações:
# obrigatório — lista de ações em ordem de execução
# máximo recomendado: 9 ações, sendo até 7 com [tool: nome] definida
# o agente executa em sequência como um inspetor — sem improvisar, sem pular
#
# formato por ação:
#   - descrição em linguagem natural
#   - descrição com tool sugerida  [tool: nome_da_tool]
#
# [tool: nome] é opcional por ação — use quando quiser precisão
# sem [tool:], o agente escolhe a tool mais adequada disponível
#
# exemplos:
# - obter data e hora atual  [tool: get_local_datetime]
# - buscar notícias de tecnologia  [tool: web_search_extended]
# - organizar e exibir os resultados

resultado esperado: o que deve ser entregue ao final
# opcional mas ajuda o agente a saber quando a task está concluída
# ex: lista de notícias organizadas por categoria exibida no terminal

# Nome do Agente
# obrigatório — vira o nome exibido no banner e nos comandos /agente

## Persona
# obrigatório — quem é o agente, especialidade, tom e estilo de resposta
# primeira linha vira a descrição curta na listagem de agentes
# seja específico: modelos menores seguem instruções diretas melhor que descrições longas

## Tools permitidas
# 'todas' → todas as tools do registry ficam disponíveis
# lista de nomes → só as core tools + as listadas ficam disponíveis
#
# core tools (sempre incluídas, não precisa listar):
#   read_file, write_file, list_directory, search_files, calculator,
#   get_local_datetime, web_search_extended, secondary_model, list_skills,
#   run_script, create_tool, install_tool, http_request, temp_log,
#   entrevista_interativa
#
# exemplo de tools extras:
#   get_hardware_info
#   consultar_estoque
#   registrar_pedido

## Servidores MCP
# 'todos'  → todos os servidores conectados ficam visíveis
# 'nenhum' → nenhuma tool MCP disponível
# lista    → só os servidores listados ficam visíveis
#
# exemplo:
#   telegram

## Skills
# opcional — skills vinculadas à persona
# formato: nome-da-skill: obrigatoria | sugerida | opcional
#
#   obrigatoria → aciona secondary_model automaticamente quando a tarefa se encaixar
#   sugerida    → avalia antes de responder se a skill se encaixa
#   opcional    → disponível via /skill ou decisão própria
#
# exemplo:
#   frontend-visual: obrigatoria
#   code-review: sugerida

## Comportamento
# regras de fluxo injetadas no system prompt
# use para: quando usar X, sempre confirmar Y, nunca fazer Z
# seja direto — instruções curtas performam melhor em modelos menores

## Comportamento de segurança
# opcional — regras específicas de segurança do domínio
# exemplo:
#   - Recuse ações destrutivas sem confirmação explícita no mesmo turno
#   - Nunca execute scripts sem path explícito fornecido pelo usuário

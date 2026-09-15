## task: criar_agente

objetivo: guiar o usuário na criação de um novo agente via entrevista progressiva e salvar o arquivo em agents/

ações:
- ler o template de referência para entender a estrutura e os campos disponíveis  [tool: read_file] docs/template_agente.md
- conduzir entrevista base com o usuário: nome do agente, domínio/especialidade, tom de resposta  [tool: entrevista_interativa]
- com base nas respostas, conduzir entrevista sobre tools: precisa de tools extras além das core? se sim, quais  [tool: entrevista_interativa]
- com base nas respostas, conduzir entrevista sobre MCP: precisa acessar algum servidor MCP? se sim, quais  [tool: entrevista_interativa]
- com base nas respostas, conduzir entrevista sobre skills: vai usar skills do secondary_model? se sim, quais e em qual nível (obrigatoria/sugerida/opcional)  [tool: entrevista_interativa]
- conduzir entrevista sobre comportamento: quais regras de fluxo o agente deve seguir? há restrições de segurança específicas?  [tool: entrevista_interativa]
- montar o conteúdo do arquivo .md do agente com base em todas as respostas coletadas, seguindo exatamente a estrutura do template — omitir seções opcionais que não se aplicam
- salvar o arquivo em agents/<nome_do_agente>.md (nome em snake_case, sem espaços)  [tool: write_file]
- informar no message que o agente foi criado com sucesso e o comando para ativá-lo: /agente <nome_do_agente>

resultado esperado: arquivo agents/<nome>.md criado e válido, pronto para ser carregado com /agente

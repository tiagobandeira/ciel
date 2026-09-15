## task: criar_task

objetivo: guiar o usuário na criação de uma nova task via entrevista e salvar o arquivo em tasks/

ações:
- ler o template de referência para entender a estrutura e os campos disponíveis  [tool: read_file] docs/template_task.md
- conduzir entrevista com o usuário: nome da task (em kebab-case) e objetivo — o que ela deve fazer  [tool: entrevista_interativa]
- com base no objetivo informado, sugerir uma lista de ações em ordem lógica usando as tools disponíveis no contexto — respeitar o limite de 9 ações e no máximo 7 com [tool:] definida  [tool: entrevista_interativa]
- perguntar ao usuário se deseja adicionar alguma instrução extra às ações sugeridas ou se aceita como está  [tool: entrevista_interativa]
- conduzir entrevista sobre o resultado esperado: o que deve ser entregue ao final da task  [tool: entrevista_interativa]
- montar o conteúdo do arquivo .md da task com base em todas as respostas e sugestões, seguindo exatamente a estrutura do template — sem comentários no arquivo final
- salvar o arquivo em tasks/<nome-da-task>.md  [tool: write_file]
- informar no message que a task foi criada com sucesso e o comando para executá-la: /task <nome-da-task>

resultado esperado: arquivo tasks/<nome>.md criado e válido, pronto para ser executado com /task

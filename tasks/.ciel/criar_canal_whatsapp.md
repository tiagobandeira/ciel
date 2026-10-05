## task: criar_canal_whatsapp

objetivo: guiar o usuário na configuração do canal WhatsApp via entrevista e salvar em whatsapp_channels.json

ações:
- conduzir entrevista inicial: explicar os dois modos disponíveis (Modo Bot = Ciel responde mensagens em tempo real, como extensão do terminal; MCP = o modelo usa WhatsApp como tool pontual dentro de tasks) e perguntar qual o usuário quer ativar — pode ser um ou os dois  [tool: entrevista_interativa]
- se modo bot foi escolhido: perguntar qual agente vai atender esse número (listar os disponíveis em agents/) e qual o número pessoal do usuário que poderá mandar mensagens (explicar que é o número de quem vai conversar com o agente, não o número do WhatsApp onde o Ciel vai rodar)  [tool: entrevista_interativa]
- perguntar se quer usar a bridge_url padrão (http://127.0.0.1:8765) ou configurar outra  [tool: entrevista_interativa]
- gravar a configuração em whatsapp_channels.json na raiz do projeto usando o script abaixo  [tool: run_script]
- informar no message: configuração salva, próximos passos para parear o bridge e subir o modo bot

resultado esperado: whatsapp_channels.json criado/atualizado na raiz do projeto, pronto para uso com `python ciel.py bot`

---

instrução para a ação de gravar (run_script):
montar e executar o seguinte script Python com os valores coletados na entrevista:

```python
import sys
sys.path.insert(0, '.')
from mcp.whatsapp.channels import configure_interactive

cfg = configure_interactive(
    agent_name='<agente_escolhido>',
    allow_from=['<numero_do_usuario>'],
    bot=<True_se_modo_bot>,
    mcp=<True_se_mcp>,
    bridge_url_override='<bridge_url_se_diferente_do_padrao_ou_None>',
)
print('ok:', cfg)
```

instrução para o message final:
incluir os próximos passos na mensagem de conclusão:
1. instalar e subir o bridge: `git clone https://github.com/lharries/whatsapp-mcp && cd whatsapp-mcp && go run .`
2. configurar o bridge pra enviar eventos pro webhook do Ciel: `WEBHOOK_URL=http://127.0.0.1:8766/webhook`
3. parear escaneando o QR que aparece no terminal do bridge
4. subir o modo bot: `python ciel.py bot`
5. mandar uma mensagem do número configurado na allowlist

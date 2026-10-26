# Tool calls nativos

O Ciel fala tools por JSON em texto (e aceita DSML do DeepSeek). A partir desta
fase, clientes OpenAI-compatible também podem usar **tool calls nativos**,
atrás de uma flag de capability.

## Ativar

No `ciel_config.json`, na entrada do papel/provider:

```json
{
  "roles": {
    "orchestrator": {
      "provider": "nvidia",
      "model": "deepseek-ai/deepseek-v3",
      "native_tools": true
    }
  }
}
```

Também pode ser definido no bloco `secondary` ou no topo do config:

```json
{
  "native_tools": true
}
```

Sem a flag, o comportamento continua exatamente o de antes (JSON/DSML).

## O que já funciona

- envio do schema de tools no formato OpenAI (`tools`);
- `parallel_tool_calls: true`;
- leitura de `message.tool_calls`;
- execução de **leituras independentes em paralelo** em um único step;
- mensagens `assistant.tool_calls` + `tool` no histórico;
- fallback automático para JSON quando a chamada nativa pede escrita.

## Limitações atuais

- Escritas ainda usam o protocolo JSON (uma por step).
- O modelo precisa suportar tool calling nativo; se não suportar, a flag deve
  ficar desligada.
- O caminho nativo não substitui `apply_patch`/`edit_file`; ele só muda o
  transporte da chamada.

## Testes

`tests/test_integration/test_agent_loop_native.py` e
`tests/test_core/test_llm_client.py` cobrem o caminho nativo com clientes
falsos, sem gastar API.

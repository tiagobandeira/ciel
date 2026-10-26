"""Testes do caminho de tool calls nativos (leitura em lote)."""

import json

from agent_loop import run_agent
from llm.client import ChatResult
from tools_registry import tools_schema


AGENT_INFO = {
    "id": "teste",
    "name": "Teste",
    "description": "agente de teste",
    "system_prompt": "Você é um agente de teste.",
    "allowed_tools": None,
    "allowed_mcp_servers": [],
}


class NativeFakeClient:
    native_tools = True

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def chat(self, messages, *, model=None, tools=None, **kwargs):
        self.chamadas.append({
            "messages": list(messages), "model": model, "tools": tools,
        })
        item = self.respostas.pop(0)
        if isinstance(item, ChatResult):
            return item
        return ChatResult(item, tokens_in=3, tokens_out=4)


def _tool_call(call_id, name, args):
    return {
        "id": call_id,
        "type": "function",
        "name": name,
        "arguments": args,
        "arguments_raw": json.dumps(args),
    }


def test_native_parallel_reads_em_um_step():
    def calc(expression: str) -> str:
        return str(eval(expression, {"__builtins__": {}}))

    tools = {
        "calculator": {
            "fn": calc,
            "description": "calcula",
            "permissions": {},
        },
    }
    schema = tools_schema(tools)
    client = NativeFakeClient([
        ChatResult("", tool_calls=[
            _tool_call("c1", "calculator", {"expression": "1+1"}),
            _tool_call("c2", "calculator", {"expression": "2+2"}),
        ]),
        ChatResult(json.dumps({"done": True, "message": "4 e 6"})),
    ])

    result = run_agent(
        "calcule", tools, schema, "m", AGENT_INFO,
        model_client=client,
    )

    assert result.status == "done"
    assert result.tool_calls == 2
    assert result.batch_calls == 1
    assert client.chamadas[0]["tools"] is not None
    second_messages = client.chamadas[1]["messages"]
    assert second_messages[-3]["role"] == "assistant"
    assert second_messages[-3]["tool_calls"][0]["function"]["name"] == "calculator"
    assert second_messages[-2]["role"] == "tool"
    assert second_messages[-2]["tool_call_id"] == "c1"


def test_native_tool_de_escrita_faz_fallback_para_json():
    tools = {
        "write_file": {
            "fn": lambda path, content: "ok",
            "description": "escreve",
            "permissions": {"path": "write"},
        },
    }
    schema = tools_schema(tools)
    client = NativeFakeClient([
        ChatResult("", tool_calls=[
            _tool_call("c1", "write_file", {"path": "a.txt", "content": "x"}),
        ]),
        ChatResult(json.dumps({"done": True, "message": "ok"})),
    ])

    result = run_agent(
        "escreva", tools, schema, "m", AGENT_INFO,
        model_client=client,
    )

    assert result.status == "done"
    assert result.tool_calls == 0
    # segunda chamada já vai sem tools nativas
    assert client.chamadas[1]["tools"] is None

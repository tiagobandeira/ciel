"""
tests/test_integration/test_agent_loop_client.py

Garante que `run_agent(model_client=...)` usa o cliente injetado e que o
caminho padrão (model_client=None) continua idêntico — os testes antigos
que patcham `_call_model` cobrem o default.
"""

import json

import pytest
import requests

from agent_loop import run_agent
from llm.client import ChatResult, LLMError


AGENT_INFO = {
    "id": "teste",
    "name": "Teste",
    "description": "agente de teste",
    "system_prompt": "Você é um agente de teste.",
    "allowed_tools": None,
    "allowed_mcp_servers": [],
}


class FakeClient:
    """Dublê de BaseClient: devolve respostas prontas e registra chamadas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def chat(self, messages, *, model=None, **kwargs):
        self.chamadas.append({"messages": messages, "model": model})
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResult(item, tokens_in=3, tokens_out=4)


def _done(texto: str) -> str:
    return json.dumps({"done": True, "message": texto})


class TestClienteInjetado:
    def test_done_com_cliente_cloud(self):
        client = FakeClient([_done("pronto")])
        result = run_agent(
            "oi", {}, [], "modelo-cloud", AGENT_INFO,
            model_client=client,
        )
        assert result.status == "done"
        assert result.message == "pronto"
        assert (result.tokens_in, result.tokens_out) == (3, 4)
        assert client.chamadas[0]["model"] == "modelo-cloud"

    def test_model_vazio_deixa_cliente_decidir(self):
        client = FakeClient([_done("ok")])
        run_agent("oi", {}, [], "", AGENT_INFO, model_client=client)
        assert client.chamadas[0]["model"] is None

    def test_tool_call_e_depois_done(self):
        chamadas = []

        def echo(text: str) -> str:
            chamadas.append(text)
            return f"eco:{text}"

        tools = {"echo": {"fn": echo, "description": "eco"}}
        client = FakeClient([
            json.dumps({"tool": "echo", "args": {"text": "oi"}}),
            _done("fim"),
        ])
        result = run_agent(
            "use echo", tools, [], "m", AGENT_INFO, model_client=client,
        )

        assert result.status == "done"
        assert chamadas == ["oi"]
        # a segunda chamada viu o resultado da tool no histórico
        mensagens = client.chamadas[1]["messages"]
        assert any("eco:oi" in str(m.get("content")) for m in mensagens)

    def test_erro_de_conexao_vira_status_error(self):
        client = FakeClient([requests.ConnectionError("caiu")])
        erros = []
        result = run_agent(
            "oi", {}, [], "m", AGENT_INFO,
            model_client=client,
            on_error=lambda kind, msg: erros.append((kind, msg)),
        )
        assert result.status == "error"
        assert erros and erros[0][0] == "connection"

    def test_llm_error_vira_status_error(self):
        client = FakeClient([LLMError("sem base_url")])
        result = run_agent("oi", {}, [], "m", AGENT_INFO, model_client=client)
        assert result.status == "error"
        assert "sem base_url" in result.message

    def test_client_que_devolve_tupla_continua_funcionando(self):
        class TuplaClient:
            def chat(self, messages, *, model=None, **kwargs):
                return _done("tupla"), 1, 2

        result = run_agent(
            "oi", {}, [], "m", AGENT_INFO, model_client=TuplaClient(),
        )
        assert result.status == "done"
        assert (result.tokens_in, result.tokens_out) == (1, 2)


class TestContextInjectionSobreviveAoReload:
    def test_reload_nao_perde_injecao(self):
        """create_tool recarrega o registry; o contexto injetado deve ficar."""
        from unittest.mock import patch

        sistemas = []

        class CapturingClient:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, *, model=None, **kwargs):
                sistemas.append(messages[0]["content"])
                self.calls += 1
                if self.calls == 1:
                    return ChatResult(
                        json.dumps({"tool": "create_tool", "args": {}}), 1, 1
                    )
                return ChatResult(_done("ok"), 1, 1)

        def fake_create_tool(**kwargs):
            return "tool criada"

        tools = {
            "create_tool": {
                "fn": fake_create_tool,
                "description": "cria tool",
            }
        }

        with patch("tools_registry.load_tools", return_value=tools), \
             patch("tools_registry.tools_schema", return_value=[]):
            result = run_agent(
                "crie", tools, [], "m", AGENT_INFO,
                model_client=CapturingClient(),
                context_injection="## Contexto do teste\nfase=backend",
                on_confirm_tool=lambda *_: True,
            )

        assert result.status == "done"
        assert len(sistemas) >= 2          # houve reload entre as chamadas
        assert all("Contexto do teste" in s for s in sistemas)

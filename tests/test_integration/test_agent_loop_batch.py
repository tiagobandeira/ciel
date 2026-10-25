"""Testes de lote de leituras e compactação de histórico."""

import json

from agent_loop import (
    _batch_allowed,
    _compact_history,
    _extract_actions,
    _parse_response,
    run_agent,
)
from llm.client import ChatResult


AGENT = {"id": "general", "allowed_tools": None, "system_prompt": "teste"}


def _done():
    return json.dumps({"done": True, "message": "ok"})


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return ChatResult(self._responses.pop(0), 1, 1)


def test_extract_actions_normaliza():
    parsed = {"actions": [
        {"tool": "read_file", "args": {"path": "a.txt"}},
        {"name": "list_directory", "args": {"directory": "."}},
        {"tool": "x", "args": []},  # inválido
    ]}
    assert _extract_actions(parsed) == [
        {"tool": "read_file", "args": {"path": "a.txt"}},
        {"tool": "list_directory", "args": {"directory": "."}},
    ]


def test_batch_so_permite_leitura():
    tools = {"read_file": {}, "write_file": {}, "calculator": {}}
    assert _batch_allowed([{"tool": "read_file", "args": {}}], tools)
    assert not _batch_allowed([{"tool": "write_file", "args": {}}], tools)


def test_run_agent_executa_lote_em_um_step():
    calls = []

    def calc(expression):
        calls.append(expression)
        return str(eval(expression))  # noqa: S307 — teste controlado

    tools = {
        "calculator": {"fn": calc, "description": "calcula"},
        "get_local_datetime": {
            "fn": lambda: "agora",
            "description": "data",
        },
    }
    fake = FakeClient([
        json.dumps({"actions": [
            {"tool": "calculator", "args": {"expression": "1+1"}},
            {"tool": "get_local_datetime", "args": {}},
        ]}),
        _done(),
    ])

    result = run_agent(
        "oi", tools, [], "", AGENT,
        model_client=fake, max_steps=4,
    )

    assert result.status == "done"
    assert result.steps == 2
    assert result.tool_calls == 2
    assert result.batch_calls == 1
    assert result.context_peak_chars > 0
    assert calls == ["1+1"]
    assert fake.calls == 2


def test_run_agent_recusa_lote_com_escrita():
    writes = []

    def write(path, content):
        writes.append(path)
        return "ok"

    tools = {"write_file": {"fn": write, "description": "escreve"}}
    fake = FakeClient([
        json.dumps({"actions": [
            {"tool": "write_file", "args": {"path": "a.txt", "content": "x"}},
        ]}),
        _done(),
    ])

    result = run_agent(
        "oi", tools, [], "", AGENT,
        model_client=fake, max_steps=4,
    )

    assert result.status == "done"
    assert writes == []


def test_dsml_multiplos_invokes_vira_lote():
    text = """<｜｜DSML｜｜ calls>
<｜｜DSML｜｜ invoke name="read_file">
<｜｜DSML｜｜ parameter name="args" string="false">{"path": "a.txt"}</｜｜DSML｜｜ parameter>
</｜｜DSML｜｜ invoke>
<｜｜DSML｜｜ invoke name="list_directory">
<｜｜DSML｜｜ parameter name="args" string="false">{"directory": "."}</｜｜DSML｜｜ parameter>
</｜｜DSML｜｜ invoke>
</｜｜DSML｜｜ calls>"""

    parsed = _parse_response(text)

    assert parsed["actions"] == [
        {"tool": "read_file", "args": {"path": "a.txt"}},
        {"tool": "list_directory", "args": {"directory": "."}},
    ]


def test_budget_tokens_interrompe_a_task():
    class HighClient:
        def chat(self, messages, **kwargs):
            return ChatResult(_done(), 10, 10)

    result = run_agent(
        "oi", {}, [], "", AGENT,
        model_client=HighClient(), max_steps=4, budget_tokens=5,
    )

    assert result.status == "limit"
    assert "Orçamento" in result.message


def test_compact_history_preserva_inicio_e_fim():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": json.dumps({
            "tool": "write_file",
            "args": {"path": "a.txt", "content": "x" * 5_000},
        })},
        {"role": "user", "content": "Resultado da tool: " + ("y" * 5_000)},
        {"role": "assistant", "content": "recente 1"},
        {"role": "user", "content": "recente 2"},
        {"role": "assistant", "content": "recente 3"},
        {"role": "user", "content": "recente 4"},
        {"role": "assistant", "content": "recente 5"},
        {"role": "user", "content": "recente 6"},
        {"role": "assistant", "content": "recente 7"},
        {"role": "user", "content": "recente 8"},
    ]

    before = sum(len(str(m["content"])) for m in messages)
    _compact_history(messages, max_chars=1_000, keep_last=6)
    after = sum(len(str(m["content"])) for m in messages)

    assert after < before
    assert messages[0]["content"] == "system"
    assert messages[1]["content"] == "task"
    assert messages[-1]["content"] == "recente 8"
    assert "omitido" in messages[2]["content"]
    assert "compactado" in messages[3]["content"]

"""Testes do adaptador DSML (DeepSeek) do parser de resposta."""

from agent_loop import _parse_response


def test_dsml_com_args_json():
    text = """I'll start by checking the workspace.
<｜｜DSML｜｜ calls>
<｜｜DSML｜｜ invoke name="write_file">
<｜｜DSML｜｜ parameter name="args" string="false">{"path": "data/a.txt", "content": "linha1\\nlinha2"}</｜｜DSML｜｜ parameter>
</｜｜DSML｜｜ invoke>
</｜｜DSML｜｜ calls>"""

    parsed = _parse_response(text)

    assert parsed["tool"] == "write_file"
    assert parsed["args"] == {
        "path": "data/a.txt",
        "content": "linha1\nlinha2",
    }


def test_dsml_com_parametros_diretos():
    text = """<｜｜DSML｜｜ calls>
<｜｜DSML｜｜ invoke name="calculator">
<｜｜DSML｜｜ parameter name="expression" string="true">2+2</｜｜DSML｜｜ parameter>
</｜｜DSML｜｜ invoke>
</｜｜DSML｜｜ calls>"""

    parsed = _parse_response(text)

    assert parsed["tool"] == "calculator"
    assert parsed["args"] == {"expression": "2+2"}


def test_dsml_invalido_cai_no_json_normal():
    text = '{"tool": "done", "args": {}}'
    assert _parse_response(text) == {"tool": "done", "args": {}}


def test_prosa_antes_e_dois_json_pega_o_primeiro():
    text = (
        "I'll start by inspecting.\n\n"
        '{"tool": "list_directory", "args": {"directory": "."}}\n\n'
        '{"tool": "read_file", "args": {"path": "a.txt"}}'
    )
    parsed = _parse_response(text)
    assert parsed["tool"] == "list_directory"
    assert parsed["args"] == {"directory": "."}


def test_json_com_prosa_depois():
    text = '{"done": true, "message": "ok"}\n\nPronto.'
    assert _parse_response(text) == {"done": True, "message": "ok"}

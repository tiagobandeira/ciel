"""Testes do adaptador de schema interno -> tools nativas."""

from llm.native_tools import to_openai_tools


def test_converte_parametros_e_obrigatorios():
    schema = [{
        "name": "read_file",
        "description": "lê arquivo",
        "parameters": [
            {"name": "path", "type": "str", "description": "caminho"},
            {"name": "limit", "type": "int", "default": "8000",
             "description": "limite"},
            {"name": "numbered", "type": "bool", "default": "False"},
            {"name": "hunks", "type": "list", "default": "[]"},
        ],
    }]

    tools = to_openai_tools(schema)

    assert tools[0]["type"] == "function"
    fn = tools[0]["function"]
    assert fn["name"] == "read_file"
    assert fn["parameters"]["properties"]["path"]["type"] == "string"
    assert fn["parameters"]["properties"]["limit"]["type"] == "integer"
    assert fn["parameters"]["properties"]["numbered"]["type"] == "boolean"
    assert fn["parameters"]["properties"]["hunks"] == {
        "type": "array", "items": {"type": "string"},
    }
    assert fn["parameters"]["required"] == ["path"]


def test_schema_vazio_ou_sem_nome():
    assert to_openai_tools([]) == []
    assert to_openai_tools([{"description": "sem nome"}]) == []

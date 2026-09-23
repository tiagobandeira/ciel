"""
tests/test_integration/test_agent_loop.py

Testa run_agent com o modelo mockado — sem precisar do Ollama.
O mock retorna respostas JSON pré-definidas (tool call ou done),
permitindo testar o loop, callbacks de segurança e workspace guard
de forma determinística.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _resposta_done(texto: str) -> tuple[str, int, int]:
    """Simula resposta final do modelo (sem tool call)."""
    return json.dumps({"done": True, "message": texto}), 10, 20


def _resposta_tool(tool: str, args: dict) -> tuple[str, int, int]:
    """Simula resposta do modelo pedindo uma tool call."""
    return json.dumps({"tool": tool, "args": args}), 10, 20


@pytest.fixture
def tools_minimas():
    """Conjunto mínimo de tools pra testar o loop sem carregar tudo."""
    import tools_registry
    tools = tools_registry.load_tools()
    # só o necessário pra não precisar de todas as deps opcionais
    return {k: v for k, v in tools.items() if k in (
        "read_file", "write_file", "calculator", "list_directory"
    )}


@pytest.fixture
def schema(tools_minimas):
    from tools_registry import tools_schema
    return tools_schema(tools_minimas)


@pytest.fixture
def agent_info():
    return {
        "id": "general",
        "name": "General",
        "description": "Agente de teste",
        "system_prompt": "Você é um assistente de teste.",
        "allowed_tools": None,
        "allowed_mcp_servers": [],
    }


# ── testes do loop ────────────────────────────────────────────────────────────

class TestLoopBasico:
    def test_resposta_direta_sem_tool(self, tools_minimas, schema, agent_info):
        """Modelo responde direto sem chamar tool — loop termina em 1 step."""
        from agent_loop import run_agent

        with patch("agent_loop._call_model", return_value=_resposta_done("olá!")):
            result = run_agent(
                "oi",
                tools_minimas, schema,
                model="mock", agent_info=agent_info,
            )
        assert result.status == "done"
        assert "olá!" in result.message

    def test_tool_calculator(self, tools_minimas, schema, agent_info):
        """Loop com uma tool call de calculator e depois done."""
        from agent_loop import run_agent

        respostas = iter([
            _resposta_tool("calculator", {"expression": "2 + 2"}),
            _resposta_done("o resultado é 4"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                "quanto é 2+2?",
                tools_minimas, schema,
                model="mock", agent_info=agent_info,
            )
        assert result.status == "done"

    def test_limite_de_steps(self, tools_minimas, schema, agent_info):
        """Loop que nunca para deve ser interrompido pelo max_steps."""
        from agent_loop import run_agent

        # sempre retorna tool call, nunca done
        with patch("agent_loop._call_model",
                   return_value=_resposta_tool("calculator", {"expression": "1"})):
            result = run_agent(
                "calcule para sempre",
                tools_minimas, schema,
                model="mock", agent_info=agent_info,
                max_steps=3,
            )
        assert result.status in ("limit", "done", "error")


class TestCallbacksSeguranca:
    def test_on_confirm_tool_bloqueia_create(self, agent_info):
        """on_confirm_tool retornando False deve bloquear create_tool."""
        import tools_registry
        from tools_registry import tools_schema
        from agent_loop import run_agent

        tools = tools_registry.load_tools()
        schema = tools_schema(tools)

        respostas = iter([
            _resposta_tool("create_tool", {
                "tool_name": "minha_tool",
                "tool_code": '"""x"""\ndef run() -> str:\n    return "x"\n'
            }),
            _resposta_done("não consegui criar"),
        ])

        criou = []

        def on_confirm(tool_name, tool_code):
            criou.append(tool_name)
            return False  # recusa

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                "crie uma tool",
                tools, schema,
                model="mock", agent_info=agent_info,
                on_confirm_tool=on_confirm,
            )

        assert "create_tool" in criou
        # resultado deve conter mensagem de recusa, não erro de execução
        assert result.status in ("done", "error")

    def test_on_confirm_path_bloqueia_acesso_externo(
        self, tools_minimas, schema, agent_info, tmp_path
    ):
        """on_confirm_path retornando False deve bloquear leitura fora do workspace."""
        import workspace
        from agent_loop import run_agent

        workspace.init_workspace(tmp_path)
        arquivo_externo = str(Path("/etc/hosts"))

        respostas = iter([
            _resposta_tool("read_file", {"path": arquivo_externo}),
            _resposta_done("acesso negado"),
        ])

        path_bloqueado = []

        def on_confirm_path(raw_path, need_write):
            path_bloqueado.append(raw_path)
            return False

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                f"leia {arquivo_externo}",
                tools_minimas, schema,
                model="mock", agent_info=agent_info,
                on_confirm_path=on_confirm_path,
            )

        assert arquivo_externo in path_bloqueado


class TestExternalData:
    def test_output_externo_marcado_no_contexto(
        self, tools_minimas, schema, agent_info, tmp_path
    ):
        """
        Resultado de tool com OUTPUT='external' deve aparecer no contexto
        do modelo com marcação [EXTERNAL_DATA].
        """
        import workspace
        from agent_loop import run_agent

        workspace.init_workspace(tmp_path)
        (tmp_path / "pagina.txt").write_text("conteúdo da página")

        # adiciona read_file com output_type=external pra simular read_url
        tools_ext = dict(tools_minimas)
        tools_ext["read_file"] = {
            **tools_minimas["read_file"],
            "output_type": "external",
        }

        mensagens_recebidas = []

        def mock_call(messages, model, ollama_url):
            mensagens_recebidas.extend(messages)
            if len(mensagens_recebidas) < 5:
                return _resposta_tool("read_file", {"path": "pagina.txt"})
            return _resposta_done("li o arquivo")

        from tools_registry import tools_schema
        schema_ext = tools_schema(tools_ext)

        with patch("agent_loop._call_model", side_effect=mock_call):
            run_agent(
                "leia pagina.txt",
                tools_ext, schema_ext,
                model="mock", agent_info=agent_info,
            )

        # alguma mensagem enviada ao modelo deve conter a marcação
        todos_conteudos = " ".join(
            str(m.get("content", "")) for m in mensagens_recebidas
        )
        assert "[EXTERNAL_DATA" in todos_conteudos

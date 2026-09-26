"""
tests/test_integration/test_agent_loop_borda.py

Testes de valor agregado para agent_loop — caminhos de borda que não
aparecem no caminho feliz: JSON inválido, recusa de tool, recusa de path,
exceções em tool e esgotamento de steps.

Todos os testes mockam _call_model — sem Ollama.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from agent_loop import run_agent, AgentResult


# ── fixtures ──────────────────────────────────────────────────────────────────

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


@pytest.fixture
def tools():
    import tools_registry
    return tools_registry.load_tools()


@pytest.fixture
def schema(tools):
    from tools_registry import tools_schema
    return tools_schema(tools)


def _resp(payload, t_in=5, t_out=10):
    """Tupla de resposta mockada."""
    if isinstance(payload, dict):
        return json.dumps(payload), t_in, t_out
    return payload, t_in, t_out


def _done(msg="ok"):
    return _resp({"done": True, "message": msg})


def _tool(name, **args):
    return _resp({"tool": name, "args": args})


# ── parse error — JSON inválido ───────────────────────────────────────────────

class TestParseError:
    def test_json_invalido_nao_encerra_loop(self, agent_info, tools, schema):
        """Modelo retorna texto livre → loop injeta correção e continua."""
        respostas = iter([
            _resp("Claro! Posso te ajudar com isso."),  # inválido
            _done("corrigi e respondi"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent("oi", tools, schema, "mock", agent_info)

        assert result.status == "done"
        assert result.message == "corrigi e respondi"

    def test_json_invalido_incrementa_step(self, agent_info, tools, schema):
        """Parse error consome um step — o loop continua com step+1."""
        steps = []

        def on_step(s, label, desc, kind):
            steps.append((s, kind))

        respostas = iter([
            _resp("resposta inválida"),
            _done("ok"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            run_agent("oi", tools, schema, "mock", agent_info, on_step=on_step)

        kinds = [k for _, k in steps]
        assert "parse_error" in kinds

    def test_json_invalido_injeta_correcao_como_user(self, agent_info, tools, schema):
        """
        Após parse error, o loop injeta uma mensagem de role 'user' com
        instrução de correção — não encerra o loop.
        Bug conhecido: o modelo pode interpretar essa mensagem como vinda
        do usuário real e se desculpar. Fix proposto: prefixar com [SISTEMA].
        """
        mensagens_injetadas = []
        call_count = {"n": 0}

        original_call = __import__("agent_loop")._call_model

        def interceptar(messages, model, url):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # captura a mensagem que foi injetada antes da segunda chamada
                mensagens_injetadas.extend(messages[-2:])
            if call_count["n"] == 1:
                return _resp("texto livre inválido")
            return _done("ok")

        with patch("agent_loop._call_model", side_effect=interceptar):
            run_agent("oi", tools, schema, "mock", agent_info)

        # a mensagem de correção deve existir
        assert any("JSON" in m.get("content", "") or "formato" in m.get("content", "").lower()
                   for m in mensagens_injetadas)

    def test_multiplos_json_invalidos_ate_max_steps(self, agent_info, tools, schema):
        """Loop com todos os steps retornando JSON inválido → status limit ou error."""
        with patch("agent_loop._call_model", return_value=_resp("texto livre")):
            result = run_agent("oi", tools, schema, "mock", agent_info, max_steps=3)

        assert result.status in ("limit", "error", "needs_tool")

    def test_json_com_fence_markdown_e_parseado(self, agent_info, tools, schema):
        """Modelo retorna JSON dentro de ```json ... ``` → deve ser parseado."""
        raw = "```json\n" + json.dumps({"done": True, "message": "parseado"}) + "\n```"

        with patch("agent_loop._call_model", return_value=_resp(raw)):
            result = run_agent("oi", tools, schema, "mock", agent_info)

        assert result.status == "done"
        assert result.message == "parseado"

    def test_parse_error_seguido_de_tool_valida(self, agent_info, tools, schema):
        """Após parse error, modelo corrije e faz tool call válida."""
        respostas = iter([
            _resp("me desculpe, vou responder em JSON"),  # inválido
            _tool("calculator", expression="2+2"),
            _done("resultado: 4"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent("calcule 2+2", tools, schema, "mock", agent_info)

        assert result.status == "done"


# ── on_confirm_tool — recusa de tool sensível ─────────────────────────────────

class TestConfirmTool:
    def test_sem_callback_tool_sensivel_bloqueada(self, agent_info, tools, schema):
        """on_confirm_tool=None com tool sensível → bloqueada, loop continua."""
        respostas = iter([
            _tool("create_tool", tool_name="x", tool_code="def run(): pass"),
            _done("ok sem a tool"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                "crie uma tool",
                tools, schema, "mock", agent_info,
                on_confirm_tool=None,
            )

        assert result.status == "done"

    def test_sem_callback_feedback_enviado_ao_modelo(self, agent_info, tools, schema):
        """Quando bloqueada, o feedback vai pro modelo via messages."""
        mensagens = []
        call_count = {"n": 0}

        def interceptar(messages, model, url):
            call_count["n"] += 1
            if call_count["n"] == 2:
                mensagens.extend(messages[-2:])
            if call_count["n"] == 1:
                return _tool("create_tool", tool_name="x", tool_code="def run(): pass")
            return _done("ok")

        with patch("agent_loop._call_model", side_effect=interceptar):
            run_agent("crie uma tool", tools, schema, "mock", agent_info, on_confirm_tool=None)

        conteudos = " ".join(m.get("content", "") for m in mensagens)
        assert "bloqueada" in conteudos.lower() or "confirmação" in conteudos.lower()

    def test_callback_retorna_false_recusa_tool(self, agent_info, tools, schema):
        """on_confirm_tool retornando False → recusada, feedback ao modelo."""
        respostas = iter([
            _tool("create_tool", tool_name="x", tool_code="def run(): pass"),
            _done("ok sem criar"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                "crie uma tool",
                tools, schema, "mock", agent_info,
                on_confirm_tool=lambda name, code: False,
            )

        assert result.status == "done"

    def test_callback_retorna_true_executa_tool(self, agent_info, tools, schema):
        """on_confirm_tool retornando True → tool executada."""
        tool_executada = {"sim": False}
        original_fn = tools.get("create_tool", {}).get("fn")

        def mock_create(**kwargs):
            tool_executada["sim"] = True
            return "tool criada com sucesso"

        tools_fake = dict(tools)
        if "create_tool" in tools_fake:
            tools_fake["create_tool"] = dict(tools_fake["create_tool"])
            tools_fake["create_tool"]["fn"] = mock_create

        respostas = iter([
            _tool("create_tool", tool_name="x", tool_code="def run(): pass"),
            _done("feito"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                "crie",
                tools_fake, schema, "mock", agent_info,
                on_confirm_tool=lambda name, code: True,
            )

        assert tool_executada["sim"] is True
        assert result.status == "done"

    def test_on_confirm_tool_recebe_nome_e_codigo(self, agent_info, tools, schema):
        """on_confirm_tool deve receber o nome da tool e o tool_code."""
        confirmacoes = []

        respostas = iter([
            _tool("create_tool", tool_name="minha_tool", tool_code="def run(): return 'ok'"),
            _done("ok"),
        ])

        def on_confirm(name, code):
            confirmacoes.append((name, code))
            return False

        with patch("agent_loop._call_model", side_effect=respostas):
            run_agent("crie", tools, schema, "mock", agent_info, on_confirm_tool=on_confirm)

        assert len(confirmacoes) == 1
        assert confirmacoes[0][0] == "create_tool"
        assert "run" in confirmacoes[0][1]


# ── on_confirm_path — recusa de acesso a path ────────────────────────────────

class TestConfirmPath:
    def test_path_negado_feedback_ao_modelo(self, agent_info, tools, schema):
        """on_confirm_path retornando False → acesso negado, loop continua."""
        respostas = iter([
            _tool("read_file", path="/etc/passwd"),
            _done("ok sem ler"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                "leia /etc/passwd",
                tools, schema, "mock", agent_info,
                on_confirm_path=lambda path, write: False,
            )

        assert result.status == "done"

    def test_path_negado_nao_executa_tool(self, agent_info, tools, schema):
        """Tool não deve ser executada quando path é negado."""
        tool_executada = {"sim": False}
        tools_fake = dict(tools)

        def mock_read(**kwargs):
            tool_executada["sim"] = True
            return "conteudo"

        if "read_file" in tools_fake:
            tools_fake["read_file"] = dict(tools_fake["read_file"])
            tools_fake["read_file"]["fn"] = mock_read

        respostas = iter([
            _tool("read_file", path="/etc/passwd"),
            _done("ok"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            run_agent(
                "leia", tools_fake, schema, "mock", agent_info,
                on_confirm_path=lambda path, write: False,
            )

        assert tool_executada["sim"] is False

    def test_path_permitido_executa_normalmente(self, agent_info, tools, schema, tmp_path):
        """on_confirm_path retornando True → tool executa normalmente."""
        arquivo = tmp_path / "teste.txt"
        arquivo.write_text("conteúdo real", encoding="utf-8")

        respostas = iter([
            _tool("read_file", path=str(arquivo)),
            _done("lido"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent(
                "leia o arquivo",
                tools, schema, "mock", agent_info,
                on_confirm_path=lambda path, write: True,
            )

        assert result.status == "done"


# ── exceções em tool ──────────────────────────────────────────────────────────

class TestExcecaoEmTool:
    def test_typeerror_nao_encerra_loop(self, agent_info, tools, schema):
        """TypeError nos args da tool → feedback ao modelo, loop continua."""
        respostas = iter([
            _tool("calculator", arg_errado="x"),  # calculator espera 'expression'
            _done("ok após erro"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent("calcule algo", tools, schema, "mock", agent_info)

        assert result.status == "done"

    def test_typeerror_feedback_menciona_assinatura(self, agent_info, tools, schema):
        """Feedback de TypeError deve mencionar a assinatura correta."""
        feedbacks = []
        call_count = {"n": 0}

        def interceptar(messages, model, url):
            call_count["n"] += 1
            if call_count["n"] == 2:
                feedbacks.extend(messages[-2:])
            if call_count["n"] == 1:
                return _tool("calculator", arg_errado="x")
            return _done("ok")

        with patch("agent_loop._call_model", side_effect=interceptar):
            run_agent("calcule", tools, schema, "mock", agent_info)

        conteudo = " ".join(m.get("content", "") for m in feedbacks)
        assert "calculator" in conteudo or "Args" in conteudo

    def test_exception_generica_nao_encerra_loop(self, agent_info, tools, schema):
        """Exception genérica na tool → feedback ao modelo, loop continua."""
        tools_fake = dict(tools)
        tools_fake["calculator"] = dict(tools_fake["calculator"])
        tools_fake["calculator"]["fn"] = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("erro inesperado"))

        respostas = iter([
            _tool("calculator", expression="1+1"),
            _done("ok após exception"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent("calcule", tools_fake, schema, "mock", agent_info)

        assert result.status == "done"

    def test_exception_feedback_enviado_ao_modelo(self, agent_info, tools, schema):
        """Após exception, o erro vai como feedback pro modelo."""
        tools_fake = dict(tools)
        tools_fake["calculator"] = dict(tools_fake["calculator"])
        tools_fake["calculator"]["fn"] = lambda **kwargs: (_ for _ in ()).throw(ValueError("divisão por zero"))

        feedbacks = []
        call_count = {"n": 0}

        def interceptar(messages, model, url):
            call_count["n"] += 1
            if call_count["n"] == 2:
                feedbacks.extend(messages[-2:])
            if call_count["n"] == 1:
                return _tool("calculator", expression="1/0")
            return _done("ok")

        with patch("agent_loop._call_model", side_effect=interceptar):
            run_agent("calcule", tools_fake, schema, "mock", agent_info)

        conteudo = " ".join(m.get("content", "") for m in feedbacks)
        assert "divisão por zero" in conteudo or "Erro" in conteudo

    def test_tool_inexistente_feedback_lista_disponiveis(self, agent_info, tools, schema):
        """Tool que não existe → feedback lista as tools disponíveis."""
        feedbacks = []
        call_count = {"n": 0}

        def interceptar(messages, model, url):
            call_count["n"] += 1
            if call_count["n"] == 2:
                feedbacks.extend(messages[-2:])
            if call_count["n"] == 1:
                return _tool("tool_fantasma")
            return _done("ok")

        with patch("agent_loop._call_model", side_effect=interceptar):
            run_agent("use a tool fantasma", tools, schema, "mock", agent_info)

        conteudo = " ".join(m.get("content", "") for m in feedbacks)
        assert "não existe" in conteudo or "Disponíveis" in conteudo


# ── limite de steps ───────────────────────────────────────────────────────────

class TestLimiteDeSteps:
    def test_steps_esgotados_retorna_limit_ou_needs_tool(self, agent_info, tools, schema):
        """Com max_steps=2 e tool call em cada step → limit ou needs_tool."""
        with patch("agent_loop._call_model", return_value=_tool("calculator", expression="1+1")):
            result = run_agent(
                "calcule", tools, schema, "mock", agent_info,
                max_steps=2,
            )

        assert result.status in ("limit", "needs_tool")

    def test_steps_esgotados_chama_on_limit(self, agent_info, tools, schema):
        """on_limit deve ser chamado quando steps se esgotam."""
        limits = []

        def on_limit(steps, tin, tout):
            limits.append(steps)

        with patch("agent_loop._call_model", return_value=_tool("calculator", expression="1+1")), \
             patch("agent_loop._ask_model_for_tool_proposal", return_value=None):
            run_agent(
                "calcule", tools, schema, "mock", agent_info,
                max_steps=2,
                on_limit=on_limit,
            )

        assert len(limits) > 0

    def test_acumula_tokens_ao_longo_dos_steps(self, agent_info, tools, schema):
        """tokens_in e tokens_out devem ser acumulados entre steps."""
        respostas = iter([
            _tool("calculator", expression="1+1"),
            _done("ok"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent("calcule", tools, schema, "mock", agent_info)

        assert result.tokens_in > 0
        assert result.tokens_out > 0

    def test_steps_contados_corretamente(self, agent_info, tools, schema):
        """steps no resultado deve refletir quantas chamadas ao modelo foram feitas."""
        respostas = iter([
            _tool("calculator", expression="1+1"),
            _tool("calculator", expression="2+2"),
            _done("feito"),
        ])

        with patch("agent_loop._call_model", side_effect=respostas):
            result = run_agent("calcule", tools, schema, "mock", agent_info)

        assert result.steps == 3


# ── erro de conexão ───────────────────────────────────────────────────────────

class TestErroConexao:
    def test_connection_error_retorna_status_error(self, agent_info, tools, schema):
        """RequestException na primeira chamada → status error."""
        import requests

        with patch("agent_loop._call_model", side_effect=requests.ConnectionError("recusada")):
            result = run_agent("oi", tools, schema, "mock", agent_info)

        assert result.status == "error"

    def test_connection_error_chama_on_error(self, agent_info, tools, schema):
        """RequestException deve chamar on_error com kind='connection'."""
        import requests
        erros = []

        with patch("agent_loop._call_model", side_effect=requests.ConnectionError("recusada")):
            run_agent(
                "oi", tools, schema, "mock", agent_info,
                on_error=lambda kind, msg: erros.append(kind),
            )

        assert "connection" in erros

    def test_connection_error_mensagem_nao_vazia(self, agent_info, tools, schema):
        """Mensagem de erro de conexão deve ter conteúdo útil."""
        import requests

        with patch("agent_loop._call_model", side_effect=requests.ConnectionError("host unreachable")):
            result = run_agent("oi", tools, schema, "mock", agent_info)

        assert result.message


# ── fix proposto: mensagem de parse error ────────────────────────────────────

class TestParseErrorFix:
    """
    Documenta o bug atual e verifica o fix proposto.

    Bug: após parse error, o loop injeta a correção com role='user' e
    texto "Resposta inválida. Retorne APENAS JSON no formato especificado."
    O modelo interpreta isso como reclamação do usuário real e se desculpa
    ("Me desculpe pelo erro anterior...").

    Fix proposto: prefixar com [SISTEMA] para sinalizar que não é o usuário.
    """

    def test_mensagem_de_correcao_tem_prefixo_sistema(self, agent_info, tools, schema):
        """
        Após parse error, a mensagem injetada deve ter prefixo [SISTEMA]
        para não ser confundida com mensagem do usuário real.

        Se este teste falhar, o bug ainda está presente.
        """
        mensagens_injetadas = []
        call_count = {"n": 0}

        def interceptar(messages, model, url):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # captura última mensagem injetada (a correção)
                correcao = next(
                    (m for m in reversed(messages) if m["role"] == "user"),
                    None,
                )
                if correcao:
                    mensagens_injetadas.append(correcao["content"])
            if call_count["n"] == 1:
                return _resp("texto livre sem JSON")
            return _done("ok")

        with patch("agent_loop._call_model", side_effect=interceptar):
            run_agent("oi", tools, schema, "mock", agent_info)

        assert mensagens_injetadas, "nenhuma mensagem de correção foi injetada"
        correcao = mensagens_injetadas[0]

        # FIX: deve ter prefixo [SISTEMA] para não parecer mensagem do usuário
        assert correcao.startswith("[SISTEMA]"), (
            f"Bug presente: mensagem de correção sem prefixo [SISTEMA].\n"
            f"Mensagem atual: {correcao!r}\n"
            f"Fix: em agent_loop.py, mudar para:\n"
            f'  "content": "[SISTEMA] Formato inválido. Responda APENAS em JSON puro."'
        )

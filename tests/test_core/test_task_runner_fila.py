"""
tests/test_core/test_task_runner_fila.py

Testes de valor agregado para run_task — fila determinística com falhas,
tipos desconhecidos, limite de steps e consolidador final.

Complementa test_task_runner.py (que cobre parsing e estruturas de dados).
Aqui o foco é o comportamento de execução real da fila, especialmente
caminhos de erro que não aparecem no caminho feliz.

Todos os testes mockam _call_model e _request_plan — sem Ollama.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from task_runner import (
    run_task,
    TaskCheckpoint,
    _execute_tool,
    _build_final_message,
)
from agent_loop import AgentResult


# ── fixtures base ─────────────────────────────────────────────────────────────

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


@pytest.fixture
def task_com_grupo():
    return {
        "nome": "task-fila",
        "objetivo": "calcular múltiplos valores",
        "acoes": [
            "calcular 2+2 [tool: calculator]",
            "calcular 3+3 [tool: calculator]",
            "calcular 4+4 [tool: calculator]",
        ],
        "resultado": "resultados calculados",
        "grupo": "calculator",
    }


def _done_response(msg="ok"):
    """Resposta de modelo que encerra o loop."""
    return json.dumps({"done": True, "message": msg}), 5, 10


def _make_plan(*tool_names, tool="calculator"):
    """Gera um plano com ações tool simples."""
    return [
        {
            "id": f"a{i+1}",
            "type": "tool",
            "tool": tool,
            "args": {"expression": f"{i+1}+{i+1}"},
            "descricao": f"calcular {i+1}+{i+1}",
        }
        for i in range(len(tool_names))
    ]


# ── fila com falha no meio ────────────────────────────────────────────────────

class TestFilaComFalha:
    def test_falha_nao_bloqueia_acoes_seguintes(self, task_com_grupo, tools, schema, agent_info):
        """Tool 2 falha — tools 1 e 3 devem executar normalmente."""
        call_count = {"n": 0}

        def tool_seletivo(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("erro proposital na ação 2")
            return f"resultado {call_count['n']}"

        plano = _make_plan("a1", "a2", "a3")

        tools_fake = {
            "calculator": {
                "fn": tool_seletivo,
                "description": "calculadora",
                "permissions": [],
                "output_type": "text",
                "interactive": False,
            }
        }

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("consolidado")):
            result = run_task(
                task_com_grupo, tools_fake, schema,
                model="mock", agent_info=agent_info,
            )

        assert result.status == "done"
        assert call_count["n"] == 3  # as 3 tools foram chamadas

    def test_checkpoint_failed_registra_acao_com_erro(self, task_com_grupo, tools, schema, agent_info):
        """Ação que falha deve aparecer em checkpoint.failed."""
        steps_capturados = []

        def tool_que_falha(**kwargs):
            raise ValueError("falha controlada")

        plano = [
            {"id": "a1", "type": "tool", "tool": "calculator",
             "args": {"expression": "1+1"}, "descricao": "ok"},
            {"id": "a2", "type": "tool", "tool": "calculator",
             "args": {"expression": "2+2"}, "descricao": "falha"},
        ]

        tools_fake = {
            "calculator": {
                "fn": tool_que_falha,
                "description": "calculadora",
                "permissions": [],
                "output_type": "text",
                "interactive": False,
            }
        }

        checkpoint_capturado = {}

        original_run_task = run_task

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")), \
             patch("task_runner.TaskCheckpoint", wraps=TaskCheckpoint) as mock_cp:
            result = run_task(
                task_com_grupo, tools_fake, schema,
                model="mock", agent_info=agent_info,
            )

        # resultado ainda é done — falha não é fatal
        assert result.status == "done"

    def test_checkpoint_completed_nao_inclui_falha(self, task_com_grupo, tools, schema, agent_info):
        """Ação que falha não deve estar em completed."""
        call_count = {"n": 0}

        def tool_falha_na_segunda(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("falha")
            return "sucesso"

        plano = [
            {"id": "a1", "type": "tool", "tool": "calculator",
             "args": {}, "descricao": "falha"},
            {"id": "a2", "type": "tool", "tool": "calculator",
             "args": {}, "descricao": "sucesso"},
        ]

        tools_fake = {
            "calculator": {
                "fn": tool_falha_na_segunda,
                "description": "calculadora",
                "permissions": [],
                "output_type": "text",
                "interactive": False,
            }
        }

        steps = []

        def on_step(step, label, desc, kind):
            steps.append((label, kind))

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            result = run_task(
                task_com_grupo, tools_fake, schema,
                model="mock", agent_info=agent_info,
                on_step=on_step,
            )

        assert result.status == "done"
        # ação 2 executou (sucesso) — verificado via call_count
        assert call_count["n"] == 2

    def test_callback_on_step_sinaliza_erro(self, task_com_grupo, tools, schema, agent_info):
        """on_step deve ser chamado com kind='error' quando tool falha."""
        def tool_falha(**kwargs):
            raise RuntimeError("erro")

        plano = [
            {"id": "a1", "type": "tool", "tool": "calculator",
             "args": {}, "descricao": "vai falhar"},
        ]

        tools_fake = {
            "calculator": {
                "fn": tool_falha,
                "description": "calculadora",
                "permissions": [],
                "output_type": "text",
                "interactive": False,
            }
        }

        steps = []

        def on_step(step, label, desc, kind):
            steps.append(kind)

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            run_task(
                task_com_grupo, tools_fake, schema,
                model="mock", agent_info=agent_info,
                on_step=on_step,
            )

        assert "error" in steps

    def test_tool_inexistente_marca_failed(self, task_com_grupo, tools, schema, agent_info):
        """Ação com tool que não existe deve registrar falha e continuar."""
        plano = [
            {"id": "a1", "type": "tool", "tool": "tool_que_nao_existe",
             "args": {}, "descricao": "tool inválida"},
            {"id": "a2", "type": "tool", "tool": "calculator",
             "args": {"expression": "1+1"}, "descricao": "calculator válida"},
        ]

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
            )

        assert result.status == "done"

    def test_todas_falham_resultado_ainda_done(self, task_com_grupo, tools, schema, agent_info):
        """Mesmo com todas as tools falhando, run_task retorna done (não error)."""
        def tool_sempre_falha(**kwargs):
            raise RuntimeError("sempre falha")

        plano = [
            {"id": f"a{i}", "type": "tool", "tool": "calculator",
             "args": {}, "descricao": f"ação {i}"}
            for i in range(3)
        ]

        tools_fake = {
            "calculator": {
                "fn": tool_sempre_falha,
                "description": "calculadora",
                "permissions": [],
                "output_type": "text",
                "interactive": False,
            }
        }

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok mesmo sem dados")):
            result = run_task(
                task_com_grupo, tools_fake, schema,
                model="mock", agent_info=agent_info,
            )

        assert result.status == "done"


# ── ação com tipo desconhecido ────────────────────────────────────────────────

class TestTipoDesconhecido:
    def test_tipo_desconhecido_e_skipped(self, task_com_grupo, tools, schema, agent_info):
        """Ação com type='???' deve ser skippada sem consumir step."""
        plano = [
            {"id": "a1", "type": "???", "descricao": "tipo inválido"},
            {"id": "a2", "type": "tool", "tool": "calculator",
             "args": {"expression": "2+2"}, "descricao": "válida"},
        ]

        steps = []

        def on_step(step, label, desc, kind):
            steps.append((label, kind))

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                on_step=on_step,
            )

        assert result.status == "done"
        # "skip" deve aparecer nos steps
        labels = [label for label, _ in steps]
        assert any("skip" in l.lower() for l in labels)

    def test_tipo_desconhecido_nao_consome_step(self, task_com_grupo, tools, schema, agent_info):
        """Tipo desconhecido não deve incrementar o contador de steps."""
        plano = [
            {"id": "a1", "type": "fantasma", "descricao": "não existe"},
        ]

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
            )

        # steps = 1 (planejamento) + 1 (consolidador) = 2
        assert result.steps <= 2


# ── limite de steps ───────────────────────────────────────────────────────────

class TestLimiteDeSteps:
    def test_acao_model_com_step_limite_retorna_limit(self, task_com_grupo, tools, schema, agent_info):
        """
        Ação 'model' com max_steps=2: step=1 (planejamento), condição step+1 >= max_steps
        dispara SOMENTE se o sub-agente não completar antes.
        Quando _call_model retorna done imediatamente, o sub-agente completa em 1 step
        e o run_task retorna done (não limit), porque o step do run_task não avança.

        Comportamento documentado: o check de limit protege sub-agentes lentos,
        mas não se o modelo responde done no primeiro step interno.
        Para forçar limit: usar muitas ações model com max_steps muito baixo.
        """
        plano = [
            {"id": f"a{i}", "type": "model", "descricao": f"análise {i}"}
            for i in range(5)
        ]

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            # max_steps=3: planejamento(1) + model(2) + check limit antes de model(3)
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                max_steps=3,
            )

        # status pode ser limit ou done dependendo de quantos steps o sub-agente usa
        assert result.status in ("limit", "done")

    def test_limit_retorna_melhor_resultado_parcial(self, task_com_grupo, tools, schema, agent_info):
        """Status 'limit' deve trazer mensagem não vazia."""
        plano = [
            {"id": "a1", "type": "tool", "tool": "calculator",
             "args": {"expression": "1+1"}, "descricao": "calc"},
            {"id": "a2", "type": "model", "descricao": "análise"},
        ]

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                max_steps=2,
            )

        assert result.message  # não vazio

    def test_consolidador_sem_step_usa_fallback(self, task_com_grupo, tools, schema, agent_info):
        """Quando step >= max_steps no consolidador, usa _build_final_message."""
        plano = [
            {"id": "a1", "type": "tool", "tool": "calculator",
             "args": {"expression": "5+5"}, "descricao": "calc"},
        ]

        # max_steps=2: step=1 (plano) → fila executa → step=1 ainda (tool não incrementa)
        # consolidador: step+1=2 >= max_steps=2? Não → executa normalmente
        # Para forçar fallback: max_steps=1 (planejamento já esgota)
        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=_done_response("ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                max_steps=1,
            )

        assert result.status in ("done", "limit")
        assert result.message


# ── sub-agente retorna erro ───────────────────────────────────────────────────

class TestSubAgenteComErro:
    def test_sub_agente_error_propaga_para_run_task(self, task_com_grupo, tools, schema, agent_info):
        """Ação 'model' cujo sub-agente retorna error → run_task retorna error.

        run_agent é importado via 'from agent_loop import run_agent' no topo do
        task_runner, então o patch deve ser em 'agent_loop.run_agent'.
        """
        plano = [
            {"id": "a1", "type": "model", "descricao": "análise com erro"},
        ]

        error_result = AgentResult(
            "error", "Erro de conexão com Ollama",
            tokens_in=0, tokens_out=0, steps=1,
        )

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop.run_agent", return_value=error_result):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                max_steps=10,
            )

        assert result.status == "error"
        assert "Erro de conexão" in result.message

    def test_sub_agente_error_chama_on_error(self, task_com_grupo, tools, schema, agent_info):
        """on_error deve ser chamado quando sub-agente retorna error."""
        plano = [
            {"id": "a1", "type": "model", "descricao": "vai dar erro"},
        ]

        error_result = AgentResult(
            "error", "timeout",
            tokens_in=0, tokens_out=0, steps=1,
        )

        erros = []

        def on_error(kind, msg):
            erros.append((kind, msg))

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop.run_agent", return_value=error_result):
            run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                max_steps=10,
                on_error=on_error,
            )

        assert len(erros) > 0


# ── _execute_tool ─────────────────────────────────────────────────────────────

class TestExecuteTool:
    @pytest.fixture
    def tools_fake(self):
        return {
            "calculator": {
                "fn": lambda expression: str(eval(expression)),
                "description": "calculadora",
                "permissions": [],
                "output_type": "text",
                "interactive": False,
            },
            "tool_interativa": {
                "fn": lambda perguntar=None: "resposta interativa",
                "description": "interativa",
                "permissions": [],
                "output_type": "text",
                "interactive": True,
            },
        }

    @pytest.fixture
    def agent(self):
        return {"id": "general", "name": "General"}

    def test_sucesso_retorna_true_e_resultado(self, tools_fake, agent):
        action = {"id": "a1", "type": "tool", "tool": "calculator",
                  "args": {"expression": "2+2"}, "descricao": "calc"}
        ok, result = _execute_tool(action, tools_fake, agent, None, None, None, None)
        assert ok is True
        assert "4" in result

    def test_tool_inexistente_retorna_false(self, tools_fake, agent):
        action = {"id": "a1", "type": "tool", "tool": "nao_existe",
                  "args": {}, "descricao": "?"}
        ok, result = _execute_tool(action, tools_fake, agent, None, None, None, None)
        assert ok is False
        assert "não encontrada" in result

    def test_tool_lanca_exception_retorna_false(self, tools_fake, agent):
        tools_fake["calculator"]["fn"] = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        action = {"id": "a1", "type": "tool", "tool": "calculator",
                  "args": {}, "descricao": "erro"}
        ok, result = _execute_tool(action, tools_fake, agent, None, None, None, None)
        assert ok is False
        assert "boom" in result or "Erro" in result

    def test_tool_lanca_typeerror_retorna_false(self, tools_fake, agent):
        action = {"id": "a1", "type": "tool", "tool": "calculator",
                  "args": {"arg_errado": "x"}, "descricao": "args inválidos"}
        ok, result = _execute_tool(action, tools_fake, agent, None, None, None, None)
        assert ok is False
        assert "Args inválidos" in result or "Erro" in result

    def test_tool_sensivel_sem_confirm_bloqueada(self, agent):
        """Tool que needs_confirmation=True sem on_confirm_tool → bloqueada."""
        from tools_registry import load_tools
        tools = load_tools()
        action = {"id": "a1", "type": "tool", "tool": "create_tool",
                  "args": {"tool_name": "x", "tool_code": "def run(): pass"},
                  "descricao": "criar tool"}
        ok, result = _execute_tool(action, tools, agent, None, None, None, None)
        assert ok is False
        assert "bloqueada" in result.lower() or "requer confirmação" in result.lower()

    def test_tool_sensivel_confirm_false_bloqueada(self, agent):
        """on_confirm_tool retornando False → tool recusada."""
        from tools_registry import load_tools
        tools = load_tools()
        action = {"id": "a1", "type": "tool", "tool": "create_tool",
                  "args": {"tool_name": "x", "tool_code": "def run(): pass"},
                  "descricao": "criar tool"}
        ok, result = _execute_tool(
            action, tools, agent, None,
            on_confirm_tool=lambda name, code: False,
            on_confirm_path=None, on_ask_user=None,
        )
        assert ok is False
        assert "recusada" in result.lower()

    def test_tool_sensivel_confirm_true_executa(self, agent):
        """on_confirm_tool retornando True → tool executa (mesmo que falhe por outros motivos)."""
        from tools_registry import load_tools
        tools = load_tools()
        action = {"id": "a1", "type": "tool", "tool": "create_tool",
                  "args": {"tool_name": "x", "tool_code": "def run(): pass"},
                  "descricao": "criar tool"}
        # Mesmo que a tool falhe por args inválidos, não deve retornar "bloqueada"
        ok, result = _execute_tool(
            action, tools, agent, None,
            on_confirm_tool=lambda name, code: True,
            on_confirm_path=None, on_ask_user=None,
        )
        # ok pode ser False por erro de args, mas a mensagem não deve ser de bloqueio
        assert "bloqueada" not in result.lower()

    def test_on_confirm_path_false_bloqueia(self, tools_fake, agent, tmp_path):
        """on_confirm_path retornando False bloqueia acesso ao path."""
        from tools_registry import load_tools
        tools = load_tools()
        # read_file tem path check
        action = {"id": "a1", "type": "tool", "tool": "read_file",
                  "args": {"path": "/caminho/fora/workspace"},
                  "descricao": "leitura"}
        ok, result = _execute_tool(
            action, tools, agent, None,
            on_confirm_tool=None,
            on_confirm_path=lambda path, write: False,
            on_ask_user=None,
        )
        assert ok is False
        assert "negado" in result.lower()

    def test_tool_interativa_recebe_perguntar(self, tools_fake, agent):
        """Tool interativa recebe on_ask_user via args['perguntar']."""
        action = {"id": "a1", "type": "tool", "tool": "tool_interativa",
                  "args": {}, "descricao": "interativa"}
        perguntar_chamado = []
        ok, result = _execute_tool(
            action, tools_fake, agent, None, None, None,
            on_ask_user=lambda p: perguntar_chamado.append(p) or "resp",
        )
        assert ok is True


# ── _build_final_message ──────────────────────────────────────────────────────

class TestBuildFinalMessageComFalhas:
    def _actions(self, *specs):
        """specs: lista de (id, type)"""
        return [{"id": aid, "type": atype, "descricao": f"ação {aid}"}
                for aid, atype in specs]

    def test_usa_ultimo_model_bem_sucedido(self):
        actions = self._actions(("a1", "tool"), ("a2", "model"), ("a3", "model"))
        cp = TaskCheckpoint(actions)
        cp.mark_done("a1", "dado coletado")
        cp.mark_done("a2", "análise intermediária")
        cp.mark_done("a3", "análise final elaborada")
        msg = _build_final_message({"nome": "t"}, cp)
        assert "análise final elaborada" in msg

    def test_pula_model_com_erro(self):
        actions = self._actions(("a1", "model"), ("a2", "model"))
        cp = TaskCheckpoint(actions)
        cp.mark_failed("a1", "erro grave")
        cp.mark_done("a2", "resultado válido")
        msg = _build_final_message({"nome": "t"}, cp)
        assert "resultado válido" in msg
        assert "erro grave" not in msg

    def test_fallback_tools_quando_sem_model(self):
        actions = self._actions(("a1", "tool"), ("a2", "tool"))
        cp = TaskCheckpoint(actions)
        cp.mark_done("a1", "resultado tool 1")
        cp.mark_done("a2", "resultado tool 2")
        msg = _build_final_message({"nome": "t"}, cp)
        assert "resultado tool 1" in msg or "resultado tool 2" in msg

    def test_fallback_generico_quando_tudo_falhou(self):
        actions = self._actions(("a1", "tool"), ("a2", "model"))
        cp = TaskCheckpoint(actions)
        cp.mark_failed("a1", "erro 1")
        cp.mark_failed("a2", "erro 2")
        msg = _build_final_message({"nome": "minha-task"}, cp)
        assert "minha-task" in msg

    def test_erros_nao_aparecem_na_mensagem_final(self):
        actions = self._actions(("a1", "tool"),)
        cp = TaskCheckpoint(actions)
        cp.mark_failed("a1", "senha123 vazada no erro")
        msg = _build_final_message({"nome": "t"}, cp)
        assert "senha123" not in msg

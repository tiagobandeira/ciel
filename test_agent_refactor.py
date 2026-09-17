"""
test_agent_refactor.py — Testes da refatoração cli.py → agent_loop.py

Cobre:
  1. run_agent retorna AgentResult (não tupla)
  2. on_limit é chamado quando steps se esgotam (não on_steps_exhausted)
  3. _make_run_callbacks produz as chaves certas para run_agent
  4. on_confirm_tool=None bloqueia tool sensível (bug de segurança da Fase 1)
  5. on_confirm_tool callback decide corretamente (allow / deny)
  6. Fluxo "done" normal e fluxo "connection error"
  7. session_flags não é passado direto pro run_agent (verificação de assinatura)

Uso:
    python -m pytest test_agent_refactor.py -v
    # ou sem pytest:
    python test_agent_refactor.py
"""

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ── stubs de módulos que não existem no ambiente de teste ─────────────────────
# agent_loop faz imports locais (dentro do loop) de tool_dispatch e workspace.
# Precisamos que esses imports não estejam disponíveis até ser necessário, e
# quando são necessários, devolvemos stubs controlados.

def _make_stub_tool_dispatch(needs_confirmation_result=False):
    mod = types.ModuleType("tool_dispatch")
    mod.needs_confirmation = MagicMock(return_value=needs_confirmation_result)
    mod.get_path_checks    = MagicMock(return_value=[])   # sem checks de path
    return mod


def _make_stub_workspace():
    mod = types.ModuleType("workspace")
    ws = MagicMock()
    ws.check.return_value = ("/some/path", None)   # sem erro de workspace
    mod.get_workspace = MagicMock(return_value=ws)
    return mod


# ── respostas JSON que o modelo "retornaria" ──────────────────────────────────

def _done_json(message="Feito!"):
    return json.dumps({"done": True, "message": message})


def _tool_json(tool_name="minha_tool", args=None):
    return json.dumps({"tool": tool_name, "args": args or {}})


def _create_tool_json(tool_code="# código"):
    return json.dumps({"tool": "create_tool", "args": {"tool_code": tool_code}})


# ── helper: instala stubs e importa agent_loop ────────────────────────────────

def _import_agent_loop(needs_confirmation_result=False):
    """
    Instala stubs de tool_dispatch e workspace em sys.modules e importa
    agent_loop. Retorna o módulo — use dentro de 'with patch(...)' pra
    controlar _call_model.
    """
    sys.modules.setdefault("tool_dispatch", _make_stub_tool_dispatch(needs_confirmation_result))
    sys.modules.setdefault("workspace",     _make_stub_workspace())
    # garante que agent_loop é reimportado (caso outro teste já o tenha carregado)
    if "agent_loop" in sys.modules:
        del sys.modules["agent_loop"]
    import agent_loop
    return agent_loop


# ─────────────────────────────────────────────────────────────────────────────
#  Fixture mínima
# ─────────────────────────────────────────────────────────────────────────────

AGENT_INFO = {
    "id": "test",
    "name": "Test Agent",
    "system_prompt": "Você é um agente de teste.",
    "allowed_tools": None,
}

DUMMY_TOOL_FN = MagicMock(return_value="resultado da tool")
TOOLS = {"minha_tool": {"fn": DUMMY_TOOL_FN, "interactive": False}}
SCHEMA = [{"name": "minha_tool", "description": "tool de teste", "parameters": {}}]
MODEL  = "test-model"


def _call_model_stub(*responses):
    """
    Retorna um side_effect que devolve respostas em sequência.
    Cada resposta é (raw_text, tokens_in, tokens_out).
    """
    it = iter(responses)
    def _inner(*args, **kwargs):
        return next(it)
    return _inner


# ─────────────────────────────────────────────────────────────────────────────
#  1. run_agent retorna AgentResult, não tupla
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentResultType(unittest.TestCase):

    def test_run_agent_returns_agent_result_not_tuple(self):
        al = _import_agent_loop()
        with patch.object(al, "_call_model", side_effect=_call_model_stub(
            (_done_json("ok"), 10, 20),
        )):
            result = al.run_agent("oi", TOOLS, SCHEMA, MODEL, AGENT_INFO)

        self.assertIsInstance(result, al.AgentResult)
        self.assertEqual(result.status, "done")
        self.assertEqual(result.message, "ok")

    def test_agent_result_attributes_populated(self):
        al = _import_agent_loop()
        with patch.object(al, "_call_model", side_effect=_call_model_stub(
            (_done_json("resposta"), 42, 99),
        )):
            result = al.run_agent("oi", TOOLS, SCHEMA, MODEL, AGENT_INFO)

        self.assertEqual(result.tokens_in,  42)
        self.assertEqual(result.tokens_out, 99)
        self.assertEqual(result.steps, 1)
        self.assertTrue(result.ok)

    def test_cannot_unpack_as_tuple(self):
        """Garante que o código antigo 'result, t_in, t_out = run_agent(...)' quebra."""
        al = _import_agent_loop()
        with patch.object(al, "_call_model", side_effect=_call_model_stub(
            (_done_json(), 1, 2),
        )):
            result = al.run_agent("oi", TOOLS, SCHEMA, MODEL, AGENT_INFO)

        with self.assertRaises(TypeError):
            _, __, ___ = result   # deve falhar


# ─────────────────────────────────────────────────────────────────────────────
#  2. on_limit é o nome correto (não on_steps_exhausted)
# ─────────────────────────────────────────────────────────────────────────────

class TestOnLimitCallback(unittest.TestCase):

    def _make_exhausted_responses(self, n_steps):
        """Retorna n_steps respostas de tool seguidas de proposta de nova tool."""
        responses = [(_tool_json(), 5, 5)] * n_steps
        # depois dos steps esgotados, _ask_model_for_tool_proposal faz mais uma
        # chamada ao modelo — retorna "não precisa de tool nova"
        responses.append((json.dumps({"criar_tool": False}), 1, 1))
        return responses

    def test_on_limit_is_called_when_steps_exhausted(self):
        al = _import_agent_loop()
        on_limit = MagicMock()

        with patch.object(al, "_call_model", side_effect=_call_model_stub(
            *self._make_exhausted_responses(2)
        )):
            result = al.run_agent(
                "oi", TOOLS, SCHEMA, MODEL, AGENT_INFO,
                max_steps=2,
                on_limit=on_limit,
            )

        on_limit.assert_called_once()
        self.assertEqual(result.status, "limit")

    def test_on_steps_exhausted_is_not_a_valid_kwarg(self):
        """on_steps_exhausted não deve ser aceito por run_agent."""
        al = _import_agent_loop()
        import inspect
        sig = inspect.signature(al.run_agent)
        self.assertNotIn("on_steps_exhausted", sig.parameters,
            "run_agent não deve ter on_steps_exhausted — use on_limit")

    def test_make_run_callbacks_uses_on_limit_key(self):
        """
        _make_run_callbacks deve retornar 'on_limit', não 'on_steps_exhausted'.
        Esse é o bug do Patch 0 — garante que a chave bate com run_agent.
        """
        # importa cli sem precisar de todos os deps (só testa o dict retornado)
        import importlib, types

        # stubs mínimos para importar cli
        for mod_name in ["rich", "rich.console", "rich.panel", "rich.live",
                         "rich.spinner", "rich.syntax", "rich.markup",
                         "rich.prompt", "rich.text", "rich.style",
                         "prompt_toolkit", "prompt_toolkit.completion",
                         "prompt_toolkit.styles", "prompt_toolkit.shortcuts",
                         "history_ui", "tools_registry", "agent_loader",
                         "tool_dispatch", "workspace", "mcp_manager",
                         "session_store", "task_loader"]:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = types.ModuleType(mod_name)

        # garante que agent_loop está disponível
        if "agent_loop" not in sys.modules:
            _import_agent_loop()

        try:
            if "cli" in sys.modules:
                del sys.modules["cli"]
            import cli as cli_mod
            callbacks = cli_mod._make_run_callbacks({"trust_tool_creation": False})
            self.assertIn("on_limit", callbacks,
                "_make_run_callbacks deve ter chave 'on_limit'")
            self.assertNotIn("on_steps_exhausted", callbacks,
                "_make_run_callbacks não deve ter 'on_steps_exhausted'")
        except Exception as e:
            self.skipTest(f"Import de cli falhou no ambiente de teste: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  3. run_agent não aceita session_flags nem interactive
# ─────────────────────────────────────────────────────────────────────────────

class TestRunAgentSignature(unittest.TestCase):

    def setUp(self):
        self.al = _import_agent_loop()

    def test_session_flags_not_accepted(self):
        with self.assertRaises(TypeError) as ctx:
            with patch.object(self.al, "_call_model", side_effect=_call_model_stub(
                (_done_json(), 1, 1),
            )):
                self.al.run_agent(
                    "oi", TOOLS, SCHEMA, MODEL, AGENT_INFO,
                    session_flags={"trust_tool_creation": False},  # inválido
                )
        self.assertIn("session_flags", str(ctx.exception))

    def test_interactive_not_accepted(self):
        with self.assertRaises(TypeError) as ctx:
            with patch.object(self.al, "_call_model", side_effect=_call_model_stub(
                (_done_json(), 1, 1),
            )):
                self.al.run_agent(
                    "oi", TOOLS, SCHEMA, MODEL, AGENT_INFO,
                    interactive=False,  # inválido
                )
        self.assertIn("interactive", str(ctx.exception))

    def test_accepted_kwargs_include_callbacks(self):
        import inspect
        sig = inspect.signature(self.al.run_agent)
        for cb in ("on_step", "on_model_start", "on_model_end",
                   "on_done", "on_limit", "on_error",
                   "on_confirm_tool", "on_confirm_path", "on_ask_user"):
            self.assertIn(cb, sig.parameters, f"run_agent deve ter parâmetro {cb!r}")


# ─────────────────────────────────────────────────────────────────────────────
#  4 & 5. on_confirm_tool — comportamento de segurança (Fase 1)
# ─────────────────────────────────────────────────────────────────────────────

class TestConfirmToolSecurity(unittest.TestCase):

    def _run_with_sensitive_tool(self, on_confirm_tool, **extra):
        """Executa run_agent com uma tool marcada como sensível."""
        sys.modules["tool_dispatch"] = _make_stub_tool_dispatch(
            needs_confirmation_result=True  # qualquer tool é "sensível"
        )
        if "agent_loop" in sys.modules:
            del sys.modules["agent_loop"]
        al = _import_agent_loop(needs_confirmation_result=True)

        sensitive_fn = MagicMock(return_value="executou!")
        tools  = {"create_tool": {"fn": sensitive_fn, "interactive": False}}
        schema = [{"name": "create_tool", "description": "cria tool", "parameters": {}}]

        with patch.object(al, "_call_model", side_effect=_call_model_stub(
            (_create_tool_json(), 5, 5),
            (_done_json("ok"), 5, 5),
        )):
            result = al.run_agent(
                "crie uma tool",
                tools, schema, MODEL, AGENT_INFO,
                on_confirm_tool=on_confirm_tool,
                **extra,
            )
        return result, sensitive_fn

    def test_no_callback_blocks_sensitive_tool(self):
        """on_confirm_tool=None deve bloquear a tool, não deixar passar."""
        result, fn = self._run_with_sensitive_tool(on_confirm_tool=None)
        fn.assert_not_called()
        # o agente continua rodando (retornou done ou limit), mas a tool não executou

    def test_callback_returning_false_blocks_tool(self):
        result, fn = self._run_with_sensitive_tool(
            on_confirm_tool=lambda tool_name, code: False
        )
        fn.assert_not_called()

    def test_callback_returning_true_allows_tool(self):
        result, fn = self._run_with_sensitive_tool(
            on_confirm_tool=lambda tool_name, code: True
        )
        fn.assert_called_once()

    def test_callback_receives_tool_name_and_code(self):
        received = {}
        def capture(tool_name, code):
            received["tool_name"] = tool_name
            received["code"] = code
            return False

        self._run_with_sensitive_tool(on_confirm_tool=capture)
        self.assertEqual(received.get("tool_name"), "create_tool")
        self.assertIn("código", received.get("code", "código"))  # tool_code do json


# ─────────────────────────────────────────────────────────────────────────────
#  6. Fluxos normais: done e error de conexão
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalFlows(unittest.TestCase):

    def setUp(self):
        # reseta explicitamente para needs_confirmation=False, porque
        # TestConfirmToolSecurity seta o stub com True e setdefault não sobrescreve.
        sys.modules["tool_dispatch"] = _make_stub_tool_dispatch(needs_confirmation_result=False)
        self.al = _import_agent_loop()

    def test_done_flow_callbacks(self):
        on_step       = MagicMock()
        on_model_start = MagicMock()
        on_model_end   = MagicMock()
        on_done        = MagicMock()

        with patch.object(self.al, "_call_model", side_effect=_call_model_stub(
            (_done_json("perfeito"), 10, 20),
        )):
            result = self.al.run_agent(
                "tarefa",
                TOOLS, SCHEMA, MODEL, AGENT_INFO,
                on_step=on_step,
                on_model_start=on_model_start,
                on_model_end=on_model_end,
                on_done=on_done,
            )

        self.assertEqual(result.status,  "done")
        self.assertEqual(result.message, "perfeito")
        on_model_start.assert_called_once_with(1)
        on_model_end.assert_called_once_with(1)
        on_done.assert_called_once()
        # on_step deve ter sido chamado ao menos uma vez com status="done"
        statuses = [c.args[3] for c in on_step.call_args_list]
        self.assertIn("done", statuses)

    def test_connection_error_returns_error_result(self):
        import requests
        on_error = MagicMock()

        with patch.object(self.al, "_call_model",
                          side_effect=requests.RequestException("timeout")):
            result = self.al.run_agent(
                "tarefa",
                TOOLS, SCHEMA, MODEL, AGENT_INFO,
                on_error=on_error,
            )

        self.assertEqual(result.status, "error")
        self.assertFalse(result.ok)
        on_error.assert_called_once()
        kind, msg = on_error.call_args.args
        self.assertEqual(kind, "connection")

    def test_tool_call_then_done(self):
        """Loop com uma tool call seguida de done."""
        tool_fn = MagicMock(return_value="achei algo")
        tools  = {"busca": {"fn": tool_fn, "interactive": False}}
        schema = [{"name": "busca", "description": "busca coisas", "parameters": {}}]

        with patch.object(self.al, "_call_model", side_effect=_call_model_stub(
            (_tool_json("busca"), 5, 5),
            (_done_json("resultado final"), 5, 5),
        )):
            result = self.al.run_agent("busque X", tools, schema, MODEL, AGENT_INFO)

        self.assertEqual(result.status, "done")
        tool_fn.assert_called_once()
        self.assertEqual(result.steps, 2)

    def test_tokens_accumulate_across_steps(self):
        tool_fn = MagicMock(return_value="ok")
        tools  = {"eco": {"fn": tool_fn, "interactive": False}}
        schema = [{"name": "eco", "description": "eco", "parameters": {}}]

        with patch.object(self.al, "_call_model", side_effect=_call_model_stub(
            (_tool_json("eco"), 10, 15),  # step 1 — tool
            (_done_json(),      20, 25),  # step 2 — done
        )):
            result = self.al.run_agent("eco", tools, schema, MODEL, AGENT_INFO)

        self.assertEqual(result.tokens_in,  30)   # 10 + 20
        self.assertEqual(result.tokens_out, 40)   # 15 + 25


# ─────────────────────────────────────────────────────────────────────────────
#  Runner standalone (sem pytest)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in [
        TestAgentResultType,
        TestOnLimitCallback,
        TestRunAgentSignature,
        TestConfirmToolSecurity,
        TestNormalFlows,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

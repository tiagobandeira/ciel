"""
tests/test_core/test_task_runner.py

Cobre load_task (cli.py), build_task_prompt, e as peças internas do
task_runner: _extract_text, _validate_tool_groups, TaskCheckpoint e run_task.

run_task é testado com modelo mockado — sem precisar do Ollama.
O mock simula o planner retornando um plano JSON e as respostas das ações.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch


# ── load_task (cli.py) ────────────────────────────────────────────────────────

class TestLoadTask:
    @pytest.fixture
    def tasks_dir(self, tmp_path):
        d = tmp_path / "tasks"
        d.mkdir()
        return d

    def _write(self, tasks_dir, filename, content):
        p = tasks_dir / filename
        p.write_text(content, encoding="utf-8")
        return p

    def test_task_valida_campos_basicos(self, tasks_dir):
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
## task: minha-task

objetivo: fazer alguma coisa útil

ações:
- passo 1 [tool: calculator]
- passo 2 [tool: read_file]

resultado esperado: arquivo gerado com sucesso
""")
        task = load_task(p)
        assert task is not None
        assert task["nome"] == "minha-task"
        assert task["objetivo"] == "fazer alguma coisa útil"
        assert task["resultado"] == "arquivo gerado com sucesso"

    def test_task_valida_acoes(self, tasks_dir):
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
## task: minha-task

ações:
- passo 1
- passo 2
- passo 3
""")
        task = load_task(p)
        assert len(task["acoes"]) == 3

    def test_anotacao_tool_preservada_na_acao(self, tasks_dir):
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
## task: com-tool

ações:
- buscar dados [tool: web_search_extended]
""")
        task = load_task(p)
        assert "[tool: web_search_extended]" in task["acoes"][0]

    def test_campo_grupo_presente(self, tasks_dir):
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
## task: com-grupo

grupo: calculator, read_file

ações:
- calcular algo
""")
        task = load_task(p)
        assert task["grupo"] == "calculator, read_file"

    def test_campo_grupo_ausente_retorna_string_vazia(self, tasks_dir):
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
## task: sem-grupo

ações:
- uma ação
""")
        task = load_task(p)
        assert task["grupo"] == ""

    def test_sem_nome_retorna_none(self, tasks_dir):
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
objetivo: algo

ações:
- passo 1
""")
        assert load_task(p) is None

    def test_sem_acoes_retorna_none(self, tasks_dir):
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
## task: sem-acoes

objetivo: algo
""")
        assert load_task(p) is None

    def test_arquivo_inexistente_retorna_none(self, tmp_path):
        from cli import load_task
        assert load_task(tmp_path / "nao_existe.md") is None

    def test_acoes_com_alias_acoes(self, tasks_dir):
        """Aceita 'acoes:' sem acento."""
        from cli import load_task
        p = self._write(tasks_dir, "t.md", """\
## task: sem-acento

acoes:
- passo 1
""")
        task = load_task(p)
        assert task is not None
        assert len(task["acoes"]) == 1


# ── build_task_prompt ─────────────────────────────────────────────────────────

class TestBuildTaskPrompt:
    @pytest.fixture
    def task(self):
        return {
            "nome": "relatorio-diario",
            "objetivo": "gerar relatório das tarefas do dia",
            "acoes": ["buscar dados", "formatar resultado", "salvar arquivo"],
            "resultado": "relatório em markdown",
            "grupo": "",
        }

    def test_nome_no_prompt(self, task):
        from cli import build_task_prompt
        prompt = build_task_prompt(task)
        assert "relatorio-diario" in prompt

    def test_objetivo_no_prompt(self, task):
        from cli import build_task_prompt
        prompt = build_task_prompt(task)
        assert "gerar relatório das tarefas do dia" in prompt

    def test_acoes_numeradas_em_ordem(self, task):
        from cli import build_task_prompt
        prompt = build_task_prompt(task)
        assert "1. buscar dados" in prompt
        assert "2. formatar resultado" in prompt
        assert "3. salvar arquivo" in prompt

    def test_resultado_esperado_no_prompt(self, task):
        from cli import build_task_prompt
        prompt = build_task_prompt(task)
        assert "relatório em markdown" in prompt

    def test_instrucao_de_ordem(self, task):
        from cli import build_task_prompt
        prompt = build_task_prompt(task)
        assert "ordem" in prompt.lower()


# ── _extract_text ─────────────────────────────────────────────────────────────

class TestExtractText:
    def test_texto_puro_retornado_diretamente(self):
        from task_runner import _extract_text
        assert _extract_text("olá mundo") == "olá mundo"

    def test_json_com_message(self):
        from task_runner import _extract_text
        raw = json.dumps({"done": True, "message": "resultado final"})
        assert _extract_text(raw) == "resultado final"

    def test_json_com_fence_markdown(self):
        from task_runner import _extract_text
        raw = "```json\n" + json.dumps({"done": True, "message": "ok"}) + "\n```"
        assert _extract_text(raw) == "ok"

    def test_fence_sem_linguagem(self):
        from task_runner import _extract_text
        raw = "```\nconteúdo livre\n```"
        assert _extract_text(raw) == "conteúdo livre"

    def test_string_vazia_retorna_vazia(self):
        from task_runner import _extract_text
        assert _extract_text("") == ""

    def test_json_sem_message_retorna_json_string(self):
        from task_runner import _extract_text
        raw = json.dumps({"tool": "calculator", "args": {}})
        # não tem "message" → retorna o texto bruto (sem fence)
        result = _extract_text(raw)
        assert "calculator" in result

    def test_texto_com_whitespace(self):
        from task_runner import _extract_text
        assert _extract_text("  texto com espaços  ") == "texto com espaços"


# ── _validate_tool_groups ─────────────────────────────────────────────────────

class TestValidateToolGroups:
    def _a(self, id_, type_, tool=None):
        """Helper pra criar action dict."""
        a = {"id": id_, "type": type_, "descricao": f"ação {id_}"}
        if tool:
            a["tool"] = tool
        return a

    def test_bloco_homogeneo_sem_restricao_mantido(self):
        from task_runner import _validate_tool_groups
        actions = [
            self._a("a1", "tool", "calculator"),
            self._a("a2", "tool", "calculator"),
        ]
        result = _validate_tool_groups(actions, allowed_tools=None)
        assert all(a["type"] == "tool" for a in result)
        assert len(result) == 2

    def test_bloco_homogeneo_com_tool_permitida_mantido(self):
        from task_runner import _validate_tool_groups
        actions = [
            self._a("a1", "tool", "calculator"),
            self._a("a2", "tool", "calculator"),
        ]
        result = _validate_tool_groups(actions, allowed_tools={"calculator"})
        assert all(a["type"] == "tool" for a in result)

    def test_bloco_misto_rebaixado_para_model(self):
        from task_runner import _validate_tool_groups
        actions = [
            self._a("a1", "tool", "calculator"),
            self._a("a2", "tool", "read_file"),  # tool diferente no bloco
        ]
        result = _validate_tool_groups(actions, allowed_tools=None)
        assert len(result) == 1
        assert result[0]["type"] == "model"

    def test_tool_nao_permitida_rebaixada_para_model(self):
        from task_runner import _validate_tool_groups
        actions = [
            self._a("a1", "tool", "web_search_extended"),
            self._a("a2", "tool", "web_search_extended"),
        ]
        # web_search_extended não está em allowed_tools
        result = _validate_tool_groups(actions, allowed_tools={"calculator"})
        assert len(result) == 1
        assert result[0]["type"] == "model"

    def test_acoes_model_nao_afetadas(self):
        from task_runner import _validate_tool_groups
        actions = [
            self._a("a1", "model"),
            self._a("a2", "model"),
        ]
        result = _validate_tool_groups(actions, allowed_tools=None)
        assert all(a["type"] == "model" for a in result)
        assert len(result) == 2

    def test_mistura_tool_e_model(self):
        from task_runner import _validate_tool_groups
        actions = [
            self._a("a1", "tool", "calculator"),
            self._a("a2", "tool", "calculator"),
            self._a("a3", "model"),
            self._a("a4", "tool", "read_file"),
        ]
        result = _validate_tool_groups(actions, allowed_tools=None)
        # primeiro bloco (calculator, calculator) → mantém como tools
        # model → mantém
        # último (read_file solitário, homogêneo) → mantém como tool
        tipos = [a["type"] for a in result]
        assert tipos.count("tool") >= 2
        assert "model" in tipos

    def test_lista_vazia_retorna_vazia(self):
        from task_runner import _validate_tool_groups
        assert _validate_tool_groups([], allowed_tools=None) == []

    def test_rebaixado_guarda_ids_originais(self):
        from task_runner import _validate_tool_groups
        actions = [
            self._a("a1", "tool", "calculator"),
            self._a("a2", "tool", "read_file"),
        ]
        result = _validate_tool_groups(actions, allowed_tools={"calculator"})
        rebaixado = result[0]
        assert "_rebaixado_de" in rebaixado
        assert "a1" in rebaixado["_rebaixado_de"]
        assert "a2" in rebaixado["_rebaixado_de"]


# ── TaskCheckpoint ────────────────────────────────────────────────────────────

class TestTaskCheckpoint:
    @pytest.fixture
    def actions(self):
        return [
            {"id": "a1", "type": "tool", "descricao": "buscar dados",    "tool": "calculator"},
            {"id": "a2", "type": "model", "descricao": "analisar dados"},
            {"id": "a3", "type": "tool", "descricao": "salvar resultado", "tool": "write_file"},
        ]

    def test_mark_done_registra_resultado(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        cp.mark_done("a1", "resultado real")
        assert "a1" in cp.completed
        assert cp.results["a1"] == "resultado real"

    def test_mark_failed_registra_erro(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        cp.mark_failed("a2", "conexão recusada")
        assert "a2" in cp.failed
        assert "[ERRO]" in cp.results["a2"]

    def test_mark_skipped_registra_skip(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        cp.mark_skipped("a3")
        assert "a3" in cp.skipped

    def test_summary_inclui_resultados_bem_sucedidos(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        cp.mark_done("a1", "42")
        summary = cp.summary()
        assert "buscar dados" in summary
        assert "42" in summary

    def test_summary_omite_erros(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        cp.mark_failed("a1", "erro grave")
        summary = cp.summary()
        # Erros não devem aparecer no resumo entregue ao modelo
        assert "erro grave" not in summary

    def test_summary_omite_skipped(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        cp.mark_skipped("a1")
        summary = cp.summary()
        assert "a1" not in summary

    def test_to_dict_estrutura(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        cp.mark_done("a1", "ok")
        cp.mark_failed("a2", "falhou")
        d = cp.to_dict()
        assert "completed" in d
        assert "failed" in d
        assert "skipped" in d
        assert "results" in d
        assert "a1" in d["completed"]
        assert "a2" in d["failed"]

    def test_resultado_sem_acoes_summary_generico(self, actions):
        from task_runner import TaskCheckpoint
        cp = TaskCheckpoint(actions)
        # nenhum resultado → summary mínimo
        summary = cp.summary()
        assert isinstance(summary, str)


# ── _build_final_message ──────────────────────────────────────────────────────

class TestBuildFinalMessage:
    def _make_actions(self):
        return [
            {"id": "a1", "type": "tool",  "descricao": "buscar"},
            {"id": "a2", "type": "model", "descricao": "analisar"},
            {"id": "a3", "type": "tool",  "descricao": "salvar"},
        ]

    def test_usa_ultimo_resultado_model(self):
        from task_runner import TaskCheckpoint, _build_final_message
        actions = self._make_actions()
        cp = TaskCheckpoint(actions)
        cp.mark_done("a2", "análise concluída com sucesso")
        task = {"nome": "minha-task"}
        msg = _build_final_message(task, cp)
        assert "análise concluída" in msg

    def test_fallback_concatena_resultados_uteis(self):
        from task_runner import TaskCheckpoint, _build_final_message
        actions = self._make_actions()
        cp = TaskCheckpoint(actions)
        cp.mark_done("a1", "dado coletado")
        cp.mark_done("a3", "arquivo salvo")
        task = {"nome": "minha-task"}
        msg = _build_final_message(task, cp)
        assert "dado coletado" in msg or "arquivo salvo" in msg

    def test_sem_resultados_uteis_retorna_fallback_generico(self):
        from task_runner import TaskCheckpoint, _build_final_message
        actions = self._make_actions()
        cp = TaskCheckpoint(actions)
        task = {"nome": "minha-task"}
        msg = _build_final_message(task, cp)
        assert "minha-task" in msg

    def test_erros_nao_usados_como_resposta_final(self):
        from task_runner import TaskCheckpoint, _build_final_message
        actions = self._make_actions()
        cp = TaskCheckpoint(actions)
        cp.mark_failed("a2", "erro interno crítico")
        task = {"nome": "t"}
        msg = _build_final_message(task, cp)
        assert "erro interno crítico" not in msg


# ── run_task (com modelo mockado) ─────────────────────────────────────────────

class TestRunTask:
    """
    Testa run_task com _call_model e _request_plan mockados —
    sem precisar do Ollama rodando.
    """

    @pytest.fixture
    def task_sem_grupo(self):
        return {
            "nome": "test-task",
            "objetivo": "calcular 2+2",
            "acoes": ["calcular a soma"],
            "resultado": "resultado da soma",
            "grupo": "",   # sem grupo → delega pro run_agent direto
        }

    @pytest.fixture
    def task_com_grupo(self):
        return {
            "nome": "task-com-fila",
            "objetivo": "calcular múltiplos valores",
            "acoes": [
                "calcular 2+2 [tool: calculator]",
                "calcular 3+3 [tool: calculator]",
            ],
            "resultado": "resultados calculados",
            "grupo": "calculator",
        }

    @pytest.fixture
    def tools(self):
        import tools_registry
        return tools_registry.load_tools()

    @pytest.fixture
    def schema(self, tools):
        from tools_registry import tools_schema
        return tools_schema(tools)

    @pytest.fixture
    def agent_info(self):
        return {
            "id": "general",
            "name": "General",
            "description": "Agente de teste",
            "system_prompt": "Você é um assistente de teste.",
            "allowed_tools": None,
            "allowed_mcp_servers": [],
        }

    def _done(self, msg="tarefa concluída"):
        return json.dumps({"done": True, "message": msg}), 5, 10

    def _tool_call(self, tool, args):
        return json.dumps({"tool": tool, "args": args}), 5, 10

    def test_sem_grupo_delega_run_agent(
        self, task_sem_grupo, tools, schema, agent_info
    ):
        """Task sem 'grupo' não usa planner — delega direto pro run_agent."""
        from task_runner import run_task

        with patch("agent_loop._call_model", return_value=self._done("ok sem grupo")):
            result = run_task(
                task_sem_grupo, tools, schema,
                model="mock", agent_info=agent_info,
            )
        assert result.status == "done"

    def test_com_grupo_usa_planner(
        self, task_com_grupo, tools, schema, agent_info
    ):
        """Task com 'grupo' usa planner e executa fila de tools."""
        from task_runner import run_task

        plano = {
            "actions": [
                {"id": "a1", "type": "tool", "tool": "calculator",
                 "args": {"expression": "2+2"}, "descricao": "calcular 2+2"},
                {"id": "a2", "type": "tool", "tool": "calculator",
                 "args": {"expression": "3+3"}, "descricao": "calcular 3+3"},
            ]
        }

        with patch("task_runner._request_plan", return_value=plano["actions"]), \
             patch("agent_loop._call_model", return_value=self._done("resultado: 4 e 6")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
            )
        assert result.status == "done"

    def test_plano_vazio_cai_em_run_agent(
        self, task_com_grupo, tools, schema, agent_info
    ):
        """Se o planner falhar (None), run_task delega pro run_agent."""
        from task_runner import run_task

        with patch("task_runner._request_plan", return_value=None), \
             patch("agent_loop._call_model", return_value=self._done("fallback ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
            )
        assert result.status == "done"

    def test_plano_so_com_model_cai_em_run_agent(
        self, task_com_grupo, tools, schema, agent_info
    ):
        """Plano sem ações 'tool' não usa fila — delega pro run_agent."""
        from task_runner import run_task

        plano = [
            {"id": "a1", "type": "model", "descricao": "analisar"},
        ]

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=self._done("análise ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
            )
        assert result.status == "done"

    def test_max_steps_retorna_limit(
        self, task_com_grupo, tools, schema, agent_info
    ):
        """Com max_steps muito baixo, run_task deve retornar status 'limit'."""
        from task_runner import run_task

        # Plano com muitas ações model para esgotar os steps
        plano = [
            {"id": f"a{i}", "type": "model", "descricao": f"ação {i}"}
            for i in range(10)
        ]

        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model", return_value=self._done("ok")):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                max_steps=2,
            )
        assert result.status in ("limit", "done")

    def test_acumula_tokens(
        self, task_com_grupo, tools, schema, agent_info
    ):
        """tokens_in e tokens_out devem ser acumulados entre sub-agentes."""
        from task_runner import run_task

        plano = [
            {"id": "a1", "type": "tool", "tool": "calculator",
             "args": {"expression": "1+1"}, "descricao": "calcular"},
        ]

        # consolidador retorna tokens
        with patch("task_runner._request_plan", return_value=plano), \
             patch("agent_loop._call_model",
                   return_value=(json.dumps({"done": True, "message": "ok"}), 7, 13)):
            result = run_task(
                task_com_grupo, tools, schema,
                model="mock", agent_info=agent_info,
            )
        # tokens_in e tokens_out devem ser > 0 (vieram do consolidador)
        assert result.tokens_in >= 0
        assert result.tokens_out >= 0

    def test_callback_on_step_chamado(
        self, task_sem_grupo, tools, schema, agent_info
    ):
        """on_step deve ser chamado ao longo da execução."""
        from task_runner import run_task

        steps_capturados = []

        def on_step(step_n, label, desc, kind):
            steps_capturados.append((step_n, label, kind))

        with patch("agent_loop._call_model", return_value=self._done("ok")):
            run_task(
                task_sem_grupo, tools, schema,
                model="mock", agent_info=agent_info,
                on_step=on_step,
            )
        assert len(steps_capturados) > 0

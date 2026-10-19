"""tests/test_core/test_cli_profile.py

Cobre o roteamento de perfil da CLI sem rede: `_run_agent_session` e o
filtro de tools do build.
"""

from types import SimpleNamespace

import pytest

import cli
import environment
from agent_loop import AgentResult


@pytest.fixture(autouse=True)
def reset_session(monkeypatch):
    monkeypatch.setattr(cli, "_SESSION", {
        "perfil": "local",
        "label": "gemma4:cloud",
        "client": None,
        "roles": None,
    })


class TestRunAgentSession:
    def test_local_usa_model_e_sem_client(self, monkeypatch):
        calls = {}

        def fake_run_agent(user_input, tools, schema, model, agent_info, **kwargs):
            calls.update(model=model, kwargs=kwargs)
            return AgentResult("done", "ok")

        monkeypatch.setattr(cli, "run_agent", fake_run_agent)
        cli._run_agent_session("oi", {}, [], "gemma4:cloud", {"id": "x"})

        assert calls["model"] == "gemma4:cloud"
        assert calls["kwargs"]["profile"] == "local"
        assert calls["kwargs"]["model_client"] is None

    def test_build_usa_client_e_model_vazio(self, monkeypatch):
        calls = {}
        sentinel = object()

        def fake_run_agent(user_input, tools, schema, model, agent_info, **kwargs):
            calls.update(model=model, kwargs=kwargs)
            return AgentResult("done", "ok")

        monkeypatch.setattr(cli, "run_agent", fake_run_agent)
        cli._SESSION.update(perfil="build", client=sentinel)

        cli._run_agent_session("oi", {}, [], "gemma4:cloud", {"id": "x"})

        assert calls["model"] == ""
        assert calls["kwargs"]["profile"] == "build"
        assert calls["kwargs"]["model_client"] is sentinel


class TestToolsDoPerfil:
    def test_build_esconde_secondary_model(self, monkeypatch):
        all_tools = {
            "read_file": {"fn": lambda: "", "description": "lê"},
            "secondary_model": {"fn": lambda: "", "description": "delega"},
        }
        monkeypatch.setattr(cli, "load_tools", lambda: all_tools)
        cli._SESSION.update(perfil="build")

        tools, schema = cli._reload_tools({"allowed_tools": None}, safe=False)

        assert "read_file" in tools
        assert "secondary_model" not in tools
        assert all(item.get("name") != "secondary_model" for item in schema)

    def test_local_mantem_secondary_model(self, monkeypatch):
        all_tools = {
            "secondary_model": {"fn": lambda: "", "description": "delega"},
        }
        monkeypatch.setattr(cli, "load_tools", lambda: all_tools)
        cli._SESSION.update(perfil="local")

        tools, _ = cli._reload_tools({"allowed_tools": None}, safe=False)

        assert "secondary_model" in tools


class TestEnvironmentBuild:
    def test_build_nao_verifica_ollama(self, monkeypatch):
        roles = SimpleNamespace(
            perfil="build",
            orchestrator=SimpleNamespace(is_local=False, label="cloud"),
        )
        monkeypatch.setattr("llm.roles.load_roles", lambda *a, **k: roles)

        chamou = {"ollama": False}
        monkeypatch.setattr(
            environment, "_check_ollama_running",
            lambda: chamou.update(ollama=True) or (False, []),
        )

        assert environment.check_environment("modelo", profile="build") == []
        assert chamou["ollama"] is False

    def test_build_sem_provider_sai(self, monkeypatch):
        roles = SimpleNamespace(
            perfil="build",
            orchestrator=SimpleNamespace(is_local=True, label="local"),
        )
        monkeypatch.setattr("llm.roles.load_roles", lambda *a, **k: roles)

        with pytest.raises(SystemExit):
            environment.check_environment("modelo", profile="build")

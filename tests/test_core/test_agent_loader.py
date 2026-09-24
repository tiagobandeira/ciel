"""
tests/test_core/test_agent_loader.py

Cobre load_agent, list_agents, filter_tools e filter_mcp_tools.
Todos os testes usam agentes sintéticos em tmp_path — não dependem
dos agentes reais do projeto, então rodam independente do estado de /agents/.
"""

import sys
import pytest
from pathlib import Path

import agent_loader as al


# ── fixture base: diretório de agentes temporário ────────────────────────────

@pytest.fixture
def agents_dir(tmp_path, monkeypatch):
    """
    Substitui AGENTS_DIR por um diretório temporário e restaura depois.
    Cada teste recebe uma pasta limpa com agentes sintéticos.
    """
    d = tmp_path / "agents"
    d.mkdir()
    orig = al.AGENTS_DIR
    al.AGENTS_DIR = d
    yield d
    al.AGENTS_DIR = orig


def write_agent(agents_dir: Path, name: str, content: str) -> Path:
    """Cria um arquivo .md de agente no diretório temporário."""
    p = agents_dir / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


# ── agentes sintéticos (strings) ─────────────────────────────────────────────

AGENT_COMPLETO = """\
# Assistente de Teste

## Persona
Você é um agente de teste. Seja direto e conciso.

## Tools permitidas
calculator
read_file

## Servidores MCP
nenhum

## Comportamento
- Sempre confirme antes de executar
- Use português

## Skills
code-review: sugerida
data-analysis: opcional
"""

AGENT_TOOLS_TODAS = """\
# Agente Geral

## Persona
Agente com acesso total a todas as tools.

## Tools permitidas
todas
"""

AGENT_SEM_FORMATO = """\
# Sem Formato Custom

## Persona
Este agente não define formato de resposta customizado.
"""

AGENT_COM_FORMATO = """\
# Com Formato Custom

## Persona
Este agente define seu próprio formato.

## Formato de resposta
Responda sempre em XML: <resposta>...</resposta>
"""

AGENT_MCP_TODOS = """\
# MCP Todos

## Persona
Pode usar todos os servidores MCP.

## Servidores MCP
todos
"""

AGENT_MCP_LISTA = """\
# MCP Restrito

## Persona
Só pode usar o servidor telegram.

## Servidores MCP
telegram
"""

AGENT_SKILL_SEM_NIVEL = """\
# Skill Sem Nível

## Persona
Agente com skill sem nível explícito.

## Skills
code-review
"""

AGENT_SKILL_NIVEL_INVALIDO = """\
# Skill Nível Inválido

## Persona
Agente com nível de skill inválido.

## Skills
code-review: invalido
"""

AGENT_MINIMO = """\
# Agente Mínimo

## Persona
Descrição mínima.
"""

AGENT_SEM_NOME = """\
## Persona
Sem título principal.
"""

AGENT_SEM_ACOES = """\
# Sem Ações
"""


# ── carregamento e campos obrigatórios ───────────────────────────────────────

class TestLoadAgentCamposBasicos:
    def test_name(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert info["name"] == "Assistente de Teste"

    def test_id_igual_ao_nome_do_arquivo(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert info["id"] == "teste"

    def test_system_prompt_nao_vazio(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert len(info["system_prompt"]) > 0

    def test_persona_no_system_prompt(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert "agente de teste" in info["system_prompt"].lower()

    def test_comportamento_no_system_prompt(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert "Sempre confirme" in info["system_prompt"]

    def test_description_primeira_linha_da_persona(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert "agente de teste" in info["description"].lower()

    def test_agente_inexistente_lanca_file_not_found(self, agents_dir):
        with pytest.raises(FileNotFoundError, match="nao_existe"):
            al.load_agent("nao_existe")

    def test_agente_inexistente_menciona_disponiveis(self, agents_dir):
        write_agent(agents_dir, "geral", AGENT_MINIMO)
        with pytest.raises(FileNotFoundError, match="geral"):
            al.load_agent("outro")


# ── allowed_tools ─────────────────────────────────────────────────────────────

class TestAllowedTools:
    def test_tools_todas_retorna_none(self, agents_dir):
        write_agent(agents_dir, "geral", AGENT_TOOLS_TODAS)
        info = al.load_agent("geral")
        assert info["allowed_tools"] is None

    def test_tools_lista_retorna_lista(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert isinstance(info["allowed_tools"], list)
        assert "calculator" in info["allowed_tools"]
        assert "read_file" in info["allowed_tools"]

    def test_tools_lista_nao_contem_ferramenta_nao_listada(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert "web_search_extended" not in info["allowed_tools"]

    def test_parse_allowed_tools_todas(self):
        assert al._parse_allowed_tools("todas") is None

    def test_parse_allowed_tools_all(self):
        assert al._parse_allowed_tools("all") is None

    def test_parse_allowed_tools_asterisco(self):
        assert al._parse_allowed_tools("*") is None

    def test_parse_allowed_tools_lista_virgula(self):
        result = al._parse_allowed_tools("calculator, read_file, write_file")
        assert result == ["calculator", "read_file", "write_file"]

    def test_parse_allowed_tools_lista_newline(self):
        result = al._parse_allowed_tools("calculator\nread_file\nwrite_file")
        assert result == ["calculator", "read_file", "write_file"]


# ── servidores MCP ────────────────────────────────────────────────────────────

class TestServidoresMCP:
    def test_mcp_nenhum_retorna_lista_vazia(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        assert info["allowed_mcp_servers"] == []

    def test_mcp_todos_retorna_none(self, agents_dir):
        write_agent(agents_dir, "mcp_todos", AGENT_MCP_TODOS)
        info = al.load_agent("mcp_todos")
        assert info["allowed_mcp_servers"] is None

    def test_mcp_lista_retorna_servidores(self, agents_dir):
        write_agent(agents_dir, "mcp_restrito", AGENT_MCP_LISTA)
        info = al.load_agent("mcp_restrito")
        assert info["allowed_mcp_servers"] == ["telegram"]

    def test_parse_mcp_nenhum(self):
        assert al._parse_allowed_mcp_servers("nenhum") == []

    def test_parse_mcp_none(self):
        assert al._parse_allowed_mcp_servers("none") == []

    def test_parse_mcp_todos(self):
        assert al._parse_allowed_mcp_servers("todos") is None

    def test_parse_mcp_all(self):
        assert al._parse_allowed_mcp_servers("all") is None


# ── formato de resposta ───────────────────────────────────────────────────────

class TestFormatoResposta:
    def test_sem_formato_injeta_default_json(self, agents_dir):
        write_agent(agents_dir, "sem_fmt", AGENT_SEM_FORMATO)
        info = al.load_agent("sem_fmt")
        assert "JSON" in info["system_prompt"]
        assert '{"tool"' in info["system_prompt"] or '"tool"' in info["system_prompt"]

    def test_com_formato_nao_injeta_default(self, agents_dir):
        write_agent(agents_dir, "com_fmt", AGENT_COM_FORMATO)
        info = al.load_agent("com_fmt")
        # O formato customizado deve estar presente
        assert "XML" in info["system_prompt"]
        # O DEFAULT_JSON_FORMAT não deve ter sido injetado além do customizado
        # (o default tem o texto "Responda SEMPRE em JSON puro")
        assert "Responda SEMPRE em JSON puro" not in info["system_prompt"]


# ── skills ────────────────────────────────────────────────────────────────────

class TestSkills:
    def test_skills_parseadas(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        nomes = [s["name"] for s in info["skills"]]
        assert "code-review" in nomes
        assert "data-analysis" in nomes

    def test_skill_nivel_correto(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        levels = {s["name"]: s["level"] for s in info["skills"]}
        assert levels["code-review"] == "sugerida"
        assert levels["data-analysis"] == "opcional"

    def test_skill_sem_nivel_usa_default(self, agents_dir):
        write_agent(agents_dir, "skill_sem_nivel", AGENT_SKILL_SEM_NIVEL)
        info = al.load_agent("skill_sem_nivel")
        assert info["skills"][0]["level"] == al._DEFAULT_SKILL_LEVEL

    def test_skill_nivel_invalido_usa_default(self, agents_dir, capsys):
        write_agent(agents_dir, "skill_invalido", AGENT_SKILL_NIVEL_INVALIDO)
        info = al.load_agent("skill_invalido")
        assert info["skills"][0]["level"] == al._DEFAULT_SKILL_LEVEL

    def test_skill_nivel_invalido_avisa_stderr(self, agents_dir, capsys):
        write_agent(agents_dir, "skill_invalido", AGENT_SKILL_NIVEL_INVALIDO)
        al.load_agent("skill_invalido")
        captured = capsys.readouterr()
        assert "invalido" in captured.err.lower() or "nível" in captured.err

    def test_sem_skills_retorna_lista_vazia(self, agents_dir):
        write_agent(agents_dir, "minimo", AGENT_MINIMO)
        info = al.load_agent("minimo")
        assert info["skills"] == []

    def test_skills_no_system_prompt(self, agents_dir):
        write_agent(agents_dir, "teste", AGENT_COMPLETO)
        info = al.load_agent("teste")
        # skills com nivel não-vazio devem aparecer no prompt
        assert "code-review" in info["system_prompt"]

    def test_build_skills_block_vazio(self):
        assert al._build_skills_block([]) == ""

    def test_build_skills_block_contem_skill(self):
        skills = [{"name": "code-review", "level": "sugerida"}]
        block = al._build_skills_block(skills)
        assert "code-review" in block
        assert "sugerida" in block


# ── list_agents ───────────────────────────────────────────────────────────────

class TestListAgents:
    def test_retorna_lista_ordenada(self, agents_dir):
        write_agent(agents_dir, "zebra", AGENT_MINIMO)
        write_agent(agents_dir, "alpha", AGENT_MINIMO)
        write_agent(agents_dir, "medio", AGENT_MINIMO)
        result = al.list_agents()
        assert result == sorted(result)

    def test_sem_extensao(self, agents_dir):
        write_agent(agents_dir, "meu_agente", AGENT_MINIMO)
        result = al.list_agents()
        assert "meu_agente" in result
        assert "meu_agente.md" not in result

    def test_pasta_vazia(self, agents_dir):
        assert al.list_agents() == []


# ── filter_tools ──────────────────────────────────────────────────────────────

class TestFilterTools:
    @pytest.fixture
    def tools_fake(self):
        return {
            "calculator":         {"fn": None},
            "read_file":          {"fn": None},
            "web_search_extended": {"fn": None},
            "run_script":         {"fn": None},
            "create_tool":        {"fn": None},
            "minha_tool_custom":  {"fn": None},
        }

    def test_allowed_none_retorna_tudo(self, tools_fake):
        result = al.filter_tools(tools_fake, allowed=None)
        assert set(result.keys()) == set(tools_fake.keys())

    def test_allowed_lista_filtra(self, tools_fake):
        result = al.filter_tools(tools_fake, allowed=["minha_tool_custom"])
        assert "minha_tool_custom" in result
        # tool fora da lista mas fora das CORE_TOOLS não passa
        # (web_search_extended está em CORE_TOOLS, então passa)

    def test_core_tools_sempre_incluidas(self, tools_fake):
        """CORE_TOOLS passam mesmo quando não listadas em allowed."""
        result = al.filter_tools(tools_fake, allowed=["minha_tool_custom"])
        for core in al.CORE_TOOLS:
            if core in tools_fake:
                assert core in result, f"CORE_TOOL '{core}' deveria estar presente"

    def test_tool_nao_listada_e_nao_core_excluida(self, tools_fake):
        tools = {"ferramenta_exotica": {"fn": None}}
        result = al.filter_tools(tools, allowed=["outra_coisa"])
        assert "ferramenta_exotica" not in result


# ── filter_mcp_tools ──────────────────────────────────────────────────────────

class TestFilterMCPTools:
    @pytest.fixture
    def mcp_tools(self):
        return {
            "mcp_telegram__send_message": {"fn": None},
            "mcp_telegram__read_messages": {"fn": None},
            "mcp_google__search":          {"fn": None},
            "calculator":                  {"fn": None},  # tool local, não MCP
        }

    def test_allowed_none_retorna_tudo(self, mcp_tools):
        result = al.filter_mcp_tools(mcp_tools, allowed_servers=None)
        assert set(result.keys()) == set(mcp_tools.keys())

    def test_allowed_vazio_remove_todas_mcp(self, mcp_tools):
        result = al.filter_mcp_tools(mcp_tools, allowed_servers=[])
        assert "mcp_telegram__send_message" not in result
        assert "mcp_google__search" not in result

    def test_allowed_vazio_preserva_tools_locais(self, mcp_tools):
        result = al.filter_mcp_tools(mcp_tools, allowed_servers=[])
        assert "calculator" in result

    def test_allowed_servidor_especifico(self, mcp_tools):
        result = al.filter_mcp_tools(mcp_tools, allowed_servers=["telegram"])
        assert "mcp_telegram__send_message" in result
        assert "mcp_telegram__read_messages" in result
        assert "mcp_google__search" not in result

    def test_namespace_correto_extraido(self, mcp_tools):
        """Servidor é extraído entre 'mcp_' e '__'."""
        result = al.filter_mcp_tools(mcp_tools, allowed_servers=["google"])
        assert "mcp_google__search" in result
        assert "mcp_telegram__send_message" not in result

"""
tests/test_tools/test_whatsapp_configure.py

Cobre tools/whatsapp_configure.py:
  - registro: carrega, expõe parâmetros tipados e NÃO é insegura (funciona com --safe)
  - criação: parte do exemplo, não herda números de ilustração, strip de _comentario
  - validação: modos, agente, números, bridge_url — e nada é gravado se falhar
  - config existente: recusa sem overwrite; com overwrite preserva groups/dm_policy
  - tolerância a entrada de modelo: bool como string, lista, array JSON em string
  - o whatsapp_channels.example.json do repositório continua válido e em sincronia
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """
    Isola tudo no tmp_path: config, exemplo e pasta de agentes.
    Devolve um objeto simples com os caminhos e o módulo da tool.
    """
    import agent_loader
    from mcp.whatsapp import channels
    import tools.whatsapp_configure as mod

    agents = tmp_path / "agents"
    agents.mkdir()
    for name in ("general", "dev_helper"):
        (agents / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")

    cfg_file = tmp_path / "whatsapp_channels.json"
    monkeypatch.setattr(agent_loader, "AGENTS_DIR", agents)
    monkeypatch.setattr(channels, "CONFIG_FILE", cfg_file)

    class Env:
        tool = mod
        config = cfg_file
        example = tmp_path / "whatsapp_channels.example.json"

        @staticmethod
        def write_example(**overrides):
            data = {
                "_comentario": "texto só do exemplo",
                "bridge_url": "http://127.0.0.1:8765",
                "bot": {
                    "enabled": True,
                    "agent": "general",
                    "allow_from": ["+55 11 99999-9999", "+247000000000000"],
                    "groups": {"policy": "allowlist", "allow_from": []},
                    "dm_policy": "allowlist",
                },
                "mcp": {"enabled": False},
            }
            data.update(overrides)
            cfg_file.with_name("whatsapp_channels.example.json").write_text(
                json.dumps(data), encoding="utf-8"
            )

        @staticmethod
        def saved():
            return json.loads(cfg_file.read_text(encoding="utf-8"))

    return Env


def _ok(env, **kw):
    kw.setdefault("agent", "general")
    kw.setdefault("allow_from", "+55 86 99999-9999")
    return env.tool.run(**kw)


# ── registro ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tools():
    import tools_registry
    return tools_registry.load_tools()


class TestRegistro:

    def test_tool_carrega(self, tools):
        assert "whatsapp_configure" in tools

    def test_nao_e_insegura(self, tools):
        """O ponto da tool: a task de configuração tem que funcionar com --safe."""
        from tool_dispatch import UNSAFE_TOOLS, filter_unsafe
        assert "whatsapp_configure" not in UNSAFE_TOOLS
        assert "whatsapp_configure" in filter_unsafe(tools, safe=True)

    def test_parametros_expostos_ao_modelo(self, tools):
        names = [p["name"] for p in tools["whatsapp_configure"]["parameters"]]
        assert names == ["agent", "allow_from", "bot", "mcp", "bridge_url", "overwrite"]

    def test_parametros_tem_descricao(self, tools):
        for p in tools["whatsapp_configure"]["parameters"]:
            assert p.get("description"), f"{p['name']} sem descrição"

    def test_overwrite_default_e_false(self, tools):
        p = {x["name"]: x for x in tools["whatsapp_configure"]["parameters"]}
        assert p["overwrite"]["default"] == "False"

    def test_output_interno(self, tools):
        assert tools["whatsapp_configure"]["output_type"] == "internal"


# ── criação ───────────────────────────────────────────────────────────────────

class TestCriacao:
    def test_cria_arquivo_com_valores_informados(self, env):
        r = _ok(env, allow_from="+55 86 99999-9999")
        assert "salvo" in r
        data = env.saved()
        assert data["bot"]["enabled"] is True
        assert data["bot"]["agent"] == "general"
        assert data["bot"]["allow_from"] == ["+55 86 99999-9999"]
        assert data["mcp"]["enabled"] is False
        assert data["bridge_url"] == "http://127.0.0.1:8765"

    def test_sem_exemplo_usa_defaults(self, env):
        assert not env.example.exists()
        _ok(env)
        data = env.saved()
        assert data["bot"]["groups"] == {"policy": "allowlist", "allow_from": []}
        assert data["bot"]["dm_policy"] == "allowlist"

    def test_parte_do_exemplo(self, env):
        env.write_example(bridge_url="http://127.0.0.1:9999")
        r = _ok(env)
        assert "exemplo" in r
        assert env.saved()["bridge_url"] == "http://127.0.0.1:9999"

    def test_nao_herda_numeros_do_exemplo(self, env):
        env.write_example()
        _ok(env, allow_from="+55 86 99999-9999")
        allow = env.saved()["bot"]["allow_from"]
        assert allow == ["+55 86 99999-9999"]
        assert "+247000000000000" not in allow

    def test_remove_comentario_do_exemplo(self, env):
        env.write_example()
        _ok(env)
        assert "_comentario" not in env.saved()

    def test_exemplo_corrompido_cai_para_defaults(self, env):
        env.example.write_text("{ isso não é json", encoding="utf-8")
        r = _ok(env)
        assert "salvo" in r
        assert env.saved()["bot"]["agent"] == "general"

    def test_resultado_pode_ser_lido_pelo_channels(self, env):
        """Round-trip: o que a tool grava é o que o roteador do bot entende."""
        from mcp.whatsapp import channels
        _ok(env, agent="dev_helper", allow_from="+55 86 99999-9999")
        assert channels.bot_enabled() is True
        assert channels.bot_agent() == "dev_helper"
        assert channels.is_allowed("+55 86 99999-9999", "direct") is True
        assert channels.is_allowed("+55 11 11111-1111", "direct") is False

    def test_lid_na_allowlist(self, env):
        from mcp.whatsapp import channels
        _ok(env, allow_from="+55 86 99999-9999, +999999999999999")
        assert channels.is_allowed("+999999999999999", "direct") is True


# ── modos ─────────────────────────────────────────────────────────────────────

class TestModos:
    def test_so_mcp_nao_exige_agente_nem_numero(self, env):
        r = env.tool.run(bot=False, mcp=True)
        assert "salvo" in r
        data = env.saved()
        assert data["bot"]["enabled"] is False
        assert data["mcp"]["enabled"] is True

    def test_so_mcp_nao_herda_numeros_do_exemplo(self, env):
        env.write_example()
        env.tool.run(bot=False, mcp=True)
        assert env.saved()["bot"]["allow_from"] == []

    def test_dois_modos(self, env):
        _ok(env, mcp=True)
        data = env.saved()
        assert data["bot"]["enabled"] is True
        assert data["mcp"]["enabled"] is True

    def test_nenhum_modo_e_erro_e_nao_grava(self, env):
        r = env.tool.run(bot=False, mcp=False)
        assert r.startswith("Erro")
        assert not env.config.exists()

    def test_bool_como_string(self, env):
        env.tool.run(agent="general", allow_from="+55 86 99999-9999",
                     bot="true", mcp="nao")
        data = env.saved()
        assert data["bot"]["enabled"] is True
        assert data["mcp"]["enabled"] is False

    def test_bool_invalido_e_erro(self, env):
        r = env.tool.run(agent="general", allow_from="+55 86 99999-9999", bot="talvez")
        assert r.startswith("Erro") and "bot" in r
        assert not env.config.exists()


# ── agente ────────────────────────────────────────────────────────────────────

class TestAgente:
    def test_bot_sem_agente_e_erro(self, env):
        r = env.tool.run(allow_from="+55 86 99999-9999")
        assert r.startswith("Erro") and "agente" in r
        assert not env.config.exists()

    def test_agente_inexistente_lista_os_disponiveis(self, env):
        r = _ok(env, agent="inventado")
        assert r.startswith("Erro")
        assert "inventado" in r
        assert "general" in r and "dev_helper" in r
        assert not env.config.exists()

    def test_aceita_nome_com_extensao_md(self, env):
        _ok(env, agent="dev_helper.md")
        assert env.saved()["bot"]["agent"] == "dev_helper"


# ── números ───────────────────────────────────────────────────────────────────

class TestNumeros:
    def test_bot_sem_numero_e_erro(self, env):
        r = env.tool.run(agent="general")
        assert r.startswith("Erro") and "allow_from" in r
        assert not env.config.exists()

    @pytest.mark.parametrize("bad", [
        "5586999999999",         # sem +
        "+55",                   # curto demais
        "+55 86 abcde-9999",     # letras
        "(86) 99999-9999",       # sem + nem código do país
        "+",
    ])
    def test_numero_invalido_e_erro_e_nao_grava(self, env, bad):
        r = _ok(env, allow_from=bad)
        assert r.startswith("Erro")
        assert "Nada foi gravado" in r
        assert not env.config.exists()

    def test_um_invalido_entre_validos_bloqueia_tudo(self, env):
        r = _ok(env, allow_from="+55 86 99999-9999, 12345")
        assert r.startswith("Erro") and "12345" in r
        assert not env.config.exists()

    @pytest.mark.parametrize("fmt", [
        "+55 86 99999-9999",
        "+5586999999999",
        "+55 (86) 99999-9999",
        "+55.86.99999.9999",
    ])
    def test_formatos_aceitos(self, env, fmt):
        assert "salvo" in _ok(env, allow_from=fmt)

    def test_separadores_virgula_ponto_e_virgula_e_quebra_de_linha(self, env):
        _ok(env, allow_from="+55 86 99999-9999;+55 11 98888-7777\n+247000000000001")
        assert len(env.saved()["bot"]["allow_from"]) == 3

    def test_aceita_lista(self, env):
        _ok(env, allow_from=["+55 86 99999-9999", "+55 11 98888-7777"])
        assert len(env.saved()["bot"]["allow_from"]) == 2

    def test_aceita_array_json_em_string(self, env):
        _ok(env, allow_from='["+55 86 99999-9999", "+55 11 98888-7777"]')
        assert len(env.saved()["bot"]["allow_from"]) == 2

    def test_deduplica_mesmo_numero_em_formatos_diferentes(self, env):
        _ok(env, allow_from="+55 86 99999-9999, +5586999999999")
        assert env.saved()["bot"]["allow_from"] == ["+55 86 99999-9999"]

    def test_espacos_extras_sao_colapsados(self, env):
        _ok(env, allow_from="  +55   86  99999-9999  ")
        assert env.saved()["bot"]["allow_from"] == ["+55 86 99999-9999"]


# ── bridge_url ────────────────────────────────────────────────────────────────

class TestBridgeUrl:
    def test_omitida_mantem_padrao(self, env):
        _ok(env)
        assert env.saved()["bridge_url"] == "http://127.0.0.1:8765"

    def test_customizada(self, env):
        _ok(env, bridge_url="http://127.0.0.1:9000")
        assert env.saved()["bridge_url"] == "http://127.0.0.1:9000"

    def test_barra_final_removida(self, env):
        _ok(env, bridge_url="http://127.0.0.1:9000/")
        assert env.saved()["bridge_url"] == "http://127.0.0.1:9000"

    @pytest.mark.parametrize("bad", ["127.0.0.1:8765", "ftp://x.com", "http://", "javascript:1"])
    def test_invalida_e_erro_e_nao_grava(self, env, bad):
        r = _ok(env, bridge_url=bad)
        assert r.startswith("Erro") and "bridge_url" in r
        assert not env.config.exists()

    def test_host_remoto_gera_aviso_mas_grava(self, env):
        r = _ok(env, bridge_url="http://192.168.0.10:8765")
        assert "Atenção" in r and "192.168.0.10" in r
        assert env.saved()["bridge_url"] == "http://192.168.0.10:8765"

    def test_host_local_sem_aviso(self, env):
        assert "Atenção" not in _ok(env)

    def test_string_vazia_equivale_a_omitida(self, env):
        _ok(env, bridge_url="  ")
        assert env.saved()["bridge_url"] == "http://127.0.0.1:8765"


# ── config já existente ───────────────────────────────────────────────────────

class TestExistente:
    def _preexistente(self, env):
        original = {
            "bridge_url": "http://127.0.0.1:8765",
            "bot": {
                "enabled": True,
                "agent": "dev_helper",
                "allow_from": ["+55 11 98888-7777"],
                "groups": {"policy": "mention_only", "allow_from": ["123@g.us"]},
                "dm_policy": "pairing",
            },
            "mcp": {"enabled": True},
        }
        env.config.write_text(json.dumps(original), encoding="utf-8")
        return original

    def test_recusa_sem_overwrite_e_nao_altera_o_arquivo(self, env):
        self._preexistente(env)
        antes = env.config.read_bytes()
        r = _ok(env, agent="general")
        assert "Já existe" in r
        assert "overwrite=true" in r
        assert env.config.read_bytes() == antes

    def test_recusa_mostra_o_que_existe(self, env):
        self._preexistente(env)
        r = _ok(env)
        assert "dev_helper" in r
        assert "+55 11 98888-7777" in r

    def test_recusa_arquivo_corrompido_tambem(self, env):
        env.config.write_text("{ quebrado", encoding="utf-8")
        r = _ok(env)
        assert "Já existe" in r and "inválido" in r
        assert env.config.read_text(encoding="utf-8") == "{ quebrado"

    def test_validacao_vem_antes_da_checagem_de_existente(self, env):
        """Erro de entrada é reportado mesmo com arquivo presente — o modelo corrige primeiro."""
        self._preexistente(env)
        r = _ok(env, allow_from="sem-mais")
        assert r.startswith("Erro")

    def test_overwrite_substitui_agente_e_numeros(self, env):
        self._preexistente(env)
        _ok(env, agent="general", allow_from="+55 86 99999-9999", overwrite=True)
        data = env.saved()
        assert data["bot"]["agent"] == "general"
        assert data["bot"]["allow_from"] == ["+55 86 99999-9999"]

    def test_overwrite_preserva_groups_e_dm_policy(self, env):
        self._preexistente(env)
        r = _ok(env, overwrite=True)
        data = env.saved()
        assert data["bot"]["groups"] == {"policy": "mention_only", "allow_from": ["123@g.us"]}
        assert data["bot"]["dm_policy"] == "pairing"
        assert "groups e dm_policy" in r

    def test_overwrite_atualiza_modos(self, env):
        self._preexistente(env)
        _ok(env, mcp=False, overwrite=True)
        assert env.saved()["mcp"]["enabled"] is False

    def test_overwrite_so_mcp_preserva_allowlist_existente(self, env):
        self._preexistente(env)
        env.tool.run(bot=False, mcp=True, overwrite=True)
        data = env.saved()
        assert data["bot"]["enabled"] is False
        assert data["bot"]["allow_from"] == ["+55 11 98888-7777"]

    def test_overwrite_em_arquivo_corrompido_recomeca_do_exemplo(self, env):
        env.write_example()
        env.config.write_text("{ quebrado", encoding="utf-8")
        r = _ok(env, overwrite=True)
        assert "salvo" in r
        assert env.saved()["bot"]["agent"] == "general"

    def test_overwrite_sem_arquivo_previo_funciona_normal(self, env):
        assert "salvo" in _ok(env, overwrite=True)

    def test_overwrite_como_string(self, env):
        self._preexistente(env)
        assert "salvo" in _ok(env, overwrite="true")


# ── whatsapp_channels.example.json do repositório ─────────────────────────────

@pytest.fixture(scope="module")
def example():
    p = ROOT / "whatsapp_channels.example.json"
    assert p.exists(), "whatsapp_channels.example.json deve estar versionado na raiz"
    return json.loads(p.read_text(encoding="utf-8"))


class TestExemploDoRepositorio:

    def test_e_json_valido_de_objeto(self, example):
        assert isinstance(example, dict)

    def test_estrutura_acompanha_os_defaults_do_channels(self, example):
        """Se alguém adicionar uma chave em channels._DEFAULTS, o exemplo precisa acompanhar."""
        from mcp.whatsapp import channels

        def keys(d):
            return {k: keys(v) if isinstance(v, dict) else None
                    for k, v in d.items() if not k.startswith("_")}

        assert keys(example) == keys(channels._DEFAULTS)

    def test_numeros_de_ilustracao_passam_na_validacao_da_tool(self, example):
        import tools.whatsapp_configure as mod
        from mcp.whatsapp import channels
        valid, invalid = mod._validate_numbers(example["bot"]["allow_from"], channels._normalize)
        assert invalid == []
        assert len(valid) == len(example["bot"]["allow_from"])

    def test_nao_contem_numero_real(self, example):
        """Guarda contra commitar um número pessoal por engano: só placeholders."""
        for n in example["bot"]["allow_from"]:
            digits = "".join(c for c in n if c.isdigit())
            # código do país e DDD podem ser reais; o miolo/final do número não
            assert set(digits[-8:]) <= {"9", "0", "1"}, f"{n} parece número real"

    def test_arquivo_real_continua_no_gitignore(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert "whatsapp_channels.json" in [l.strip() for l in lines]
        assert "whatsapp_channels.example.json" not in [l.strip() for l in lines]

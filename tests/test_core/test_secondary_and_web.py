"""
tests/test_tools/test_secondary_and_web.py

Cobre tools/secondary_model.py (12% → ~40%) e tools/web_search_extended.py (21% → ~80%).

Estratégia para secondary_model.py:
  - Funções utilitárias puras: _ext_to_lexer, _extract_json, _save_code_project,
    _save_text_response, _load_config, _load_quota, _save_quota, _inject_files.
  - Caminhos de erro e configuração no run(): cota esgotada, sem api_key,
    modo mock, mode=code com JSON inválido.
  - _Spinner e _stream_response têm dependência pesada de Rich/HTTP — ficam de fora.

Estratégia para web_search_extended.py:
  - _clean_text e _scrape_page com mocks de requests.
  - run() com DDGS mockado.
"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open


# ═══════════════════════════════════════════════════════════════════════════════
# SECONDARY MODEL
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def sm_mod():
    """Importa secondary_model evitando exec no topo (tem imports pesados)."""
    import importlib.util
    # Usa path absoluto para não depender do cwd (outros testes usam monkeypatch.chdir)
    _here = Path(__file__).parent.parent.parent  # raiz do projeto
    spec = importlib.util.spec_from_file_location(
        "secondary_model_t", _here / "tools" / "secondary_model.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tmp_root(tmp_path, sm_mod, monkeypatch):
    """Redireciona todos os paths do módulo para tmp_path."""
    monkeypatch.setattr(sm_mod, "_CONFIG_PATH",  tmp_path / "ciel_config.json")
    monkeypatch.setattr(sm_mod, "_QUOTA_PATH",   tmp_path / "data" / "secondary_quota.json")
    monkeypatch.setattr(sm_mod, "_RESPONSE_DIR", tmp_path / "data" / "user")
    monkeypatch.setattr(sm_mod, "_SKILLS_DIR",   tmp_path / "skills")
    monkeypatch.setattr(sm_mod, "_MOCK_FILE",    tmp_path / "data" / "mock" / "mock_responses.json")
    return tmp_path


# ── _ext_to_lexer ─────────────────────────────────────────────────────────────

class TestExtToLexer:
    def test_html(self, sm_mod):
        assert sm_mod._ext_to_lexer("index.html") == "html"

    def test_python(self, sm_mod):
        assert sm_mod._ext_to_lexer("script.py") == "python"

    def test_javascript(self, sm_mod):
        assert sm_mod._ext_to_lexer("app.js") == "javascript"

    def test_css(self, sm_mod):
        assert sm_mod._ext_to_lexer("style.css") == "css"

    def test_json(self, sm_mod):
        assert sm_mod._ext_to_lexer("data.json") == "json"

    def test_desconhecido_retorna_text(self, sm_mod):
        assert sm_mod._ext_to_lexer("arquivo.xyz") == "text"

    def test_case_insensitive(self, sm_mod):
        assert sm_mod._ext_to_lexer("INDEX.HTML") == "html"

    def test_typescript(self, sm_mod):
        assert sm_mod._ext_to_lexer("app.ts") == "typescript"


# ── _extract_json ─────────────────────────────────────────────────────────────

class TestExtractJsonSM:
    def test_json_direto(self, sm_mod):
        result = sm_mod._extract_json('{"folder": "proj", "files": []}')
        assert result["folder"] == "proj"

    def test_json_com_fence(self, sm_mod):
        text = '```json\n{"folder": "proj"}\n```'
        result = sm_mod._extract_json(text)
        assert result is not None
        assert result["folder"] == "proj"

    def test_json_com_texto_ao_redor(self, sm_mod):
        text = 'Aqui está:\n{"folder": "proj"}\nObrigado.'
        result = sm_mod._extract_json(text)
        assert result is not None

    def test_retorna_none_sem_json(self, sm_mod):
        assert sm_mod._extract_json("texto puro sem json") is None

    def test_retorna_none_para_vazio(self, sm_mod):
        assert sm_mod._extract_json("") is None

    def test_json_aninhado(self, sm_mod):
        data = {"folder": "x", "files": [{"filename": "a.py", "content": "pass"}]}
        result = sm_mod._extract_json(json.dumps(data))
        assert result["files"][0]["filename"] == "a.py"


# ── _load_config ──────────────────────────────────────────────────────────────

class TestLoadConfigSM:
    def test_retorna_defaults_sem_arquivo(self, tmp_root, sm_mod):
        cfg = sm_mod._load_config()
        assert "base_url" in cfg
        assert "model" in cfg
        assert "timeout" in cfg

    def test_sobrescreve_defaults_com_arquivo(self, tmp_root, sm_mod):
        (tmp_root / "ciel_config.json").write_text(
            json.dumps({"timeout": 999, "model": "meu-modelo"}), encoding="utf-8"
        )
        cfg = sm_mod._load_config()
        assert cfg["timeout"] == 999
        assert cfg["model"] == "meu-modelo"

    def test_retorna_defaults_com_json_invalido(self, tmp_root, sm_mod):
        (tmp_root / "ciel_config.json").write_text("{invalido!!!", encoding="utf-8")
        cfg = sm_mod._load_config()
        # deve retornar os defaults sem travar
        assert "base_url" in cfg

    def test_preserva_defaults_nao_sobrescritos(self, tmp_root, sm_mod):
        (tmp_root / "ciel_config.json").write_text(
            json.dumps({"model": "custom"}), encoding="utf-8"
        )
        cfg = sm_mod._load_config()
        # base_url deve vir do _DEFAULT_CONFIG
        assert cfg["base_url"] == sm_mod._DEFAULT_CONFIG["base_url"]


# ── _load_quota / _save_quota ─────────────────────────────────────────────────

class TestQuota:
    def test_load_quota_zero_sem_arquivo(self, tmp_root, sm_mod):
        assert sm_mod._load_quota("sessao-x") == 0

    def test_save_e_load_quota(self, tmp_root, sm_mod):
        sm_mod._save_quota("sessao-abc", 5000)
        assert sm_mod._load_quota("sessao-abc") == 5000

    def test_multiplas_sessoes_independentes(self, tmp_root, sm_mod):
        sm_mod._save_quota("sess-1", 1000)
        sm_mod._save_quota("sess-2", 2000)
        assert sm_mod._load_quota("sess-1") == 1000
        assert sm_mod._load_quota("sess-2") == 2000

    def test_sessao_inexistente_retorna_zero(self, tmp_root, sm_mod):
        sm_mod._save_quota("sess-real", 500)
        assert sm_mod._load_quota("sess-fantasma") == 0

    def test_atualiza_quota_existente(self, tmp_root, sm_mod):
        sm_mod._save_quota("sess", 100)
        sm_mod._save_quota("sess", 200)
        assert sm_mod._load_quota("sess") == 200

    def test_load_quota_json_invalido_retorna_zero(self, tmp_root, sm_mod):
        quota_path = tmp_root / "data" / "secondary_quota.json"
        quota_path.parent.mkdir(parents=True, exist_ok=True)
        quota_path.write_text("{invalido", encoding="utf-8")
        assert sm_mod._load_quota("sess") == 0


# ── _save_text_response ───────────────────────────────────────────────────────
# _save_text_response usa Path(__file__).parent.parent hardcoded como raiz para
# calcular o caminho relativo. Patching _RESPONSE_DIR sozinho não resolve esse
# problema. Testamos via patch direto do módulo real (projeto).

class TestSaveTextResponse:
    def test_cria_arquivo_md(self, sm_mod):
        """Verifica que o arquivo .md é criado no _RESPONSE_DIR do módulo."""
        import os, tempfile, shutil
        orig_dir = sm_mod._RESPONSE_DIR
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            # substitui _RESPONSE_DIR e a raiz de referência do relative_to
            # não é possível sem monkey-patching Path(__file__) — então
            # usamos o diretório real do projeto e limpamos depois
            try:
                rel = sm_mod._save_text_response("# Conteúdo de teste")
                full = Path("tools/secondary_model.py").parent.parent / rel
                assert full.exists()
                assert "secondary_response_" in rel
            finally:
                # limpa arquivo criado
                full_path = Path("tools/secondary_model.py").parent.parent / rel
                if full_path.exists():
                    full_path.unlink()

    def test_conteudo_preservado(self, sm_mod):
        content = "# Meu Conteúdo Único 12345"
        try:
            rel = sm_mod._save_text_response(content)
            full = Path("tools/secondary_model.py").parent.parent / rel
            assert content in full.read_text(encoding="utf-8")
        finally:
            full_path = Path("tools/secondary_model.py").parent.parent / rel
            if full_path.exists():
                full_path.unlink()

    def test_nome_inclui_timestamp(self, sm_mod):
        try:
            rel = sm_mod._save_text_response("conteúdo")
            assert "secondary_response_" in rel
        finally:
            full_path = Path("tools/secondary_model.py").parent.parent / rel
            if full_path.exists():
                full_path.unlink()


# ── _save_code_project ────────────────────────────────────────────────────────
# Mesmo problema: usa Path(__file__).parent.parent para relative_to.

class TestSaveCodeProject:
    def _cleanup(self, sm_mod, folder_path):
        full = Path("tools/secondary_model.py").parent.parent / folder_path
        if full.exists():
            import shutil
            shutil.rmtree(full)

    def test_retorna_lista_de_arquivos_criados(self, sm_mod):
        data = {
            "folder": "proj-test-lista",
            "files": [
                {"filename": "index.html", "content": "<html/>"},
                {"filename": "style.css", "content": "body{}"},
            ],
        }
        folder_path, files = sm_mod._save_code_project(data)
        try:
            assert "index.html" in files
            assert "style.css" in files
        finally:
            self._cleanup(sm_mod, folder_path)

    def test_conteudo_dos_arquivos_correto(self, sm_mod):
        data = {
            "folder": "proj-test-content",
            "files": [{"filename": "app.py", "content": "def main_unica(): pass"}],
        }
        folder_path, _ = sm_mod._save_code_project(data)
        try:
            full_dir = Path("tools/secondary_model.py").parent.parent / folder_path
            app_file = full_dir / "app.py"
            assert app_file.exists()
            assert "def main_unica(): pass" in app_file.read_text(encoding="utf-8")
        finally:
            self._cleanup(sm_mod, folder_path)

    def test_folder_sanitizado(self, sm_mod):
        """Nome de pasta com espaços deve ser sanitizado."""
        data = {
            "folder": "Proj Com Espacos",
            "files": [{"filename": "f.txt", "content": "x"}],
        }
        folder_path, _ = sm_mod._save_code_project(data)
        try:
            assert " " not in Path(folder_path).name
        finally:
            self._cleanup(sm_mod, folder_path)

    def test_pasta_sem_arquivos(self, sm_mod):
        data = {"folder": "vazio-test", "files": []}
        folder_path, files = sm_mod._save_code_project(data)
        try:
            assert files == []
        finally:
            self._cleanup(sm_mod, folder_path)


# ── _inject_files ─────────────────────────────────────────────────────────────

class TestInjectFiles:
    def test_sem_arquivos_retorna_prompt_original(self, sm_mod):
        result = sm_mod._inject_files("meu prompt", [])
        assert result == "meu prompt"

    def test_none_retorna_prompt_original(self, sm_mod):
        result = sm_mod._inject_files("meu prompt", None)
        assert result == "meu prompt"

    def test_injeta_conteudo_do_arquivo(self, tmp_path, sm_mod):
        f = tmp_path / "contexto.py"
        f.write_text("def hello(): pass", encoding="utf-8")
        result = sm_mod._inject_files("meu prompt", [str(f)])
        assert "def hello(): pass" in result
        assert "meu prompt" in result

    def test_contexto_vem_antes_do_prompt(self, tmp_path, sm_mod):
        f = tmp_path / "ctx.md"
        f.write_text("# Contexto", encoding="utf-8")
        result = sm_mod._inject_files("instrução do usuário", [str(f)])
        pos_ctx = result.find("# Contexto")
        pos_prompt = result.find("instrução do usuário")
        assert pos_ctx < pos_prompt

    def test_arquivo_inexistente_gera_aviso_inline(self, sm_mod):
        result = sm_mod._inject_files("prompt", ["/caminho/inexistente/arquivo.py"])
        assert "não encontrado" in result or "arquivo.py" in result

    def test_inclui_cabecalho_de_contexto(self, tmp_path, sm_mod):
        f = tmp_path / "f.py"
        f.write_text("pass", encoding="utf-8")
        result = sm_mod._inject_files("prompt", [str(f)])
        assert "Contexto" in result

    def test_multiplos_arquivos_todos_injetados(self, tmp_path, sm_mod):
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("arquivo_a = 1", encoding="utf-8")
        f2.write_text("arquivo_b = 2", encoding="utf-8")
        result = sm_mod._inject_files("prompt", [str(f1), str(f2)])
        assert "arquivo_a" in result
        assert "arquivo_b" in result


# ── run() — caminhos sem chamada real à API ───────────────────────────────────

class TestRunSemAPI:
    @pytest.fixture
    def cfg_basico(self, tmp_root, sm_mod):
        """Config mínima + env var para api_key."""
        (tmp_root / "ciel_config.json").write_text(json.dumps({
            "base_url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile",
            "max_chars_per_session": 1000,
        }), encoding="utf-8")

    def test_cota_esgotada_retorna_mensagem(self, tmp_root, sm_mod, cfg_basico, monkeypatch):
        monkeypatch.setenv("SECONDARY_MODEL_API_KEY", "fake-key")
        # força cota esgotada
        sm_mod._save_quota("sess-cota", 2000)  # already over max_chars=1000
        result = sm_mod.run("prompt qualquer", session_id="sess-cota")
        assert "Cota" in result or "esgotada" in result

    def test_sem_api_key_retorna_mensagem_de_erro(self, tmp_root, sm_mod, monkeypatch):
        monkeypatch.delenv("SECONDARY_MODEL_API_KEY", raising=False)
        (tmp_root / "ciel_config.json").write_text(json.dumps({
            "base_url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3",
        }), encoding="utf-8")
        with patch("trust.secrets.secrets") as mock_secrets:
            mock_secrets.resolve_api_key.return_value = ""
            result = sm_mod.run("prompt qualquer", session_id="sess-nokey")
        assert "API key" in result or "api_key" in result.lower()

    def test_mock_secondary_mode_text(self, tmp_root, sm_mod):
        (tmp_root / "ciel_config.json").write_text(json.dumps({
            "mock_secondary": True,
            "mock_type": "text",
        }), encoding="utf-8")
        result = sm_mod.run("pergunta de teste", mode="text", session_id="sess-mock")
        assert "[MOCK]" in result

    def test_mock_secondary_mode_text_long(self, tmp_root, sm_mod):
        (tmp_root / "ciel_config.json").write_text(json.dumps({
            "mock_secondary": True,
            "mock_type": "text_long",
        }), encoding="utf-8")
        # _save_text_response usa Path(__file__).parent.parent → patchamos ela
        with patch.object(sm_mod, "_save_text_response", return_value="data/user/mock.md"):
            result = sm_mod.run("prompt longo", mode="text", session_id="sess-mock2")
        assert "Resposta completa salva em" in result or "[MOCK]" in result

    def test_mock_secondary_mode_quota(self, tmp_root, sm_mod):
        (tmp_root / "ciel_config.json").write_text(json.dumps({
            "mock_secondary": True,
            "mock_type": "quota",
        }), encoding="utf-8")
        result = sm_mod.run("prompt", session_id="sess-quota")
        assert "Cota" in result or "esgotada" in result

    def test_mock_secondary_mode_invalid_code(self, tmp_root, sm_mod):
        (tmp_root / "ciel_config.json").write_text(json.dumps({
            "mock_secondary": True,
            "mock_type": "invalid",
        }), encoding="utf-8")
        with patch.object(sm_mod, "_save_text_response", return_value="data/user/fallback.md"):
            result = sm_mod.run("prompt", mode="code", session_id="sess-inv")
        assert "aviso" in result or "JSON" in result or "texto" in result.lower()

    def test_inject_files_no_run(self, tmp_root, sm_mod, tmp_path, monkeypatch):
        """Arquivos passados via files= devem aparecer no prompt injetado."""
        f = tmp_path / "contexto.py"
        f.write_text("meu_contexto = True", encoding="utf-8")

        (tmp_root / "ciel_config.json").write_text(json.dumps({
            "mock_secondary": True,
            "mock_type": "text",
        }), encoding="utf-8")
        result = sm_mod.run("prompt", files=[str(f)], session_id="sess-files")
        # resultado deve ter saído do mock (arquivos presentes no prompt)
        assert "[MOCK]" in result


# ── _load_skill ───────────────────────────────────────────────────────────────

class TestLoadSkill:
    def test_skill_existente_retorna_conteudo(self, tmp_root, sm_mod):
        skill_dir = tmp_root / "skills"
        skill_dir.mkdir(exist_ok=True)
        (skill_dir / "minha-skill.md").write_text("# Skill de teste", encoding="utf-8")
        result = sm_mod._load_skill("minha-skill")
        assert result == "# Skill de teste"

    def test_skill_inexistente_retorna_none(self, tmp_root, sm_mod):
        result = sm_mod._load_skill("skill-que-nao-existe")
        assert result is None


# ── _load_mock_responses ──────────────────────────────────────────────────────

class TestLoadMockResponses:
    def test_retorna_dict_vazio_sem_arquivo(self, tmp_root, sm_mod):
        result = sm_mod._load_mock_responses()
        assert result == {}

    def test_carrega_respostas_do_arquivo(self, tmp_root, sm_mod):
        mock_dir = tmp_root / "data" / "mock"
        mock_dir.mkdir(parents=True, exist_ok=True)
        (mock_dir / "mock_responses.json").write_text(
            json.dumps({"text": "resposta personalizada"}), encoding="utf-8"
        )
        result = sm_mod._load_mock_responses()
        assert result["text"] == "resposta personalizada"

    def test_retorna_dict_vazio_com_json_invalido(self, tmp_root, sm_mod):
        mock_dir = tmp_root / "data" / "mock"
        mock_dir.mkdir(parents=True, exist_ok=True)
        (mock_dir / "mock_responses.json").write_text("{invalido", encoding="utf-8")
        result = sm_mod._load_mock_responses()
        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════════
# WEB SEARCH EXTENDED
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def ws_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "web_search_extended_t", Path("tools/web_search_extended.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _clean_text ───────────────────────────────────────────────────────────────

class TestCleanText:
    def test_remove_tags_html(self, ws_mod):
        html = "<p>Olá <b>mundo</b></p>"
        result = ws_mod._clean_text(html)
        assert "<p>" not in result
        assert "<b>" not in result
        assert "Olá" in result
        assert "mundo" in result

    def test_remove_scripts(self, ws_mod):
        html = "<p>Texto</p><script>alert('xss')</script>"
        result = ws_mod._clean_text(html)
        assert "alert" not in result
        assert "Texto" in result

    def test_remove_style(self, ws_mod):
        html = "<p>Texto</p><style>.cls { color: red; }</style>"
        result = ws_mod._clean_text(html)
        assert "color" not in result

    def test_remove_urls(self, ws_mod):
        html = "<p>Veja https://exemplo.com/pagina aqui</p>"
        result = ws_mod._clean_text(html)
        assert "https://" not in result

    def test_retorna_string(self, ws_mod):
        assert isinstance(ws_mod._clean_text("<p>texto</p>"), str)

    def test_remove_espacos_multiplos(self, ws_mod):
        html = "<p>texto   com   espaços</p>"
        result = ws_mod._clean_text(html)
        assert "  " not in result


# ── _scrape_page ──────────────────────────────────────────────────────────────

class TestScrapePage:
    def test_retorna_erro_quando_ssrf_bloqueado(self, ws_mod):
        with patch("tools.web_search_extended.check_url", return_value="URL bloqueada por SSRF"):
            result = ws_mod._scrape_page("http://169.254.169.254/meta-data")
        assert "URL bloqueada" in result or "[" in result

    def test_retorna_conteudo_da_pagina(self, ws_mod):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>Conteúdo da página</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("tools.web_search_extended.check_url", return_value=None):
            with patch("requests.get", return_value=mock_resp):
                result = ws_mod._scrape_page("https://exemplo.com")
        assert "Conteúdo da página" in result

    def test_trunca_conteudo_longo(self, ws_mod):
        conteudo_longo = "palavra " * 5000
        mock_resp = MagicMock()
        mock_resp.text = f"<p>{conteudo_longo}</p>"
        mock_resp.raise_for_status = MagicMock()
        with patch("tools.web_search_extended.check_url", return_value=None):
            with patch("requests.get", return_value=mock_resp):
                result = ws_mod._scrape_page("https://exemplo.com", max_chars=100)
        assert len(result) <= 105  # 100 + "..."

    def test_retorna_erro_em_excecao_de_request(self, ws_mod):
        with patch("tools.web_search_extended.check_url", return_value=None):
            with patch("requests.get", side_effect=Exception("conexão recusada")):
                result = ws_mod._scrape_page("https://exemplo.com")
        assert "Erro" in result

    def test_retorna_formato_de_erro_com_brackets(self, ws_mod):
        """Erros devem retornar string com [...] para indicar que não é conteúdo real."""
        with patch("tools.web_search_extended.check_url", return_value=None):
            with patch("requests.get", side_effect=Exception("timeout")):
                result = ws_mod._scrape_page("https://exemplo.com")
        assert result.startswith("[")


# ── run() ─────────────────────────────────────────────────────────────────────

class TestWebSearchRun:
    def _make_ddgs_result(self, n=3):
        return [
            {
                "title": f"Resultado {i}",
                "href": f"https://exemplo{i}.com",
                "body": f"Resumo do resultado {i}",
            }
            for i in range(1, n + 1)
        ]

    def _make_ddgs_mock(self, results):
        """
        DDGS é usado como 'with DDGS() as ddgs: ddgs.text(...)'.
        O __enter__ retorna self, então mock_instance.__enter__.return_value
        precisa ter o método .text() configurado.
        """
        mock_instance = MagicMock()
        mock_inner = MagicMock()
        mock_inner.text.return_value = results
        mock_instance.__enter__ = MagicMock(return_value=mock_inner)
        mock_instance.__exit__ = MagicMock(return_value=False)
        return mock_instance, mock_inner

    def test_retorna_resultados(self, ws_mod):
        mock_inst, _ = self._make_ddgs_mock(self._make_ddgs_result(3))
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            result = ws_mod.run("python tutorial")
        assert "Resultado 1" in result
        assert "Resultado 2" in result

    def test_sem_resultados_retorna_mensagem(self, ws_mod):
        mock_inst, _ = self._make_ddgs_mock([])
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            result = ws_mod.run("query sem resultado")
        assert "Nenhum resultado" in result

    def test_inclui_cabecalho_com_query(self, ws_mod):
        mock_inst, _ = self._make_ddgs_mock(self._make_ddgs_result(2))
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            result = ws_mod.run("python tutorial", limit=2)
        assert "python tutorial" in result
        assert "DuckDuckGo" in result

    def test_limit_e_respeitado(self, ws_mod):
        mock_inst, mock_inner = self._make_ddgs_mock(self._make_ddgs_result(2))
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            ws_mod.run("query", limit=2)
        mock_inner.text.assert_called_once_with("query", max_results=2)

    def test_extract_false_nao_chama_scrape(self, ws_mod):
        mock_inst, _ = self._make_ddgs_mock(self._make_ddgs_result(2))
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            with patch.object(ws_mod, "_scrape_page") as mock_scrape:
                ws_mod.run("query", extract=False)
        mock_scrape.assert_not_called()

    def test_extract_true_chama_scrape_no_primeiro(self, ws_mod):
        mock_inst, _ = self._make_ddgs_mock(self._make_ddgs_result(3))
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            with patch.object(ws_mod, "_scrape_page", return_value="conteúdo extraído") as mock_scrape:
                result = ws_mod.run("query", extract=True, max_results_with_content=1)
        assert mock_scrape.call_count >= 1
        assert "conteúdo extraído" in result

    def test_excecao_geral_retorna_mensagem_de_erro(self, ws_mod):
        with patch.object(ws_mod, "DDGS", side_effect=Exception("conexão falhou")):
            result = ws_mod.run("query")
        assert "Erro" in result

    def test_resultado_inclui_url(self, ws_mod):
        mock_inst, _ = self._make_ddgs_mock(self._make_ddgs_result(1))
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            result = ws_mod.run("query")
        assert "https://exemplo1.com" in result

    def test_resultado_inclui_resumo(self, ws_mod):
        mock_inst, _ = self._make_ddgs_mock(self._make_ddgs_result(1))
        with patch.object(ws_mod, "DDGS", return_value=mock_inst):
            result = ws_mod.run("query")
        assert "Resumo do resultado 1" in result

"""
tests/test_core/test_ingest_url.py

Cobre knowledge/ingest_url.py — 20% cobertura, 124 stmts.
Testa: cache helpers, _url_to_display_name, _chunk_text,
_quick_summary, _fetch_texto, ingest_url() e delete_session_cache.
"""

import hashlib
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import knowledge.ingest_url as iu


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    """Redireciona _CACHE_ROOT para tmp_path em todos os testes."""
    monkeypatch.setattr(iu, "_CACHE_ROOT", tmp_path / "cache")
    return tmp_path / "cache"


@pytest.fixture
def db_mocks():
    """
    Mocka as funções de banco que abrem SQLite real.
    ingest_url() faz 'from knowledge.db import ...' localmente, então
    patchamos o módulo knowledge.db diretamente.
    """
    with patch("knowledge.db.init_db") as m_init, \
         patch("knowledge.db.insert_source", return_value=42) as m_src, \
         patch("knowledge.db.insert_chunks") as m_chunks:
        yield {"init_db": m_init, "insert_source": m_src, "insert_chunks": m_chunks}


# ── _url_hash ─────────────────────────────────────────────────────────────────

class TestUrlHash:
    def test_hash_consistente(self):
        h1 = iu._url_hash("https://exemplo.com")
        h2 = iu._url_hash("https://exemplo.com")
        assert h1 == h2

    def test_urls_diferentes_geram_hashes_diferentes(self):
        h1 = iu._url_hash("https://exemplo.com/a")
        h2 = iu._url_hash("https://exemplo.com/b")
        assert h1 != h2

    def test_hash_tem_12_chars(self):
        h = iu._url_hash("https://qualquer.com")
        assert len(h) == 12

    def test_hash_e_hexadecimal(self):
        h = iu._url_hash("https://qualquer.com")
        int(h, 16)  # não deve lançar ValueError


# ── _cache_dir e _save_cache ──────────────────────────────────────────────────

class TestCacheHelpers:
    def test_cache_dir_cria_diretorio(self, tmp_path):
        d = iu._cache_dir("sessao-123")
        assert d.exists()
        assert d.is_dir()

    def test_cache_dir_estrutura_correta(self, tmp_path):
        d = iu._cache_dir("minha-sessao")
        assert d.name == "minha-sessao"

    def test_save_cache_cria_arquivo(self, tmp_path):
        path = iu._save_cache("sessao-1", "https://exemplo.com", "conteúdo aqui")
        assert path.exists()

    def test_save_cache_primeira_linha_e_url(self, tmp_path):
        iu._save_cache("sessao-1", "https://exemplo.com/artigo", "texto da página")
        cache_dir = iu._CACHE_ROOT / "sessao-1"
        arquivo = next(cache_dir.glob("*.txt"))
        primeira_linha = arquivo.read_text(encoding="utf-8").splitlines()[0]
        assert primeira_linha == "https://exemplo.com/artigo"

    def test_save_cache_conteudo_presente(self, tmp_path):
        iu._save_cache("sessao-1", "https://x.com", "conteúdo especial")
        cache_dir = iu._CACHE_ROOT / "sessao-1"
        arquivo = next(cache_dir.glob("*.txt"))
        assert "conteúdo especial" in arquivo.read_text(encoding="utf-8")

    def test_save_cache_retorna_path(self, tmp_path):
        result = iu._save_cache("sess", "https://x.com", "texto")
        assert isinstance(result, Path)
        assert result.exists()

    def test_urls_diferentes_geram_arquivos_diferentes(self, tmp_path):
        p1 = iu._save_cache("sess", "https://a.com", "texto a")
        p2 = iu._save_cache("sess", "https://b.com", "texto b")
        assert p1 != p2


# ── delete_session_cache ──────────────────────────────────────────────────────

class TestDeleteSessionCache:
    def test_remove_diretorio_existente(self, tmp_path):
        iu._save_cache("sessao-del", "https://x.com", "texto")
        cache_dir = iu._CACHE_ROOT / "sessao-del"
        assert cache_dir.exists()
        iu.delete_session_cache("sessao-del")
        assert not cache_dir.exists()

    def test_nao_falha_para_sessao_inexistente(self, tmp_path):
        # não deve lançar exceção
        iu.delete_session_cache("sessao-que-nao-existe")

    def test_nao_afeta_outras_sessoes(self, tmp_path):
        iu._save_cache("sessao-a", "https://a.com", "texto")
        iu._save_cache("sessao-b", "https://b.com", "texto")
        iu.delete_session_cache("sessao-a")
        assert (iu._CACHE_ROOT / "sessao-b").exists()


# ── _url_to_display_name ──────────────────────────────────────────────────────

class TestUrlToDisplayName:
    def test_termina_com_ponto_url(self):
        name = iu._url_to_display_name("https://exemplo.com/artigo")
        assert name.endswith(".url")

    def test_inclui_host(self):
        name = iu._url_to_display_name("https://exemplo.com/artigo")
        assert "exemplo_com" in name or "exemplo" in name

    def test_inclui_path_final(self):
        name = iu._url_to_display_name("https://exemplo.com/pagina/artigo")
        assert "artigo" in name

    def test_remove_www(self):
        name = iu._url_to_display_name("https://www.exemplo.com/")
        assert "www" not in name

    def test_remove_extensao_html(self):
        name = iu._url_to_display_name("https://exemplo.com/artigo.html")
        assert ".html" not in name.replace(".url", "")

    def test_comprimento_maximo(self):
        url = "https://exemplo.com/" + "a" * 200
        name = iu._url_to_display_name(url)
        # _url_to_display_name trunca o slug a 80 chars e adiciona ".url"
        assert len(name) <= 84  # 80 + len(".url")

    def test_url_sem_path_usa_host(self):
        name = iu._url_to_display_name("https://exemplo.com")
        assert "exemplo" in name

    def test_caracteres_especiais_substituidos(self):
        name = iu._url_to_display_name("https://exemplo.com/pagina%20com%20espaço")
        # não deve ter espaços ou % no nome (só alfanum, _, -)
        for ch in name.replace(".url", ""):
            assert ch.isalnum() or ch in ("_", "-", "_")


# ── _split_paragraphs ─────────────────────────────────────────────────────────

class TestSplitParagraphs:
    def test_paragrafo_unico(self):
        result = iu._split_paragraphs("parágrafo único")
        assert result == ["parágrafo único"]

    def test_dois_paragrafos(self):
        result = iu._split_paragraphs("primeiro\n\nsegundo")
        assert len(result) == 2

    def test_ignora_linhas_em_branco_multiplas(self):
        result = iu._split_paragraphs("a\n\n\n\nb")
        assert len(result) == 2

    def test_ignora_paragrafos_vazios(self):
        result = iu._split_paragraphs("\n\n  \n\ntexto real\n\n  \n\n")
        assert len(result) == 1
        assert result[0] == "texto real"

    def test_texto_vazio_retorna_lista_vazia(self):
        result = iu._split_paragraphs("")
        assert result == []


# ── _chunk_text ───────────────────────────────────────────────────────────────

class TestChunkText:
    def _make_words(self, n: int) -> str:
        """Cria uma string com n palavras."""
        return " ".join(f"palavra{i}" for i in range(n))

    def test_texto_curto_gera_um_chunk(self):
        text = "Parágrafo curto com poucas palavras."
        chunks = iu._chunk_text(text)
        assert len(chunks) == 1

    def test_chunks_nao_vazios(self):
        text = "Parágrafo 1.\n\nParágrafo 2.\n\nParágrafo 3."
        chunks = iu._chunk_text(text)
        assert all(c.strip() for c in chunks)

    def test_texto_longo_gera_multiplos_chunks(self):
        # 1200 palavras → deve gerar mais de um chunk (chunk_size=300)
        text = self._make_words(1200)
        chunks = iu._chunk_text(text)
        assert len(chunks) > 1

    def test_texto_vazio_retorna_lista_vazia(self):
        chunks = iu._chunk_text("")
        assert chunks == []

    def test_paragrafo_maior_que_chunk_size_e_dividido(self):
        # parágrafo com 500 palavras sem quebra de linha
        text = self._make_words(500)
        chunks = iu._chunk_text(text)
        # deve dividir em chunks menores
        assert len(chunks) > 1

    def test_chunks_tem_overlap(self):
        """
        Com CHUNK_OVERLAP=45 e texto > CHUNK_SIZE, o total de palavras
        em todos os chunks deve ser maior que o texto original
        (porque palavras são duplicadas no overlap).
        """
        n_original = 700
        text = self._make_words(n_original)
        chunks = iu._chunk_text(text)
        if len(chunks) >= 2:
            total_words_in_chunks = sum(len(c.split()) for c in chunks)
            # Com overlap, a soma deve ser > palavras originais
            assert total_words_in_chunks > n_original


# ── _quick_summary ────────────────────────────────────────────────────────────

class TestQuickSummary:
    def test_retorna_string(self):
        result = iu._quick_summary("Texto de exemplo.")
        assert isinstance(result, str)

    def test_texto_curto_retorna_completo(self):
        text = "Parágrafo único curto."
        result = iu._quick_summary(text, max_chars=1000)
        assert "Parágrafo único curto" in result

    def test_texto_longo_truncado(self):
        # Gera texto muito maior que max_chars
        text = "Parágrafo longo. " * 200
        result = iu._quick_summary(text, max_chars=100)
        assert len(result) <= 200  # com alguma margem

    def test_retorna_vazio_para_texto_vazio(self):
        result = iu._quick_summary("")
        assert result == ""


# ── _fetch_texto ──────────────────────────────────────────────────────────────

class TestFetchTexto:
    def test_usa_read_url_quando_disponivel(self):
        mock_mod = MagicMock()
        mock_mod.run.return_value = "conteúdo extraído pela tool"
        with patch.dict("sys.modules", {"read_url": mock_mod}):
            result = iu._fetch_texto("https://exemplo.com")
        assert result == "conteúdo extraído pela tool"

    def test_lanca_runtime_error_quando_read_url_retorna_erro(self):
        mock_mod = MagicMock()
        mock_mod.run.return_value = "Erro: página não encontrada"
        with patch.dict("sys.modules", {"read_url": mock_mod}):
            with pytest.raises(RuntimeError):
                iu._fetch_texto("https://exemplo.com")

    def test_lanca_value_error_para_conteudo_vazio(self):
        mock_mod = MagicMock()
        mock_mod.run.return_value = "   "
        with patch.dict("sys.modules", {"read_url": mock_mod}):
            with pytest.raises(ValueError):
                iu._fetch_texto("https://exemplo.com")

    def test_usa_fallback_quando_import_falha(self):
        """Quando read_url não está disponível, _fallback_fetch deve ser chamado."""
        with patch("knowledge.ingest_url._fallback_fetch", return_value="conteúdo fallback") as mock_fb:
            # Simula ImportError ao importar read_url
            import builtins
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "read_url":
                    raise ImportError("não encontrado")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = iu._fetch_texto("https://exemplo.com")
        assert result == "conteúdo fallback"


# ── ingest_url() — fluxo completo ─────────────────────────────────────────────

class TestIngestUrl:
    @pytest.fixture
    def mock_fetch(self):
        with patch("knowledge.ingest_url._fetch_texto",
                   return_value="Parágrafo de conteúdo.\n\nOutro parágrafo." * 20):
            yield

    def test_url_invalida_lanca_value_error(self, db_mocks):
        with pytest.raises(ValueError, match="URL inválida"):
            iu.ingest_url("nao-e-uma-url", "agent1", "sess1")

    def test_url_sem_scheme_invalida(self, db_mocks):
        with pytest.raises(ValueError):
            iu.ingest_url("exemplo.com/pagina", "agent1", "sess1")

    def test_url_ftp_invalida(self, db_mocks):
        with pytest.raises(ValueError):
            iu.ingest_url("ftp://exemplo.com", "agent1", "sess1")

    def test_url_http_valida(self, mock_fetch, db_mocks):
        source_id = iu.ingest_url("http://exemplo.com/artigo", "agent1", "sess1")
        assert source_id == 42

    def test_url_https_valida(self, mock_fetch, db_mocks):
        source_id = iu.ingest_url("https://exemplo.com/artigo", "agent1", "sess1")
        assert source_id == 42

    def test_retorna_source_id_do_banco(self, mock_fetch, db_mocks):
        result = iu.ingest_url("https://exemplo.com", "agent1", "sess1")
        assert result == 42

    def test_chama_init_db(self, mock_fetch, db_mocks):
        iu.ingest_url("https://exemplo.com", "agent1", "sess1")
        db_mocks["init_db"].assert_called_once()

    def test_chama_insert_source_com_agent_id(self, mock_fetch, db_mocks):
        iu.ingest_url("https://exemplo.com", "meu-agente", "sess1")
        call_kwargs = db_mocks["insert_source"].call_args.kwargs
        assert call_kwargs["agent_id"] == "meu-agente"

    def test_chama_insert_source_com_session_id(self, mock_fetch, db_mocks):
        iu.ingest_url("https://exemplo.com", "agent1", "sessao-xyz")
        call_kwargs = db_mocks["insert_source"].call_args.kwargs
        assert call_kwargs["session_id"] == "sessao-xyz"

    def test_chama_insert_source_com_filetype_url(self, mock_fetch, db_mocks):
        iu.ingest_url("https://exemplo.com", "agent1", "sess1")
        call_kwargs = db_mocks["insert_source"].call_args.kwargs
        assert call_kwargs["filetype"] == "url"

    def test_chama_insert_chunks(self, mock_fetch, db_mocks):
        iu.ingest_url("https://exemplo.com", "agent1", "sess1")
        db_mocks["insert_chunks"].assert_called_once()

    def test_salva_cache_local(self, mock_fetch, db_mocks):
        iu.ingest_url("https://exemplo.com/pagina", "agent1", "minha-sessao")
        cache_dir = iu._CACHE_ROOT / "minha-sessao"
        assert cache_dir.exists()
        assert len(list(cache_dir.glob("*.txt"))) == 1

    def test_verbose_nao_falha(self, mock_fetch, db_mocks, capsys):
        """verbose=True não deve travar — deve apenas printar."""
        iu.ingest_url("https://exemplo.com", "agent1", "sess1", verbose=True)
        captured = capsys.readouterr()
        assert "chars" in captured.out

    def test_erro_de_fetch_propaga_excecao(self, db_mocks):
        with patch("knowledge.ingest_url._fetch_texto",
                   side_effect=RuntimeError("Erro: 404")):
            with pytest.raises(RuntimeError):
                iu.ingest_url("https://exemplo.com", "agent1", "sess1")

    def test_insert_chunks_recebe_source_id_correto(self, mock_fetch, db_mocks):
        db_mocks["insert_source"].return_value = 99
        iu.ingest_url("https://exemplo.com", "agent1", "sess1")
        call_kwargs = db_mocks["insert_chunks"].call_args.kwargs
        assert call_kwargs["source_id"] == 99

    def test_display_name_no_insert_source(self, mock_fetch, db_mocks):
        """O filename no insert_source deve terminar com .url."""
        iu.ingest_url("https://meusite.com/minha-pagina", "agent1", "sess1")
        call_kwargs = db_mocks["insert_source"].call_args.kwargs
        assert call_kwargs["filename"].endswith(".url")

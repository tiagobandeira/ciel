"""
tests/test_core/test_knowledge.py

Cobre o módulo knowledge: ingestão de arquivos .txt/.md e busca FTS5.
Cada teste usa um banco SQLite em arquivo temporário — nunca toca
o knowledge.db real do projeto.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

import knowledge.db as _db
from knowledge.db import init_db, insert_source, insert_chunks, get_session_chain
from knowledge.ingest import extract_text, chunk_text, ingest
from knowledge.retriever import search


# ── fixture: banco isolado ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def banco_isolado(tmp_path, monkeypatch):
    """Redireciona DB_PATH para um arquivo temporário por teste."""
    db_file = tmp_path / "knowledge_test.db"
    monkeypatch.setattr(_db, "DB_PATH", db_file)
    init_db()
    yield db_file


def _ingest(filepath, agent_id="agente1", session_id="sess1"):
    """Atalho: ingere um arquivo sem saída verbose."""
    return ingest(filepath, agent_id=agent_id, session_id=session_id, verbose=False)


def _busca(query, agent_id="agente1", session_id="sess1", min_tokens=1):
    """Atalho: busca sem filtro restritivo de tokens."""
    return search(query, agent_id=agent_id, session_id=session_id, min_tokens=min_tokens)


# ── extract_text ──────────────────────────────────────────────────────────────

class TestExtractText:
    def test_extrai_txt(self, tmp_path):
        f = tmp_path / "nota.txt"
        f.write_text("conteúdo de teste", encoding="utf-8")
        assert extract_text(f) == "conteúdo de teste"

    def test_extrai_md(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Título\n\nParágrafo.", encoding="utf-8")
        texto = extract_text(f)
        assert "Título" in texto
        assert "Parágrafo" in texto

    def test_formato_nao_suportado_lanca_erro(self, tmp_path):
        f = tmp_path / "planilha.xlsx"
        f.write_bytes(b"dados binarios")
        with pytest.raises((ValueError, Exception)):
            extract_text(f)

    def test_pdf_sem_pymupdf_lanca_import_error(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        import sys
        with patch.dict(sys.modules, {"fitz": None}):
            with pytest.raises((ImportError, Exception)):
                extract_text(f)


# ── chunk_text ────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_texto_curto_gera_um_chunk(self):
        texto = "palavra " * 50  # 50 palavras < CHUNK_SIZE=300
        chunks = chunk_text(texto)
        assert len(chunks) == 1

    def test_texto_longo_gera_multiplos_chunks(self):
        texto = "palavra " * 1000
        chunks = chunk_text(texto)
        assert len(chunks) > 1

    def test_chunks_nao_vazios(self):
        texto = "Este é um texto de exemplo para chunking.\n\n" * 20
        for chunk in chunk_text(texto):
            assert chunk.strip() != ""

    def test_texto_vazio_retorna_lista_vazia(self):
        chunks = chunk_text("")
        assert chunks == []


# ── ingest ────────────────────────────────────────────────────────────────────

class TestIngest:
    def test_ingere_txt(self, tmp_path):
        f = tmp_path / "fonte.txt"
        f.write_text("Python é uma linguagem de programação.", encoding="utf-8")
        source_id = _ingest(f)
        assert isinstance(source_id, int)
        assert source_id > 0

    def test_ingere_md(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Guia\n\nEste é um guia de uso do sistema.", encoding="utf-8")
        source_id = _ingest(f)
        assert source_id > 0

    def test_ingere_com_session_shared(self, tmp_path):
        f = tmp_path / "global.txt"
        f.write_text("conteúdo compartilhado entre sessões", encoding="utf-8")
        source_id = _ingest(f, session_id="_shared")
        assert source_id > 0

    def test_arquivo_inexistente_lanca_erro(self, tmp_path):
        with pytest.raises((FileNotFoundError, Exception)):
            _ingest(tmp_path / "nao_existe.txt")

    def test_retorna_source_id_incremental(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("conteúdo a" * 5, encoding="utf-8")
        f2.write_text("conteúdo b" * 5, encoding="utf-8")
        sid1 = _ingest(f1)
        sid2 = _ingest(f2)
        assert sid2 > sid1


# ── search ────────────────────────────────────────────────────────────────────

class TestSearch:
    @pytest.fixture
    def fonte_indexada(self, tmp_path):
        f = tmp_path / "python_guia.txt"
        f.write_text(
            "Python é uma linguagem de programação de alto nível. "
            "É amplamente usada em ciência de dados e inteligência artificial. "
            "A sintaxe do Python é simples e legível. "
            "Django é um framework web para Python. "
            "Flask é um microframework mais leve para desenvolvimento web.",
            encoding="utf-8",
        )
        _ingest(f)
        return f

    def test_busca_retorna_resultado(self, fonte_indexada):
        results = _busca("Python programação")
        assert len(results) > 0

    def test_busca_retorna_conteudo_relevante(self, fonte_indexada):
        results = _busca("Django framework")
        assert any("Django" in r.content or "framework" in r.content for r in results)

    def test_busca_query_vazia_retorna_lista_vazia(self, fonte_indexada):
        results = _busca("")
        assert results == []

    def test_busca_sem_fontes_retorna_lista_vazia(self):
        results = _busca("qualquer coisa", agent_id="agente_sem_fonte")
        assert results == []

    def test_resultado_tem_campos_esperados(self, fonte_indexada):
        results = _busca("Python")
        assert len(results) > 0
        r = results[0]
        assert hasattr(r, "content")
        assert hasattr(r, "filename")
        assert hasattr(r, "score")
        assert hasattr(r, "chunk_index")
        assert hasattr(r, "total_chunks")

    def test_resultado_format_retorna_string(self, fonte_indexada):
        results = _busca("Python")
        assert len(results) > 0
        fmt = results[0].format()
        assert isinstance(fmt, str)
        assert len(fmt) > 0

    def test_format_inclui_nome_do_arquivo(self, fonte_indexada):
        results = _busca("Python")
        assert len(results) > 0
        fmt = results[0].format()
        assert "python_guia.txt" in fmt


# ── escopo de sessão ──────────────────────────────────────────────────────────

class TestSessionScope:
    def test_fonte_sessao_A_nao_aparece_em_sessao_B(self, tmp_path):
        f = tmp_path / "segredo.txt"
        f.write_text(
            "informação ultra secreta exclusiva da sessão A confidencial privada",
            encoding="utf-8",
        )
        _ingest(f, session_id="sessA")
        results = _busca("secreta", session_id="sessB")
        assert len(results) == 0

    def test_fonte_shared_visivel_via_sql(self, tmp_path):
        """_shared é incluído explicitamente na query SQL (OR s.session_id = '_shared')."""
        f = tmp_path / "compartilhado.txt"
        f.write_text(
            "conhecimento compartilhado global disponível para todos os agentes",
            encoding="utf-8",
        )
        _ingest(f, session_id="_shared")
        # com session_id=None, busca apenas _shared
        results = search(
            "compartilhado global",
            agent_id="agente1",
            session_id=None,
            min_tokens=1,
        )
        assert len(results) > 0

    def test_fonte_agente_A_nao_vaza_para_agente_B(self, tmp_path):
        f = tmp_path / "exclusivo.txt"
        f.write_text(
            "dado exclusivo confidencial pertence somente ao agente A privado",
            encoding="utf-8",
        )
        _ingest(f, agent_id="agenteA", session_id="_shared")
        results = search("exclusivo", agent_id="agenteB", session_id=None, min_tokens=1)
        assert len(results) == 0

    def test_session_none_busca_apenas_shared(self, tmp_path):
        f_shared = tmp_path / "shared.txt"
        f_sess = tmp_path / "sessao.txt"
        f_shared.write_text("conteúdo compartilhado global disponível " * 5, encoding="utf-8")
        f_sess.write_text("conteúdo da sessão específica exclusivo " * 5, encoding="utf-8")
        _ingest(f_shared, session_id="_shared")
        _ingest(f_sess, session_id="sessX")

        results = search("exclusivo sessão", agent_id="agente1", session_id=None, min_tokens=1)
        # session_id=None busca apenas _shared, não deve achar o da sessX
        assert all(r.session_id == "_shared" for r in results)

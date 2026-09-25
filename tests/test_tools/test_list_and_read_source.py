"""
tests/test_tools/test_list_and_read_source.py

Cobre:
  - tools/list_sources.py : run() com mock de knowledge.db.list_sources
  - tools/read_source.py  : run() com mock de get_source / get_chunks
"""

import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# tools/list_sources.py
# ─────────────────────────────────────────────────────────────────────────────

class TestListSources:
    def _run(self, *args, **kwargs):
        from tools.list_sources import run
        return run(*args, **kwargs)

    def test_sem_fontes_retorna_mensagem(self):
        with patch("tools.list_sources.db_list_sources", return_value=[]):
            result = self._run(agent_id="agente1", session_id="sess1")
        assert "Nenhuma fonte" in result

    def test_lista_uma_fonte_compartilhada(self):
        fontes = [
            {
                "id": 1,
                "filename": "manual.pdf",
                "n_chunks": 10,
                "session_id": "_shared",
                "summary": "Manual do produto",
            }
        ]
        with patch("tools.list_sources.db_list_sources", return_value=fontes):
            result = self._run(agent_id="agente1", session_id="sess1")
        assert "manual.pdf" in result
        assert "compartilhada" in result
        assert "10 chunks" in result

    def test_lista_fonte_de_sessao(self):
        fontes = [
            {
                "id": 2,
                "filename": "notas.txt",
                "n_chunks": 3,
                "session_id": "sess_abc",
                "summary": None,
            }
        ]
        with patch("tools.list_sources.db_list_sources", return_value=fontes):
            result = self._run(agent_id="agente1", session_id="sess_abc")
        assert "notas.txt" in result
        assert "desta sessão" in result

    def test_resumo_exibido_quando_presente(self):
        fontes = [
            {
                "id": 3,
                "filename": "relatorio.md",
                "n_chunks": 5,
                "session_id": "_shared",
                "summary": "Análise trimestral de vendas",
            }
        ]
        with patch("tools.list_sources.db_list_sources", return_value=fontes):
            result = self._run()
        assert "Análise trimestral" in result

    def test_session_id_vazio_passa_none_para_db(self):
        """session_id em branco deve ser normalizado para None."""
        with patch("tools.list_sources.db_list_sources", return_value=[]) as mock_db:
            self._run(agent_id="agente1", session_id="   ")
        mock_db.assert_called_once_with(agent_id="agente1", session_id=None)

    def test_excecao_retorna_mensagem_de_erro(self):
        with patch("tools.list_sources.db_list_sources", side_effect=RuntimeError("db offline")):
            result = self._run()
        assert "Erro" in result

    def test_contagem_de_fontes_no_cabecalho(self):
        fontes = [
            {"id": 1, "filename": "a.txt", "n_chunks": 1, "session_id": "_shared", "summary": None},
            {"id": 2, "filename": "b.txt", "n_chunks": 2, "session_id": "_shared", "summary": None},
        ]
        with patch("tools.list_sources.db_list_sources", return_value=fontes):
            result = self._run()
        assert "2 fonte" in result


# ─────────────────────────────────────────────────────────────────────────────
# tools/read_source.py
# ─────────────────────────────────────────────────────────────────────────────

class TestReadSource:
    def _run(self, source_id):
        from tools.read_source import run
        return run(source_id)

    def _source(self, **kwargs):
        base = {"id": 1, "filename": "doc.txt", "n_chunks": 2, "session_id": "_shared"}
        base.update(kwargs)
        return base

    def _chunks(self, *textos):
        return [{"content": t} for t in textos]

    def test_fonte_inexistente_retorna_erro(self):
        with patch("tools.read_source.get_source", return_value=None):
            result = self._run(1)
        assert "não encontrada" in result

    def test_sem_chunks_retorna_erro(self):
        with (
            patch("tools.read_source.get_source", return_value=self._source()),
            patch("tools.read_source.get_chunks", return_value=[]),
        ):
            result = self._run(1)
        assert "não tem chunks" in result

    def test_retorna_conteudo_correto(self):
        with (
            patch("tools.read_source.get_source", return_value=self._source(filename="notas.txt")),
            patch("tools.read_source.get_chunks", return_value=self._chunks("chunk A", "chunk B")),
        ):
            result = self._run(1)
        assert "notas.txt" in result
        assert "chunk A" in result
        assert "chunk B" in result

    def test_cabecalho_inclui_metadados(self):
        with (
            patch("tools.read_source.get_source", return_value=self._source(n_chunks=5, session_id="sess1")),
            patch("tools.read_source.get_chunks", return_value=self._chunks("texto")),
        ):
            result = self._run(1)
        assert "5 chunks" in result
        assert "sess1" in result

    def test_conteudo_longo_e_truncado(self):
        from tools.read_source import MAX_CHARS
        texto_longo = "x" * (MAX_CHARS + 1000)
        with (
            patch("tools.read_source.get_source", return_value=self._source()),
            patch("tools.read_source.get_chunks", return_value=self._chunks(texto_longo)),
        ):
            result = self._run(1)
        assert "truncado" in result
        # conteúdo não excede muito o limite
        assert len(result) < MAX_CHARS + 500

    def test_excecao_retorna_mensagem_de_erro(self):
        with patch("tools.read_source.get_source", side_effect=RuntimeError("db offline")):
            result = self._run(1)
        assert "Erro" in result

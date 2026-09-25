"""
tests/test_tools/test_search_and_datetime.py

Cobre:
  - tools/search_knowledge.py : run() com mock de knowledge.retriever
  - tools/get_local_datetime.py: run() — retorno de data/hora local
"""

import pytest
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────────────────
# tools/search_knowledge.py
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchKnowledge:
    def _run(self, query="teste", agent_id="agente1", session_id="", top_k=5):
        from tools.search_knowledge import run
        return run(query=query, agent_id=agent_id, session_id=session_id, top_k=top_k)

    def test_retorna_resultado_da_busca(self):
        with patch("tools.search_knowledge.search_formatted", return_value="Trecho relevante encontrado"):
            result = self._run("minha query")
        assert "Trecho relevante encontrado" in result

    def test_session_id_vazio_passa_none(self):
        with patch("tools.search_knowledge.search_formatted", return_value="ok") as mock_sf:
            self._run(session_id="   ")
        assert mock_sf.call_args.kwargs["session_id"] is None

    def test_top_k_minimo_e_1(self):
        """top_k=0 deve ser corrigido para 1."""
        with patch("tools.search_knowledge.search_formatted", return_value="ok") as mock_sf:
            self._run(top_k=0)
        assert mock_sf.call_args.kwargs["top_k"] >= 1

    def test_top_k_maximo_e_10(self):
        """top_k=999 deve ser limitado a 10."""
        with patch("tools.search_knowledge.search_formatted", return_value="ok") as mock_sf:
            self._run(top_k=999)
        assert mock_sf.call_args.kwargs["top_k"] <= 10

    def test_excecao_retorna_mensagem_de_erro(self):
        with patch("tools.search_knowledge.search_formatted", side_effect=RuntimeError("db offline")):
            result = self._run("query")
        assert "Erro" in result


# ─────────────────────────────────────────────────────────────────────────────
# tools/get_local_datetime.py
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLocalDatetime:
    def _run(self):
        from tools.get_local_datetime import run
        return run()

    def test_retorna_dict_com_chaves_esperadas(self):
        result = self._run()
        assert isinstance(result, dict)
        assert "datetime" in result
        assert "date" in result
        assert "time" in result

    def test_formato_datetime(self):
        """Deve seguir o padrão YYYY-MM-DD HH:MM:SS."""
        import re
        result = self._run()
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result["datetime"])

    def test_formato_date(self):
        import re
        result = self._run()
        assert re.match(r"\d{4}-\d{2}-\d{2}", result["date"])

    def test_formato_time(self):
        import re
        result = self._run()
        assert re.match(r"\d{2}:\d{2}:\d{2}", result["time"])

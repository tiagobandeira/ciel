"""
tests/test_tools/test_list_skills.py

Cobre tools/list_skills.py:
  - _extract_metadata: frontmatter YAML, fallback description, mode
  - run(): pasta inexistente, pasta vazia, skills listadas corretamente,
           leitura com erro gracioso
"""

import pytest
from pathlib import Path
from unittest.mock import patch
import importlib


# ── fixture: carrega o módulo apontando para skills/ temporária ───────────────

@pytest.fixture
def list_skills(tmp_path, monkeypatch):
    """Importa list_skills.py com _SKILLS_DIR redirecionado para tmp_path."""
    import tools.list_skills as mod
    monkeypatch.setattr(mod, "_SKILLS_DIR", tmp_path)
    # garante que run() veja o novo valor (ela lê o global do módulo)
    return mod


# ── _extract_metadata ─────────────────────────────────────────────────────────

class TestExtractMetadata:
    def _meta(self, text):
        from tools.list_skills import _extract_metadata
        return _extract_metadata(text)

    def test_frontmatter_description(self):
        text = "---\ndescription: Skill de exemplo\nmode: auto\n---\n\n# Título"
        m = self._meta(text)
        assert m["description"] == "Skill de exemplo"

    def test_frontmatter_mode(self):
        text = "---\ndescription: Algo\nmode: manual\n---\n"
        m = self._meta(text)
        assert m["mode"] == "manual"

    def test_frontmatter_sem_mode_retorna_vazio(self):
        text = "---\ndescription: Só descrição\n---\n"
        m = self._meta(text)
        assert m["mode"] == ""

    def test_fallback_description_via_chave(self):
        """Sem frontmatter, usa linha 'description: ...' no corpo."""
        text = "# Título\n\ndescription: Descrição fallback\n"
        m = self._meta(text)
        assert m["description"] == "Descrição fallback"

    def test_fallback_description_primeiro_paragrafo(self):
        """Sem frontmatter e sem chave, usa primeiro parágrafo após título."""
        text = "# Minha Skill\n\nEste é o primeiro parágrafo relevante."
        m = self._meta(text)
        assert "primeiro parágrafo" in m["description"]

    def test_texto_vazio_retorna_sem_erros(self):
        m = self._meta("")
        assert m["description"] == ""
        assert m["mode"] == ""

    def test_description_truncada_em_120_chars(self):
        longa = "x" * 200
        text = f"# Título\n\n{longa}"
        m = self._meta(text)
        assert len(m["description"]) <= 120


# ── run() ─────────────────────────────────────────────────────────────────────

class TestRun:
    def test_pasta_nao_existe_retorna_mensagem(self, list_skills, tmp_path, monkeypatch):
        """_SKILLS_DIR aponta para diretório que não existe."""
        monkeypatch.setattr(list_skills, "_SKILLS_DIR", tmp_path / "nao_existe")
        result = list_skills.run()
        assert "não encontrada" in result

    def test_pasta_vazia_retorna_mensagem(self, list_skills, tmp_path):
        result = list_skills.run()
        assert "Nenhuma skill" in result

    def test_lista_skill_com_frontmatter(self, list_skills, tmp_path):
        skill = tmp_path / "minha_skill.md"
        skill.write_text(
            "---\ndescription: Faz algo incrível\nmode: auto\n---\n\n# Minha Skill",
            encoding="utf-8",
        )
        result = list_skills.run()
        assert "minha_skill" in result
        assert "Faz algo incrível" in result

    def test_lista_multiplas_skills_ordenadas(self, list_skills, tmp_path):
        (tmp_path / "zebra.md").write_text("# Zebra\n\nDescrição da zebra.", encoding="utf-8")
        (tmp_path / "alfa.md").write_text("# Alfa\n\nDescrição alfa.", encoding="utf-8")
        result = list_skills.run()
        pos_alfa = result.index("alfa")
        pos_zebra = result.index("zebra")
        assert pos_alfa < pos_zebra  # ordenadas alfabeticamente

    def test_skill_sem_descricao_usa_fallback(self, list_skills, tmp_path):
        (tmp_path / "sem_desc.md").write_text("sem título nem frontmatter", encoding="utf-8")
        result = list_skills.run()
        assert "sem_desc" in result

    def test_skill_com_erro_de_leitura_retorna_gracioso(self, list_skills, tmp_path):
        """Se read_text falhar, o skill é listado com 'erro ao ler arquivo'."""
        skill = tmp_path / "corrompida.md"
        skill.write_text("conteúdo ok", encoding="utf-8")
        with patch("pathlib.Path.read_text", side_effect=OSError("disco cheio")):
            result = list_skills.run()
        assert "corrompida" in result
        assert "erro" in result.lower()

    def test_mode_aparece_na_listagem(self, list_skills, tmp_path):
        (tmp_path / "com_mode.md").write_text(
            "---\ndescription: Com modo\nmode: manual\n---\n",
            encoding="utf-8",
        )
        result = list_skills.run()
        assert "mode: manual" in result

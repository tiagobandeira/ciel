"""
tests/test_core/test_skill_loader.py

Cobre `skill_loader.py`: front-matter, metadados, leitura, listagem,
bindings de persona e proteção contra path traversal.
"""

from pathlib import Path

import pytest

from skill_loader import (
    Skill,
    SkillBinding,
    extract_metadata,
    list_skills,
    load_skill,
    load_text,
    parse_front_matter,
    skills_for_agent,
)


# ── front-matter ──────────────────────────────────────────────────────────

class TestParseFrontMatter:
    def test_basico(self):
        meta, body = parse_front_matter(
            "---\nmode: code\ndescription: Faz X\n---\n# Título\ncorpo"
        )
        assert meta == {"mode": "code", "description": "Faz X"}
        assert body == "# Título\ncorpo"

    def test_sem_front_matter(self):
        text = "# Título\n\ncorpo"
        meta, body = parse_front_matter(text)
        assert meta == {}
        assert body == text

    def test_texto_vazio(self):
        assert parse_front_matter("") == ({}, "")

    def test_aspas_removidas(self):
        meta, _ = parse_front_matter(
            '---\nmode: "code"\ndescription: \'com aspas\'\n---\n'
        )
        assert meta["mode"] == "code"
        assert meta["description"] == "com aspas"

    def test_crlf(self):
        meta, body = parse_front_matter(
            "---\r\nmode: code\r\n---\r\ncorpo\r\n"
        )
        assert meta["mode"] == "code"
        assert body == "corpo\r\n"

    def test_chaves_normalizadas_e_comentarios_ignorados(self):
        meta, _ = parse_front_matter(
            "---\n# comentário\nMode: code\nrequer: secundario\n---\n"
        )
        assert meta["mode"] == "code"
        assert meta["requer"] == "secundario"

    def test_front_matter_sem_fechamento_nao_e_parseado(self):
        text = "---\nmode: code\n# sem fechamento"
        meta, body = parse_front_matter(text)
        assert meta == {}
        assert body == text

    def test_bom_removido(self):
        meta, _ = parse_front_matter("\ufeff---\nmode: code\n---\n")
        assert meta["mode"] == "code"


# ── metadados (compatível com list_skills) ────────────────────────────────

class TestExtractMetadata:
    def test_frontmatter(self):
        info = extract_metadata("---\ndescription: Skill X\nmode: auto\n---\n")
        assert info == {"description": "Skill X", "mode": "auto"}

    def test_mode_ausente(self):
        info = extract_metadata("---\ndescription: Só desc\n---\n")
        assert info["mode"] == ""

    def test_fallback_chave_no_corpo(self):
        info = extract_metadata("# Título\n\ndescription: fallback\n")
        assert info["description"] == "fallback"

    def test_fallback_primeiro_paragrafo(self):
        info = extract_metadata("# Minha Skill\n\nPrimeiro parágrafo.")
        assert info["description"] == "Primeiro parágrafo."

    def test_trunca_em_120(self):
        info = extract_metadata("# T\n\n" + "x" * 200)
        assert len(info["description"]) <= 120

    def test_vazio(self):
        assert extract_metadata("") == {"description": "", "mode": ""}


# ── leitura ───────────────────────────────────────────────────────────────

@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "frontend.md").write_text(
        "---\nmode: code\ndescription: Frontend rico\nrequer: secundario\n"
        "tools: calculator, read_file\n---\n# Frontend\ncorpo\n",
        encoding="utf-8",
    )
    (d / "simples.md").write_text("# Simples\n\nDescrição simples.\n", encoding="utf-8")
    return d


class TestLoadSkill:
    def test_carrega_com_metadados(self, skills_dir):
        skill = load_skill("frontend", skills_dir=skills_dir)
        assert skill is not None
        assert skill.ok
        assert skill.name == "frontend"
        assert skill.description == "Frontend rico"
        assert skill.mode == "code"
        assert skill.requires == "secundario"
        assert skill.tools == ["calculator", "read_file"]
        assert skill.body.startswith("# Frontend")

    def test_aceita_nome_com_md(self, skills_dir):
        assert load_skill("simples.md", skills_dir=skills_dir).name == "simples"

    def test_inexistente_retorna_none(self, skills_dir):
        assert load_skill("nao-existe", skills_dir=skills_dir) is None

    def test_pasta_inexistente_retorna_none(self, tmp_path):
        assert load_skill("x", skills_dir=tmp_path / "nada") is None

    def test_erro_de_leitura_nao_explode(self, skills_dir, monkeypatch):
        original = Path.read_text

        def explode(self, *a, **kw):
            if self.name == "simples.md":
                raise OSError("disco cheio")
            return original(self, *a, **kw)

        monkeypatch.setattr(Path, "read_text", explode)
        skill = load_skill("simples", skills_dir=skills_dir)
        assert skill is not None
        assert skill.ok is False
        assert "disco cheio" in skill.error

    def test_path_traversal_bloqueado(self, tmp_path):
        base = tmp_path / "skills"
        base.mkdir()
        fora = tmp_path / "segredo.md"
        fora.write_text("# segredo", encoding="utf-8")

        assert load_skill("../segredo", skills_dir=base) is None
        assert load_text("../segredo", skills_dir=base) is None

    def test_texto_completo_preserva_front_matter(self, skills_dir):
        text = load_text("frontend", skills_dir=skills_dir)
        assert text.startswith("---\nmode: code")
        assert "# Frontend" in text


# ── listagem ──────────────────────────────────────────────────────────────

class TestListSkills:
    def test_ordenado(self, skills_dir):
        names = [s.name for s in list_skills(skills_dir)]
        assert names == ["frontend", "simples"]

    def test_pasta_inexistente(self, tmp_path):
        assert list_skills(tmp_path / "nada") == []

    def test_pasta_vazia(self, tmp_path):
        (tmp_path / "skills").mkdir()
        assert list_skills(tmp_path / "skills") == []

    def test_ignora_nao_md(self, skills_dir):
        (skills_dir / "meta.json").write_text("{}", encoding="utf-8")
        assert len(list_skills(skills_dir)) == 2


# ── bindings de persona ───────────────────────────────────────────────────

class TestSkillsForAgent:
    def test_resolve_niveis(self, skills_dir):
        agent = {"skills": [
            {"name": "frontend", "level": "obrigatoria"},
            {"name": "simples", "level": "sugerida"},
        ]}
        bindings = skills_for_agent(agent, skills_dir=skills_dir)
        assert [b.skill.name for b in bindings] == ["frontend", "simples"]
        assert [b.level for b in bindings] == ["obrigatoria", "sugerida"]
        assert isinstance(bindings[0], SkillBinding)
        assert isinstance(bindings[0].skill, Skill)

    def test_nivel_desconhecido_vira_opcional(self, skills_dir):
        bindings = skills_for_agent(
            {"skills": [{"name": "simples", "level": "urgente"}]},
            skills_dir=skills_dir,
        )
        assert bindings[0].level == "opcional"

    def test_skill_ausente_e_ignorada(self, skills_dir):
        bindings = skills_for_agent(
            {"skills": [{"name": "nao-existe"}, {"name": "simples"}]},
            skills_dir=skills_dir,
        )
        assert [b.skill.name for b in bindings] == ["simples"]

    def test_duplicata_ignorada(self, skills_dir):
        bindings = skills_for_agent(
            {"skills": [{"name": "simples"}, {"name": "simples"}]},
            skills_dir=skills_dir,
        )
        assert len(bindings) == 1

    def test_filtro_por_nivel(self, skills_dir):
        agent = {"skills": [
            {"name": "frontend", "level": "obrigatoria"},
            {"name": "simples", "level": "opcional"},
        ]}
        bindings = skills_for_agent(
            agent, skills_dir=skills_dir, levels=("obrigatoria",)
        )
        assert [b.skill.name for b in bindings] == ["frontend"]

    def test_agente_sem_skills(self, skills_dir):
        assert skills_for_agent({}, skills_dir=skills_dir) == []

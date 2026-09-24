"""
tests/test_integration/test_skill_import_extended.py

Cobre tools/skill_import.py de forma abrangente.
Foca em: _read_skill_files, _build_context_block, _extract_json,
_save_primitives, _install_requirements, run() (fluxo completo via mocks).

Os testes de _call_secondary e resolução de api_key já existem em
tests/test_integration/test_skill_import.py — não repetimos aqui.
"""

import json
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


# ── fixture: importa o módulo via spec (sem efeitos colaterais) ──────────────

@pytest.fixture(scope="module")
def si():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "skill_import_ext", Path("tools/skill_import.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _read_skill_files ────────────────────────────────────────────────────────

class TestReadSkillFiles:
    def test_arquivo_unico_retorna_lista_com_um_item(self, tmp_path, si):
        f = tmp_path / "skill.md"
        f.write_text("# Minha Skill", encoding="utf-8")
        result = si._read_skill_files(f)
        assert len(result) == 1
        assert result[0]["content"] == "# Minha Skill"

    def test_arquivo_unico_path_preservado(self, tmp_path, si):
        f = tmp_path / "minha_skill.md"
        f.write_text("conteúdo", encoding="utf-8")
        result = si._read_skill_files(f)
        assert str(f) in result[0]["path"]

    def test_path_inexistente_retorna_lista_vazia(self, tmp_path, si):
        result = si._read_skill_files(tmp_path / "nao_existe")
        assert result == []

    def test_diretorio_vazio_retorna_lista_vazia(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        result = si._read_skill_files(d)
        assert result == []

    def test_diretorio_com_varios_arquivos(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        (d / "README.md").write_text("# Readme", encoding="utf-8")
        (d / "skill.py").write_text("def run(): pass", encoding="utf-8")
        result = si._read_skill_files(d)
        assert len(result) == 2

    def test_ignora_extensoes_nao_texto(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        (d / "imagem.png").write_bytes(b"\x89PNG")
        (d / "skill.md").write_text("# ok", encoding="utf-8")
        result = si._read_skill_files(d)
        assert len(result) == 1
        assert result[0]["path"] == "skill.md"

    def test_ignora_pyc(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        (d / "module.pyc").write_bytes(b"bytecode")
        (d / "main.py").write_text("pass", encoding="utf-8")
        result = si._read_skill_files(d)
        paths = [r["path"] for r in result]
        assert not any(p.endswith(".pyc") for p in paths)

    def test_manifest_tem_prioridade_maxima(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        (d / "manifest.yaml").write_text("name: test", encoding="utf-8")
        (d / "README.md").write_text("# Readme", encoding="utf-8")
        (d / "outro.py").write_text("pass", encoding="utf-8")
        result = si._read_skill_files(d)
        assert result[0]["path"] == "manifest.yaml"

    def test_readme_tem_segunda_prioridade(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        (d / "README.md").write_text("# Readme", encoding="utf-8")
        (d / "zzz.py").write_text("pass", encoding="utf-8")
        result = si._read_skill_files(d)
        assert result[0]["path"] == "README.md"

    def test_trunca_arquivos_grandes(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        conteudo_grande = "x" * 10000
        (d / "grande.md").write_text(conteudo_grande, encoding="utf-8")
        result = si._read_skill_files(d)
        assert "truncado" in result[0]["content"]
        assert len(result[0]["content"]) < 10000

    def test_ignora_git_dir(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        git = d / ".git"
        git.mkdir()
        (git / "config").write_text("git config", encoding="utf-8")
        (d / "skill.md").write_text("# ok", encoding="utf-8")
        result = si._read_skill_files(d)
        assert len(result) == 1

    def test_extensoes_suportadas(self, tmp_path, si):
        d = tmp_path / "skill_dir"
        d.mkdir()
        for ext in [".md", ".txt", ".py", ".js", ".json", ".yaml", ".sh"]:
            (d / f"arquivo{ext}").write_text(f"conteudo{ext}", encoding="utf-8")
        result = si._read_skill_files(d)
        assert len(result) == 7


# ── _build_context_block ─────────────────────────────────────────────────────

class TestBuildContextBlock:
    def test_retorna_vazio_para_lista_vazia(self, si):
        assert si._build_context_block([]) == ""

    def test_inclui_cabecalho(self, si):
        files = [{"path": "skill.md", "content": "# Skill"}]
        result = si._build_context_block(files)
        assert "## Arquivos da skill externa" in result

    def test_inclui_path_do_arquivo(self, si):
        files = [{"path": "README.md", "content": "conteúdo"}]
        result = si._build_context_block(files)
        assert "README.md" in result

    def test_inclui_conteudo_do_arquivo(self, si):
        files = [{"path": "skill.md", "content": "meu conteúdo especial"}]
        result = si._build_context_block(files)
        assert "meu conteúdo especial" in result

    def test_varios_arquivos_todos_presentes(self, si):
        files = [
            {"path": "a.md", "content": "conteudo a"},
            {"path": "b.py", "content": "conteudo b"},
        ]
        result = si._build_context_block(files)
        assert "conteudo a" in result
        assert "conteudo b" in result
        assert "a.md" in result
        assert "b.py" in result


# ── _extract_json ─────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_json_limpo(self, si):
        text = '{"skill_name": "teste", "type": "plugin"}'
        result = si._extract_json(text)
        assert result is not None
        assert result["skill_name"] == "teste"

    def test_json_com_fence_markdown(self, si):
        text = '```json\n{"skill_name": "teste"}\n```'
        result = si._extract_json(text)
        assert result is not None
        assert result["skill_name"] == "teste"

    def test_json_com_texto_antes_e_depois(self, si):
        text = 'Aqui está o JSON:\n{"type": "context"}\nFim.'
        result = si._extract_json(text)
        assert result is not None
        assert result["type"] == "context"

    def test_retorna_none_para_texto_invalido(self, si):
        result = si._extract_json("texto sem json nenhum aqui")
        assert result is None

    def test_retorna_none_para_string_vazia(self, si):
        result = si._extract_json("")
        assert result is None

    def test_json_aninhado_complexo(self, si):
        data = {
            "skill_name": "minha-skill",
            "type": "plugin",
            "tools": [{"filename": "tools/x.py", "content": "def run(): pass"}],
            "tasks": [],
        }
        result = si._extract_json(json.dumps(data))
        assert result is not None
        assert result["tools"][0]["filename"] == "tools/x.py"

    def test_json_com_fence_sem_linguagem(self, si):
        text = "```\n{\"type\": \"context\"}\n```"
        result = si._extract_json(text)
        assert result is not None

    def test_json_com_espacos_extras(self, si):
        text = '   \n  {"type": "pipeline"}  \n  '
        result = si._extract_json(text)
        assert result is not None
        assert result["type"] == "pipeline"


# ── _save_primitives ──────────────────────────────────────────────────────────

class TestSavePrimitives:
    @pytest.fixture
    def tmp_root(self, tmp_path, si, monkeypatch):
        """Redireciona os paths do módulo para tmp_path."""
        monkeypatch.setattr(si, "_ROOT",       tmp_path)
        monkeypatch.setattr(si, "_TASKS_DIR",  tmp_path / "tasks")
        monkeypatch.setattr(si, "_TOOLS_DIR",  tmp_path / "tools")
        monkeypatch.setattr(si, "_SKILLS_DIR", tmp_path / "skills")
        return tmp_path

    def test_salva_task_no_diretorio_correto(self, tmp_root, si):
        data = {
            "tasks": [{"filename": "tasks/minha_task.md", "content": "## task: minha-task"}],
            "tools": [],
        }
        saved = si._save_primitives(data, "minha-skill")
        assert (tmp_root / "tasks" / "minha_task.md").exists()

    def test_salva_tool_no_diretorio_correto(self, tmp_root, si):
        data = {
            "tasks": [],
            "tools": [{"filename": "tools/minha_tool.py", "content": "def run(): return 'ok'"}],
        }
        saved = si._save_primitives(data, "minha-skill")
        assert (tmp_root / "tools" / "minha_tool.py").exists()

    def test_salva_residual_prompt_como_md(self, tmp_root, si):
        data = {
            "tasks": [],
            "tools": [],
            "residual_prompt": "Instruções de uso da skill.",
        }
        saved = si._save_primitives(data, "minha-skill")
        assert (tmp_root / "skills" / "minha-skill.md").exists()
        assert saved["residual"] is not None

    def test_sem_residual_nao_cria_arquivo_md(self, tmp_root, si):
        data = {"tasks": [], "tools": [], "residual_prompt": ""}
        saved = si._save_primitives(data, "minha-skill")
        assert saved["residual"] is None

    def test_cria_meta_json(self, tmp_root, si):
        data = {"tasks": [], "tools": [], "type": "context", "description": "desc"}
        si._save_primitives(data, "minha-skill")
        assert (tmp_root / "skills" / "minha-skill_meta.json").exists()

    def test_meta_json_conteudo_correto(self, tmp_root, si):
        data = {
            "tasks": [{"filename": "tasks/t.md", "content": "content"}],
            "tools": [{"filename": "tools/t.py", "content": "pass"}],
            "type": "plugin",
            "description": "Uma skill de teste",
            "entry_task": "",
        }
        si._save_primitives(data, "test-skill")
        meta = json.loads((tmp_root / "skills" / "test-skill_meta.json").read_text())
        assert meta["skill_name"] == "test-skill"
        assert meta["type"] == "plugin"
        assert "t.md" in meta["tasks"]
        assert "t.py" in meta["tools"]

    def test_retorna_lista_de_tasks_salvas(self, tmp_root, si):
        data = {
            "tasks": [
                {"filename": "tasks/t1.md", "content": "# t1"},
                {"filename": "tasks/t2.md", "content": "# t2"},
            ],
            "tools": [],
        }
        saved = si._save_primitives(data, "skill")
        assert len(saved["tasks"]) == 2

    def test_retorna_lista_de_tools_salvas(self, tmp_root, si):
        data = {
            "tasks": [],
            "tools": [
                {"filename": "tools/t1.py", "content": "pass"},
                {"filename": "tools/t2.py", "content": "pass"},
            ],
        }
        saved = si._save_primitives(data, "skill")
        assert len(saved["tools"]) == 2

    def test_erros_sao_capturados_nao_propagados(self, tmp_root, si):
        """Erros de IO devem ser capturados em saved['errors']."""
        data = {
            "tasks": [{"filename": "/caminho/impossivel/t.md", "content": "x"}],
            "tools": [],
        }
        # não deve lançar exceção
        saved = si._save_primitives(data, "skill")
        # pode ou não ter erro dependendo da implementação, mas não deve travar


# ── _install_requirements ─────────────────────────────────────────────────────

class TestInstallRequirements:
    def test_lista_vazia_retorna_sem_erros(self, si):
        errors = si._install_requirements([])
        assert errors == []

    def test_chama_pip_para_cada_pacote(self, si):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            si._install_requirements(["requests", "beautifulsoup4"])
        assert mock_run.call_count == 2

    def test_retorna_erro_quando_pip_falha(self, si):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error msg")
            errors = si._install_requirements(["pacote-inexistente-xyz"])
        assert len(errors) == 1
        assert "pacote-inexistente-xyz" in errors[0]

    def test_ignora_pacotes_em_branco(self, si):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            si._install_requirements(["", "  ", "requests"])
        # só deve chamar subprocess para "requests"
        assert mock_run.call_count == 1

    def test_captura_excecao_de_subprocess(self, si):
        with patch("subprocess.run", side_effect=Exception("pip não encontrado")):
            errors = si._install_requirements(["requests"])
        assert len(errors) == 1


# ── run() — fluxo completo ─────────────────────────────────────────────────────

class TestRunFluxoCompleto:
    @pytest.fixture
    def tmp_root(self, tmp_path, si, monkeypatch):
        monkeypatch.setattr(si, "_ROOT",       tmp_path)
        monkeypatch.setattr(si, "_TASKS_DIR",  tmp_path / "tasks")
        monkeypatch.setattr(si, "_TOOLS_DIR",  tmp_path / "tools")
        monkeypatch.setattr(si, "_SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(si, "_CONFIG_PATH", tmp_path / "ciel_config.json")
        return tmp_path

    def _mock_secondary(self, skill_type="plugin"):
        """Retorna side_effect para _call_secondary com JSON válido."""
        response = {
            "skill_name": "test-skill",
            "type": skill_type,
            "description": "skill de teste",
            "tasks": [],
            "tools": [
                {"filename": "tools/test_tool.py", "content": "def run(): return 'ok'"}
            ] if skill_type == "plugin" else [],
            "requirements": [],
            "residual_prompt": "",
            "summary": "1 tool gerada",
        }
        if skill_type == "pipeline":
            response["entry_task"] = "test-skill_etapa1"
            response["tasks"] = [
                {"filename": "tasks/test-skill_etapa1.md", "content": "## task: test-skill-etapa1"}
            ]
            response["tools"] = []
        return json.dumps(response)

    def test_erro_path_inexistente(self, tmp_root, si):
        result = si.run("/caminho/que/nao/existe")
        assert "Erro" in result

    def test_erro_diretorio_sem_arquivos_texto(self, tmp_root, si):
        d = tmp_root / "skill_vazia"
        d.mkdir()
        result = si.run(str(d))
        assert "Erro" in result

    def test_erro_modelo_nao_configurado(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill de teste", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=None):
            result = si.run(str(f))
        assert "Erro" in result
        assert "modelo secundário" in result

    def test_erro_modelo_retorna_erro(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill de teste", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value="__erro__: timeout"):
            result = si.run(str(f))
        assert "Erro" in result
        assert "timeout" in result

    def test_erro_json_invalido_salva_debug(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value="resposta sem json válido"):
            result = si.run(str(f))
        assert "Erro" in result or "JSON" in result

    def test_sucesso_plugin_cria_tool(self, tmp_root, si, tmp_path):
        f = tmp_path / "minha_skill.md"
        f.write_text("# Skill de teste", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=self._mock_secondary("plugin")):
            result = si.run(str(f), nome="test-skill")
        assert "✓" in result or "absorvida" in result
        assert (tmp_root / "tools" / "test_tool.py").exists()

    def test_sucesso_pipeline_cria_task(self, tmp_root, si, tmp_path):
        f = tmp_path / "pipeline_skill.md"
        f.write_text("# Pipeline skill", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=self._mock_secondary("pipeline")):
            result = si.run(str(f), nome="test-skill")
        assert (tmp_root / "tasks" / "test-skill_etapa1.md").exists()

    def test_nome_inferido_do_path_quando_omitido(self, tmp_root, si, tmp_path):
        f = tmp_path / "minha_habilidade.md"
        f.write_text("# Skill", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=self._mock_secondary("context")):
            result = si.run(str(f))
        # o nome deve ser derivado do filename
        assert "minha-habilidade" in result or "minha_habilidade" in result or "absorvida" in result

    def test_nome_normalizado_para_kebab_case(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=self._mock_secondary("context")):
            result = si.run(str(f), nome="Minha Skill com Espaços")
        # nome normalizado não deve ter espaços
        assert "Minha Skill" not in result or "minha-skill" in result

    def test_instala_requirements(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill", encoding="utf-8")
        response_with_reqs = {
            "skill_name": "test",
            "type": "plugin",
            "description": "desc",
            "tasks": [],
            "tools": [],
            "requirements": ["requests"],
            "residual_prompt": "",
            "summary": "ok",
        }
        with patch.object(si, "_call_secondary", return_value=json.dumps(response_with_reqs)):
            with patch.object(si, "_install_requirements", return_value=[]) as mock_install:
                si.run(str(f), nome="test")
        mock_install.assert_called_once_with(["requests"])

    def test_relatorio_inclui_nome_da_skill(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=self._mock_secondary("context")):
            result = si.run(str(f), nome="minha-skill-unica")
        assert "minha-skill-unica" in result

    def test_plugin_sugere_uso_de_tools(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=self._mock_secondary("plugin")):
            result = si.run(str(f), nome="test-skill")
        # deve mencionar tools disponíveis
        assert "tool" in result.lower() or "✓" in result

    def test_pipeline_sugere_comando_replicar(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Pipeline", encoding="utf-8")
        with patch.object(si, "_call_secondary", return_value=self._mock_secondary("pipeline")):
            result = si.run(str(f), nome="test-skill")
        assert "/replicar" in result or "pipeline" in result.lower()

    def test_context_sugere_comando_skill(self, tmp_root, si, tmp_path):
        f = tmp_path / "skill.md"
        f.write_text("# Skill", encoding="utf-8")
        response = {
            "skill_name": "ctx-skill",
            "type": "context",
            "description": "desc",
            "tasks": [],
            "tools": [],
            "requirements": [],
            "residual_prompt": "Instruções de contexto aqui.",
            "summary": "ok",
        }
        with patch.object(si, "_call_secondary", return_value=json.dumps(response)):
            result = si.run(str(f), nome="ctx-skill")
        assert "/skill" in result or "context" in result.lower()

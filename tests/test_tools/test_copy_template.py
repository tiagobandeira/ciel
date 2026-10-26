"""Testes da tool copy_template (scaffold)."""

from pathlib import Path

import tools.copy_template as copy_template


def _template(tmp_path, name="demo"):
    root = tmp_path / "templates"
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "index.html").write_text("<html></html>", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "app.js").write_text("// js", encoding="utf-8")
    return root


def test_copia_template(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_template, "TEMPLATES_DIR", _template(tmp_path))
    dest = tmp_path / "saida"

    result = copy_template.run("demo", str(dest))

    assert "2 arquivo(s)" in result
    assert (dest / "index.html").read_text(encoding="utf-8") == "<html></html>"
    assert (dest / "sub" / "app.js").read_text(encoding="utf-8") == "// js"


def test_preserva_existente_por_padrao(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_template, "TEMPLATES_DIR", _template(tmp_path))
    dest = tmp_path / "saida"
    dest.mkdir()
    (dest / "index.html").write_text("meu conteúdo", encoding="utf-8")

    result = copy_template.run("demo", str(dest))

    assert "1 preservado" in result
    assert (dest / "index.html").read_text(encoding="utf-8") == "meu conteúdo"


def test_overwrite_true(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_template, "TEMPLATES_DIR", _template(tmp_path))
    dest = tmp_path / "saida"
    dest.mkdir()
    (dest / "index.html").write_text("velho", encoding="utf-8")

    copy_template.run("demo", str(dest), overwrite=True)

    assert (dest / "index.html").read_text(encoding="utf-8") == "<html></html>"


def test_template_invalido(tmp_path, monkeypatch):
    monkeypatch.setattr(copy_template, "TEMPLATES_DIR", _template(tmp_path))
    assert "inválido" in copy_template.run("../x", str(tmp_path / "x"))
    assert "não existe" in copy_template.run("nao_existe", str(tmp_path / "x"))


def test_metadata_de_permissao():
    from tools_registry import load_tools

    tools = load_tools()
    assert "copy_template" in tools
    assert tools["copy_template"]["permissions"] == {"dest": "write"}

"""Testes do prepare_kernel (manifesto + template + smoke)."""

from pathlib import Path

import yaml

import tools.copy_template as copy_template
import tools.prepare_kernel as prepare_kernel


def test_prepara_web_static_app(tmp_path):
    dest = tmp_path / "app"
    result = prepare_kernel.run("web_static", str(dest), variant="app")
    assert "Smoke ok" in result
    assert (dest / "index.html").is_file()
    assert (dest / "style.css").is_file()
    assert (dest / "app.js").is_file()
    state = yaml.safe_load((dest / ".ciel" / "kernel.json").read_text(encoding="utf-8"))
    assert state["kernel"] == "web_static"
    assert state["variant"] == "app"


def test_variante_inexistente(tmp_path):
    result = prepare_kernel.run("web_static", str(tmp_path / "x"), variant="nao_existe")
    assert "não existe" in result


def test_kernel_inexistente(tmp_path):
    result = prepare_kernel.run("nao_existe", str(tmp_path / "x"))
    assert "não encontrado" in result


def test_variaveis_substituidas(tmp_path, monkeypatch):
    kernels = tmp_path / "kernels"
    templates = tmp_path / "templates"
    (kernels / "demo").mkdir(parents=True)
    (templates / "demo").mkdir(parents=True)
    (templates / "demo" / "index.html").write_text(
        "<title>{{title}}</title>", encoding="utf-8"
    )
    (kernels / "demo" / "kernel.yaml").write_text(
        "name: demo\nversion: 1\n"
        "variants:\n  app:\n    template: demo\n    checks: [index.html]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_kernel, "KERNELS_DIR", kernels)
    monkeypatch.setattr(copy_template, "TEMPLATES_DIR", templates)

    dest = tmp_path / "saida"
    result = prepare_kernel.run(
        "demo", str(dest), variant="app", variables={"title": "Meu App"}
    )

    assert "Smoke ok" in result
    assert "Meu App" in (dest / "index.html").read_text(encoding="utf-8")

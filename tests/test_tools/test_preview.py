"""Testes do preview estático local."""

import re
import urllib.request

import tools.preview_manager as manager


def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "STATE_DIR", tmp_path / "preview")
    monkeypatch.setattr(manager, "STATE_FILE", tmp_path / "preview" / "previews.json")


def test_start_serve_e_stop(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")

    result = manager.start(str(site), port=0)
    match = re.search(r"http://127\.0\.0\.1:(\d+)/", result)
    assert match, result
    preview_id = f"preview-{match.group(1)}"

    with urllib.request.urlopen(f"http://127.0.0.1:{match.group(1)}/", timeout=3) as resp:
        assert resp.status == 200
        assert "ok" in resp.read().decode("utf-8")

    assert preview_id in manager.list_all()
    assert "encerrado" in manager.stop(preview_id)
    assert "Nenhum preview" in manager.list_all()


def test_start_pasta_inexistente(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    assert "não encontrada" in manager.start(str(tmp_path / "nao_existe"))


def test_stop_desconhecido(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    assert "não encontrado" in manager.stop("preview-9999")

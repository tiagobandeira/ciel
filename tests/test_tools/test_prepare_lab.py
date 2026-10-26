"""Testes do prepare_lab."""

import tools.prepare_lab as prepare_lab


def test_arquiva_lab_anterior(tmp_path):
    lab = tmp_path / "estudo"
    lab.mkdir()
    (lab / "antigo.txt").write_text("velho", encoding="utf-8")

    result = prepare_lab.run(str(lab))

    assert "Lab pronto" in result
    assert lab.is_dir()
    assert not (lab / "antigo.txt").exists()
    arquivo = tmp_path / "_arquivo"
    assert arquivo.is_dir()
    assert any(p.name.startswith("estudo_") for p in arquivo.iterdir())

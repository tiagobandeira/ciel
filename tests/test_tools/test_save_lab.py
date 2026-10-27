"""Testes do save_lab."""

import tools.save_lab as save_lab


def test_copia_lab_com_nome(tmp_path):
    lab = tmp_path / "estudo"
    lab.mkdir()
    (lab / "NOTA.md").write_text("nota", encoding="utf-8")
    dest = tmp_path / "estudos"

    result = save_lab.run("meu_estudo", source=str(lab), dest_dir=str(dest))

    assert "Estudo salvo" in result
    assert (dest / "meu_estudo" / "NOTA.md").is_file()


def test_nao_sobrescreve_por_padrao(tmp_path):
    lab = tmp_path / "estudo"
    lab.mkdir()
    (lab / "a.txt").write_text("a", encoding="utf-8")
    dest = tmp_path / "estudos"
    save_lab.run("x", source=str(lab), dest_dir=str(dest))

    result = save_lab.run("x", source=str(lab), dest_dir=str(dest))

    assert "Estudo salvo" in result
    assert len(list(dest.iterdir())) == 2

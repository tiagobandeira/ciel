"""Testes do write_notebook e run_notebook."""

import json

import tools.run_notebook as run_notebook
import tools.write_notebook as write_notebook


def test_cria_notebook_colab_valido(tmp_path):
    path = tmp_path / "lab" / "laboratorio.ipynb"
    result = write_notebook.run(
        str(path),
        [
            {"type": "markdown", "source": "# Experimento"},
            {"type": "code", "source": "print('ok')"},
        ],
    )
    assert "Notebook criado" in result
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["nbformat"] == 4
    assert "colab" in data["metadata"]
    assert data["cells"][1]["outputs"] == []
    assert data["cells"][1]["source"] == "print('ok')"


def test_celula_invalida(tmp_path):
    result = write_notebook.run(
        str(tmp_path / "x.ipynb"),
        [{"type": "sql", "source": "select 1"}],
    )
    assert "tipo inválido" in result


def test_executa_notebook_e_grava_log(tmp_path):
    nb = tmp_path / "laboratorio.ipynb"
    log = tmp_path / "resultados" / "execucao.log"
    write_notebook.run(
        str(nb),
        [{"type": "code", "source": "print('ok')"}],
    )
    result = run_notebook.run(
        str(nb), cwd=str(tmp_path), log_path=str(log),
    )
    assert "exit=0" in result
    assert "ok" in result
    assert log.is_file()
    assert "exit=0" in log.read_text(encoding="utf-8")
    data = json.loads(nb.read_text(encoding="utf-8"))
    code = [c for c in data["cells"] if c["cell_type"] == "code"][0]
    assert code["outputs"]
    assert code["outputs"][0]["output_type"] == "stream"
    assert "ok" in "".join(code["outputs"][0]["text"])


def test_notebook_sem_code(tmp_path):
    nb = tmp_path / "vazio.ipynb"
    write_notebook.run(
        str(nb),
        [{"type": "markdown", "source": "# só texto"}],
    )
    result = run_notebook.run(str(nb), cwd=str(tmp_path))
    assert "não tem células de código" in result


def test_grava_expressao_e_erro(tmp_path):
    nb = tmp_path / "lab.ipynb"
    write_notebook.run(
        str(nb),
        [
            {"type": "code", "source": "1 + 1"},
            {"type": "code", "source": "raise ValueError('falhou')"},
        ],
    )
    result = run_notebook.run(str(nb), cwd=str(tmp_path))
    assert "exit=1" in result
    data = json.loads(nb.read_text(encoding="utf-8"))
    assert data["cells"][0]["outputs"][0]["output_type"] == "execute_result"
    assert data["cells"][1]["outputs"][0]["output_type"] == "error"


def test_caminho_relativo_grava_no_lugar_certo(tmp_path, monkeypatch):
    nb = tmp_path / "lab.ipynb"
    write_notebook.run(str(nb), [{"type": "code", "source": "print('ok')"}])
    monkeypatch.chdir(tmp_path)
    result = run_notebook.run("lab.ipynb", cwd=".")
    assert "exit=0" in result
    data = json.loads(nb.read_text(encoding="utf-8"))
    assert data["cells"][0]["outputs"]
    assert not (tmp_path / "lab" / "lab.ipynb").exists()

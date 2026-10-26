"""Testa o runner genérico copiado para corrigir_bug."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "templates/corrigir_bug/verificar.py"


def test_runner_executa_comando_do_alvo(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "ok.py").write_text("print('ok')", encoding="utf-8")
    output = tmp_path / "saida"
    output.mkdir()
    shutil.copy2(TEMPLATE, output / "verificar.py")
    (output / "ALVO.json").write_text(json.dumps({
        "projeto": str(target),
        "comando": [sys.executable, "ok.py"],
        "cwd": str(target),
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(output / "verificar.py")],
        capture_output=True, text=True, cwd=output,
    )

    assert result.returncode == 0
    assert "ok" in result.stdout

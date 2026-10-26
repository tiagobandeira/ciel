"""Executa um notebook célula a célula e grava outputs no próprio .ipynb."""

PERMISSIONS = {"path": "read"}

import ast
import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

MAX_OUTPUT = 20000


def _source(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(part) for part in value)
    return str(value or "")


def _clean_cell(source: str) -> str:
    """Remove magics de IPython que não rodam em Python puro."""
    lines = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("%", "!")) or stripped.startswith("get_ipython("):
            lines.append("# [ciel] linha IPython ignorada: " + stripped)
            continue
        lines.append(line)
    return "\n".join(lines)


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True) if text else []


def _display(*objects, **kwargs):
    """Fallback de display() do IPython para execução local."""
    for obj in objects:
        try:
            if hasattr(obj, "to_string"):
                print(obj.to_string())
            else:
                print(obj)
        except Exception:
            print(repr(obj))



def _run_cells(
    data: dict, notebook_path: Path, workdir: Path, timeout: int = 300,
) -> tuple[int, list[str]]:
    """Executa células no mesmo namespace e preenche outputs nbformat."""
    old_cwd = Path.cwd()
    started = time.monotonic()
    os.environ.setdefault("MPLBACKEND", "Agg")
    code = [
        cell for cell in data.get("cells", [])
        if cell.get("cell_type") == "code"
    ]
    namespace = {
        "__name__": "__main__",
        "__file__": str(notebook_path),
        "display": _display,
    }
    sys.path.insert(0, str(workdir))
    log: list[str] = []
    errors = 0
    counter = 0
    try:
        os.chdir(workdir)
        try:
            import matplotlib.pyplot as plt  # noqa: F401
        except Exception:
            plt = None

        for index, cell in enumerate(data.get("cells", []), start=1):
            if cell.get("cell_type") != "code":
                continue
            counter += 1
            source = _clean_cell(_source(cell.get("source", "")))
            cell["execution_count"] = counter
            cell["outputs"] = []
            if not source.strip():
                continue
            if time.monotonic() - started > timeout:
                errors += 1
                cell["outputs"] = [{
                    "output_type": "error",
                    "ename": "TimeoutError",
                    "evalue": f"notebook excedeu {timeout}s",
                    "traceback": [f"TimeoutError: notebook excedeu {timeout}s"],
                }]
                break

            before = set(plt.get_fignums()) if plt is not None else set()
            out_buf, err_buf = io.StringIO(), io.StringIO()
            result_value = None
            try:
                tree = ast.parse(source)
                with contextlib.redirect_stdout(out_buf), \
                        contextlib.redirect_stderr(err_buf):
                    if tree.body and isinstance(tree.body[-1], ast.Expr):
                        body = ast.Module(
                            body=tree.body[:-1], type_ignores=[],
                        )
                        exec(compile(body, f"<cell {index}>", "exec"), namespace)
                        expr = ast.Expression(tree.body[-1].value)
                        result_value = eval(
                            compile(expr, f"<cell {index}>", "eval"), namespace
                        )
                    else:
                        exec(
                            compile(tree, f"<cell {index}>", "exec"),
                            namespace,
                        )
            except Exception:
                errors += 1
                cell["outputs"].append({
                    "output_type": "error",
                    "ename": type(sys.exc_info()[1]).__name__,
                    "evalue": str(sys.exc_info()[1]),
                    "traceback": traceback.format_exc().splitlines(),
                })

            stdout, stderr = out_buf.getvalue(), err_buf.getvalue()
            if stdout:
                cell["outputs"].append({
                    "output_type": "stream", "name": "stdout",
                    "text": _lines(stdout),
                })
            if stderr:
                cell["outputs"].append({
                    "output_type": "stream", "name": "stderr",
                    "text": _lines(stderr),
                })
            if result_value is not None and not isinstance(result_value, type(None)):
                text = repr(result_value)
                if len(text) > MAX_OUTPUT:
                    text = text[:MAX_OUTPUT] + "\n[... truncado]"
                cell["outputs"].append({
                    "output_type": "execute_result",
                    "execution_count": counter,
                    "data": {"text/plain": _lines(text)},
                    "metadata": {},
                })

            if plt is not None:
                for num in set(plt.get_fignums()) - before:
                    fig = plt.figure(num)
                    buf = io.BytesIO()
                    try:
                        fig.savefig(buf, format="png", bbox_inches="tight")
                        payload = base64.b64encode(buf.getvalue()).decode("ascii")
                        cell["outputs"].append({
                            "output_type": "display_data",
                            "data": {"image/png": payload},
                            "metadata": {},
                        })
                        figdir = workdir / "figuras"
                        figdir.mkdir(parents=True, exist_ok=True)
                        fig.savefig(figdir / f"cell_{index}_fig_{num}.png")
                    except Exception:
                        pass
                    finally:
                        plt.close(fig)

            log.append(f"\n--- cell {index} ---")
            log.append(stdout)
            if stderr:
                log.append("[stderr]\n" + stderr)
            if errors and cell["outputs"] and cell["outputs"][0].get("output_type") == "error":
                log.append("[erro]\n" + cell["outputs"][0]["traceback"][-1])

        notebook_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    finally:
        os.chdir(old_cwd)
        try:
            sys.path.remove(str(workdir))
        except ValueError:
            pass
    return (0 if errors == 0 else 1), log


def _run_linear(data: dict, notebook_path: Path, workdir: Path, timeout: int) -> str:
    code = [
        _clean_cell(_source(cell.get("source", "")))
        for cell in data.get("cells", [])
        if cell.get("cell_type") == "code"
    ]
    script = "\n\n".join(code)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".py", prefix=".ciel_notebook_",
        dir=workdir, encoding="utf-8", delete=False,
    )
    try:
        handle.write(script)
        handle.close()
        proc = subprocess.run(
            [sys.executable, handle.name],
            cwd=str(workdir), capture_output=True, text=True,
            timeout=timeout,
        )
        return (
            f"Notebook executado: {notebook_path} (exit={proc.returncode})\n"
            f"cwd: {workdir}\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


def run(
    path: str,
    cwd: str = "",
    timeout: int = 300,
    log_path: str = "",
    salvar_saidas: bool = True,
) -> str:
    """
    path: .ipynb
    cwd: pasta de execução (padrão: pasta do notebook)
    timeout: usado no modo linear (salvar_saidas=False)
    log_path: se informado, grava stdout/stderr nesse arquivo
    salvar_saidas: executa célula a célula e grava outputs no notebook
    """
    notebook_path = Path(path).resolve()
    if not notebook_path.is_file():
        return f"Erro: notebook '{path}' não encontrado."
    try:
        data = json.loads(notebook_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Erro ao ler notebook: {exc}"

    if not any(c.get("cell_type") == "code" for c in data.get("cells", [])):
        return "Erro: notebook não tem células de código."

    workdir = (Path(cwd) if cwd else notebook_path.parent).resolve()
    if not workdir.is_dir():
        return f"Erro: cwd '{workdir}' não é uma pasta."

    if salvar_saidas:
        try:
            timeout = max(1, min(int(timeout), 900))
        except (TypeError, ValueError):
            timeout = 300
        status_code, log = _run_cells(
            data, notebook_path, workdir, timeout=timeout,
        )
        output = (
            f"Notebook executado: {path} (exit={status_code})\n"
            f"cwd: {workdir}\n"
            "--- execução por célula ---\n"
            + "\n".join(log)
        )
        if log_path:
            try:
                log_file = Path(log_path)
                log_file.parent.mkdir(parents=True, exist_ok=True)
                log_file.write_text(output, encoding="utf-8")
            except Exception as exc:
                output += f"\n[aviso] não gravei o log: {exc}"
        return output[:MAX_OUTPUT]

    try:
        timeout = max(1, min(int(timeout), 300))
    except (TypeError, ValueError):
        timeout = 120
    output = _run_linear(data, notebook_path, workdir, timeout)
    if log_path:
        try:
            log_file = Path(log_path)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(output, encoding="utf-8")
        except Exception as exc:
            output += f"\n[aviso] não gravei o log: {exc}"
    return output[:MAX_OUTPUT]

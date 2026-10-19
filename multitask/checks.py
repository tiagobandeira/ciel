"""
multitask/checks.py — verificação por código antes do julgamento do modelo.

A ideia do roadmap: o que dá para provar com código não deve ser aprovado
pelo próprio modelo que executou a task. Este módulo roda as checagens
declaradas no fluxo e devolve um `CheckResult` normalizado.

Tipos aceitos (campo `tipo`):

    arquivo   {"tipo":"arquivo","path":"index.html","existe":true,
               "contem":"<html","nao_contem":"TODO","tamanho_min":10}
    comando   {"tipo":"comando","cmd":["python","-m","pytest","-q"],
               "cwd":".","esperado":0,"timeout":60}
    http      {"tipo":"http","url":"http://127.0.0.1:8000/",
               "esperado":200,"metodo":"GET","corpo_contem":"ok"}
    json      {"tipo":"json","path":"dados.json","chaves":["itens"]}

Uma lista de checagens roda em ordem e para na primeira falha. Uma string
(`checagem: manual`) é registrada como "não verificada" — serve de critério
para o modelo, não de verificação automática.

Segurança: paths e `cwd` são resolvidos dentro do workspace; nada fora dele
é lido/executado por uma checagem. `comando` executa código local — um fluxo
externo deve ser confirmado pelo harness antes de rodar (a CLI faz isso).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_CMD_TIMEOUT = 30
MAX_CMD_TIMEOUT = 300
DEFAULT_HTTP_TIMEOUT = 10
MAX_HTTP_TIMEOUT = 60
MAX_OUTPUT_CHARS = 4000
MAX_FILE_CHARS = 200_000

_FILE_TYPES = {"arquivo", "file", "file_exists", "existe"}
_CMD_TYPES = {"comando", "cmd", "command", "shell", "exit", "exec"}
_HTTP_TYPES = {"http", "url", "http_status", "status_http"}
_JSON_TYPES = {"json", "json_valido", "json_schema"}
_MANUAL_TYPES = {"manual", "texto", "text"}


# ── resultado ─────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    ok: bool
    tipo: str = "none"
    mensagem: str = ""
    verificado: bool = True
    detalhes: dict = field(default_factory=dict)
    duracao_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tipo": self.tipo,
            "mensagem": self.mensagem,
            "verificado": self.verificado,
            "detalhes": self.detalhes,
            "duracao_s": round(self.duracao_s, 3),
        }


def _fail(tipo: str, mensagem: str, **detalhes) -> CheckResult:
    return CheckResult(
        ok=False, tipo=tipo, mensagem=mensagem,
        verificado=True, detalhes=detalhes,
    )


def _ok(tipo: str, mensagem: str, **detalhes) -> CheckResult:
    return CheckResult(
        ok=True, tipo=tipo, mensagem=mensagem,
        verificado=True, detalhes=detalhes,
    )


# ── helpers ───────────────────────────────────────────────────────────────

def _short(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncado — {len(text):,} chars]"


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:300]
    return ""


def _resolve_inside(root: Path, raw: str) -> tuple[Path | None, str | None]:
    """Resolve `raw` e garante que fica dentro de `root`."""
    raw = str(raw or "").strip()
    if not raw:
        return None, "path ausente"

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        return None, f"path inválido: {exc}"

    if resolved != root and root not in resolved.parents:
        return None, f"path fora do workspace: {raw}"
    return resolved, None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _expected_int(value, default: int = 0):
    if isinstance(value, list):
        result = []
        for item in value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                pass
        return result or [default]
    try:
        return [int(value)]
    except (TypeError, ValueError):
        return [default]


def _expected_label(expected: list[int]) -> str:
    if len(expected) == 1:
        return str(expected[0])
    return ", ".join(str(item) for item in expected)


# ── checagens individuais ─────────────────────────────────────────────────

def _check_arquivo(checagem: dict, root: Path) -> CheckResult:
    raw_path = (
        checagem.get("path")
        or checagem.get("caminho")
        or checagem.get("arquivo")
    )
    path, error = _resolve_inside(root, raw_path)
    if error:
        return _fail("arquivo", error)

    expect_exists = bool(checagem.get("existe", True))
    exists = path.exists()

    if expect_exists and not exists:
        return _fail(
            "arquivo", f"arquivo não existe: {_relative(path, root)}",
            path=_relative(path, root),
        )
    if not expect_exists and exists:
        return _fail(
            "arquivo", f"arquivo deveria não existir: {_relative(path, root)}",
            path=_relative(path, root),
        )
    if not exists:
        return _ok(
            "arquivo", f"arquivo ausente (esperado): {_relative(path, root)}",
            path=_relative(path, root),
        )

    if path.is_dir():
        return _fail(
            "arquivo", f"esperado arquivo, encontrado diretório: {_relative(path, root)}",
            path=_relative(path, root),
        )

    try:
        size = path.stat().st_size
    except OSError as exc:
        return _fail("arquivo", f"erro ao inspecionar: {exc}")

    min_size = checagem.get("tamanho_min")
    if min_size is not None:
        try:
            if size < int(min_size):
                return _fail(
                    "arquivo",
                    f"{_relative(path, root)} tem {size} bytes, "
                    f"mínimo {min_size}",
                    path=_relative(path, root), size=size,
                )
        except (TypeError, ValueError):
            pass

    contains = checagem.get("contem")
    not_contains = checagem.get("nao_contem")
    if contains or not_contains:
        try:
            content = path.read_text(
                encoding="utf-8", errors="replace"
            )[:MAX_FILE_CHARS]
        except OSError as exc:
            return _fail("arquivo", f"erro ao ler {_relative(path, root)}: {exc}")

        wanted = contains if isinstance(contains, list) else [contains] if contains else []
        forbidden = (
            not_contains if isinstance(not_contains, list)
            else [not_contains] if not_contains else []
        )
        for needle in wanted:
            if str(needle) not in content:
                return _fail(
                    "arquivo",
                    f"{_relative(path, root)} não contém {needle!r}",
                    path=_relative(path, root),
                )
        for needle in forbidden:
            if str(needle) in content:
                return _fail(
                    "arquivo",
                    f"{_relative(path, root)} contém {needle!r} (proibido)",
                    path=_relative(path, root),
                )

    return _ok(
        "arquivo", f"arquivo existe: {_relative(path, root)}",
        path=_relative(path, root), size=size,
    )


def _check_comando(checagem: dict, root: Path) -> CheckResult:
    raw_cmd = (
        checagem.get("cmd")
        or checagem.get("comando")
        or checagem.get("command")
    )
    if not raw_cmd:
        return _fail("comando", "campo 'cmd' ausente")

    raw_cwd = checagem.get("cwd") or "."
    cwd, error = _resolve_inside(root, raw_cwd)
    if error:
        return _fail("comando", error)
    if not cwd.is_dir():
        return _fail("comando", f"cwd não é diretório: {_relative(cwd, root)}")

    try:
        timeout = int(checagem.get("timeout", DEFAULT_CMD_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_CMD_TIMEOUT
    timeout = max(1, min(timeout, MAX_CMD_TIMEOUT))

    expected = _expected_int(checagem.get("esperado", 0))
    expected_label = _expected_label(expected)
    shell = bool(checagem.get("shell", isinstance(raw_cmd, str)))

    if isinstance(raw_cmd, str):
        if shell:
            cmd: Any = raw_cmd
        else:
            try:
                cmd = shlex.split(raw_cmd, posix=(os.name != "nt"))
            except ValueError as exc:
                return _fail("comando", f"cmd inválido: {exc}")
    elif isinstance(raw_cmd, list):
        cmd = [str(part) for part in raw_cmd]
        shell = False
    else:
        return _fail("comando", "cmd deve ser string ou lista")

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        duration = time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        return CheckResult(
            ok=False, tipo="comando",
            mensagem=f"comando excedeu {timeout}s",
            detalhes={"cmd": raw_cmd, "timeout": timeout},
            duracao_s=time.monotonic() - started,
        )
    except OSError as exc:
        return _fail("comando", f"falha ao executar: {exc}", cmd=raw_cmd)

    exit_code = proc.returncode
    ok = exit_code in expected
    output = _short((proc.stdout or "") + (proc.stderr or ""))
    detail = _first_line(proc.stderr or proc.stdout or "")

    if ok:
        message = f"comando retornou {exit_code}"
    else:
        message = (
            f"comando retornou {exit_code} (esperado {expected_label})"
        )
        if detail:
            message += f": {detail}"

    return CheckResult(
        ok=ok,
        tipo="comando",
        mensagem=message,
        verificado=True,
        detalhes={
            "cmd": raw_cmd,
            "cwd": _relative(cwd, root),
            "exit_code": exit_code,
            "esperado": expected,
            "stdout": _short(proc.stdout or ""),
            "stderr": _short(proc.stderr or ""),
            "output": output,
        },
        duracao_s=duration,
    )


def _check_http(checagem: dict, root: Path) -> CheckResult:
    url = str(checagem.get("url") or "").strip()
    if not url:
        return _fail("http", "campo 'url' ausente")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return _fail("http", f"url inválida: {url}")

    method = str(
        checagem.get("metodo") or checagem.get("method") or "GET"
    ).upper()
    expected = _expected_int(checagem.get("esperado", 200))
    expected_label = _expected_label(expected)

    try:
        timeout = float(checagem.get("timeout", DEFAULT_HTTP_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_HTTP_TIMEOUT
    timeout = max(1.0, min(timeout, MAX_HTTP_TIMEOUT))

    started = time.monotonic()
    try:
        response = requests.request(
            method, url, timeout=timeout, allow_redirects=True
        )
    except requests.RequestException as exc:
        return CheckResult(
            ok=False, tipo="http",
            mensagem=f"falha na requisição: {exc}",
            detalhes={"url": url, "metodo": method},
            duracao_s=time.monotonic() - started,
        )

    duration = time.monotonic() - started
    status = response.status_code
    ok = status in expected

    contains = checagem.get("corpo_contem")
    if ok and contains:
        body = response.text or ""
        if str(contains) not in body:
            ok = False

    message = f"HTTP {status} (esperado {expected_label})"
    if not ok and contains and status in expected:
        message += f" — corpo não contém {contains!r}"

    return CheckResult(
        ok=ok,
        tipo="http",
        mensagem=message,
        verificado=True,
        detalhes={
            "url": url,
            "metodo": method,
            "status": status,
            "esperado": expected,
            "corpo": _short(response.text or "", 1000),
            "corpo_contem": contains,
        },
        duracao_s=duration,
    )


def _check_json(checagem: dict, root: Path) -> CheckResult:
    raw_path = checagem.get("path") or checagem.get("caminho")
    path, error = _resolve_inside(root, raw_path)
    if error:
        return _fail("json", error)
    if not path.exists():
        return _fail("json", f"arquivo não existe: {_relative(path, root)}")
    if path.is_dir():
        return _fail("json", f"esperado arquivo, encontrado diretório: {_relative(path, root)}")

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(content)
    except (OSError, ValueError) as exc:
        return _fail(
            "json", f"JSON inválido em {_relative(path, root)}: {exc}",
            path=_relative(path, root),
        )

    required = checagem.get("chaves") or checagem.get("keys") or []
    if isinstance(required, str):
        required = [required]
    missing = [
        key for key in required
        if not isinstance(data, dict) or key not in data
    ]
    if missing:
        return _fail(
            "json",
            f"{_relative(path, root)} sem as chaves: {', '.join(map(str, missing))}",
            path=_relative(path, root), missing=missing,
        )

    keys = sorted(data.keys()) if isinstance(data, dict) else []
    return _ok(
        "json", f"JSON válido: {_relative(path, root)}",
        path=_relative(path, root), chaves=keys,
    )


# ── API ───────────────────────────────────────────────────────────────────

def run_check(
    checagem: dict,
    *,
    workspace_root: str | Path,
) -> CheckResult:
    """Executa uma checagem (dict) e devolve o resultado normalizado."""
    root = Path(workspace_root).resolve()
    if not isinstance(checagem, dict):
        return _fail("desconhecido", "checagem deve ser um objeto JSON")

    tipo = str(
        checagem.get("tipo") or checagem.get("type") or ""
    ).strip().lower()

    if tipo in _MANUAL_TYPES:
        return CheckResult(
            ok=True, tipo="manual",
            mensagem=str(checagem.get("descricao") or "checagem manual"),
            verificado=False,
        )

    started = time.monotonic()
    try:
        if tipo in _FILE_TYPES:
            result = _check_arquivo(checagem, root)
        elif tipo in _CMD_TYPES:
            result = _check_comando(checagem, root)
        elif tipo in _HTTP_TYPES:
            result = _check_http(checagem, root)
        elif tipo in _JSON_TYPES:
            result = _check_json(checagem, root)
        else:
            result = _fail(
                tipo or "desconhecido",
                f"tipo de checagem desconhecido: {tipo!r}",
            )
    except Exception as exc:  # nunca derruba a execução por uma checagem
        result = _fail(tipo or "desconhecido", f"erro na checagem: {exc}")

    if result.duracao_s <= 0:
        result.duracao_s = time.monotonic() - started
    return result


def run_checks(
    checagem: Any,
    *,
    workspace_root: str | Path,
) -> CheckResult:
    """
    Roda a checagem declarada (None, string, dict ou lista).

    Lista = todas precisam passar; para na primeira falha. `None`/string
    significam "sem verificação automática" (`verificado=False`).
    """
    if checagem is None:
        return CheckResult(
            ok=True, tipo="none",
            mensagem="sem checagem automática",
            verificado=False,
        )

    if isinstance(checagem, str):
        return CheckResult(
            ok=True, tipo="manual",
            mensagem=checagem,
            verificado=False,
        )

    if isinstance(checagem, dict):
        return run_check(checagem, workspace_root=workspace_root)

    if isinstance(checagem, list):
        if not checagem:
            return CheckResult(
                ok=True, tipo="none",
                mensagem="sem checagem automática",
                verificado=False,
            )

        executed: list[dict] = []
        total_time = 0.0
        for item in checagem:
            result = run_checks(item, workspace_root=workspace_root)
            executed.append(result.to_dict())
            total_time += result.duracao_s
            if not result.ok:
                return CheckResult(
                    ok=False,
                    tipo=f"lista:{result.tipo}",
                    mensagem=result.mensagem,
                    verificado=result.verificado,
                    detalhes={"checks": executed, **result.detalhes},
                    duracao_s=total_time,
                )

        return CheckResult(
            ok=True, tipo="lista",
            mensagem=f"{len(executed)} checagem(ns) passaram",
            verificado=any(item.get("verificado") for item in executed),
            detalhes={"checks": executed},
            duracao_s=total_time,
        )

    return _fail("desconhecido", f"formato de checagem inválido: {type(checagem).__name__}")


def build_correction_context(
    check: CheckResult,
    *,
    task=None,
    workspace_root: str | Path,
    max_chars: int = 6000,
) -> str:
    """
    Contexto enxuto para a task de correção: o erro da checagem + os
    arquivos envolvidos (conteúdo curto), nunca o histórico bruto.
    """
    root = Path(workspace_root).resolve()
    lines = [
        "## Correção automática",
        "A checagem automática desta task falhou.",
        f"Tipo: {check.tipo}",
        f"Erro: {check.mensagem}",
    ]

    details = check.detalhes or {}
    stdout = _short(str(details.get("stdout") or ""), 1500).strip()
    stderr = _short(str(details.get("stderr") or ""), 1500).strip()
    if stdout:
        lines += ["", "### stdout", "```", stdout, "```"]
    if stderr:
        lines += ["", "### stderr", "```", stderr, "```"]

    paths: list[str] = []
    if details.get("path"):
        paths.append(str(details["path"]))
    for item in details.get("checks") or []:
        path = (item.get("detalhes") or {}).get("path")
        if path:
            paths.append(str(path))

    if task is not None:
        for artifact in getattr(task, "artefatos", []) or []:
            path = artifact.get("path") if isinstance(artifact, dict) else artifact
            if path:
                paths.append(str(path))

    seen: set[str] = set()
    for raw in paths:
        if raw in seen:
            continue
        seen.add(raw)
        path, error = _resolve_inside(root, raw)
        if error or path is None or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in content[:200]:
            continue
        lines += [
            "",
            f"### arquivo: {_relative(path, root)}",
            "```",
            content[:2500],
            "```",
        ]

    lines += [
        "",
        "## Instruções",
        "- Corrija SOMENTE o problema apontado pela checagem.",
        "- Use as tools para inspecionar e alterar os arquivos reais.",
        "- Não refaça o que já está correto.",
        "- Ao terminar, responda com done e diga o que mudou.",
    ]

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


__all__ = [
    "DEFAULT_CMD_TIMEOUT",
    "MAX_CMD_TIMEOUT",
    "CheckResult",
    "run_check",
    "run_checks",
    "build_correction_context",
]

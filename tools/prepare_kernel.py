"""Prepara um kernel de projeto: template + manifesto + smoke test."""

PERMISSIONS = {"dest": "write"}

import json
from pathlib import Path

import yaml

from tools.copy_template import run as copy_template

KERNELS_DIR = Path(__file__).resolve().parent.parent / "kernels"


def _load_kernel(name: str) -> tuple[dict, Path]:
    safe = (name or "").strip().replace("\\", "/").split("/")[-1]
    if not safe or safe in (".", ".."):
        raise ValueError(f"kernel inválido: {name!r}")
    base = KERNELS_DIR / safe
    manifest = base / "kernel.yaml"
    if not manifest.exists():
        disponiveis = sorted(p.name for p in KERNELS_DIR.iterdir() if p.is_dir()) if KERNELS_DIR.exists() else []
        raise ValueError(
            f"kernel '{safe}' não encontrado. Disponíveis: "
            + (", ".join(disponiveis) or "(nenhum)")
        )
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"manifesto inválido: {manifest}")
    return data, base


def _substituir_variables(dest: Path, variables: dict) -> int:
    if not variables:
        return 0
    changed = 0
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        original = text
        for key, value in variables.items():
            text = text.replace("{{" + str(key) + "}}", str(value))
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def run(
    kernel: str,
    dest: str,
    variant: str = "",
    overwrite: bool = False,
    variables: dict | None = None,
) -> str:
    """
    kernel: nome em kernels/ (ex.: web_static)
    dest:   pasta de destino no workspace
    variant: variante do kernel (app, landing, game)
    overwrite: sobrescreve arquivos existentes
    variables: valores para substituir {{chave}} nos arquivos
    """
    try:
        data, base = _load_kernel(kernel)
    except ValueError as exc:
        return f"Erro: {exc}"

    variants = data.get("variants") or {}
    if not isinstance(variants, dict) or not variants:
        return f"Erro: kernel '{kernel}' não define variants."
    selected = (variant or "").strip()
    if not selected:
        selected = next(iter(variants))
    if selected not in variants:
        return (
            f"Erro: variante '{selected}' não existe em '{kernel}'. "
            f"Disponíveis: {', '.join(variants)}."
        )
    cfg = variants[selected] or {}
    if not isinstance(cfg, dict):
        return f"Erro: variante '{selected}' inválida."

    template = str(cfg.get("template") or "").strip()
    if not template:
        return f"Erro: variante '{selected}' sem template."
    result = copy_template(template, dest, overwrite=overwrite)
    if result.startswith("Erro"):
        return result

    target = Path(dest)
    merged_vars = dict(data.get("variables") or {})
    if variables:
        merged_vars.update(variables)
    changed = _substituir_variables(target, merged_vars)

    missing = []
    for item in cfg.get("checks") or []:
        raw = item.get("path") if isinstance(item, dict) else item
        if not raw:
            continue
        if not (target / str(raw)).is_file():
            missing.append(str(raw))
    if missing:
        return (
            f"Kernel '{kernel}' aplicado, mas o smoke falhou: "
            f"faltam {', '.join(missing)}."
        )

    state = {
        "kernel": kernel,
        "version": data.get("version", 0),
        "variant": selected,
        "template": template,
        "variables": merged_vars,
    }
    state_path = target / ".ciel" / "kernel.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return (
        f"Kernel '{kernel}' aplicado em {dest} "
        f"(variante={selected}, template={template}, "
        f"{changed} arquivo(s) com variáveis). Smoke ok."
    )

"""
workspace.py — sandbox de filesystem pras tools que leem/escrevem arquivos
ou executam scripts (read_file, write_file, list_directory,
list_directory_files, run_script).

Duas fontes de escopo:
  1. Workspace padrão: o diretório onde o `ciel` foi iniciado (cwd), sempre
     liberado pra leitura E escrita — "a pasta em que você está
     trabalhando", igual outros agentes de CLI (Claude Code, Aider, etc).
  2. Grants extras: via `/workspace <path>`, o usuário libera outro
     arquivo ou pasta específica, com leitura e/ou escrita concedida
     explicitamente na hora. Fica salvo em `.ciel_workspace.json` na raiz
     do workspace padrão, pra não perguntar de novo toda sessão — mas
     SEMPRE aparece no banner de início, pra deixar claro o que está
     liberado.

Todo path é resolvido com Path.resolve() antes de comparar contra os
limites, pra `..` e symlinks não escaparem do sandbox.

LIMITAÇÃO CONHECIDA: isso restringe o que as TOOLS do Ciel podem acessar
via caminho. Não é um sandbox de SO — um script rodado via run_script que
o modelo escreva pode, em tese, tentar abrir caminhos fora do workspace
por conta própria (ex: os.open direto). O guard aqui cobre o argumento
declarado da tool call, que é o vetor mais comum, mas não substitui
isolamento de processo (container, usuário restrito, etc) pra quem
precisar de garantia mais forte.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = ".ciel_workspace.json"


@dataclass
class Grant:
    root: Path
    read: bool = True
    write: bool = False
    is_file: bool = False  # True se o grant é um arquivo específico, não uma pasta


class Workspace:
    def __init__(self, root: Path):
        self.default_root: Path = root.resolve()
        self.grants: list[Grant] = []
        self._load()

    # ── consulta / exibição ────────────────────────────────────────────

    def status_lines(self) -> list[str]:
        lines = [f"padrão (leitura+escrita): {self.default_root}"]
        for g in self.grants:
            perms = "leitura+escrita" if g.write else "somente leitura"
            tipo = "arquivo" if g.is_file else "pasta"
            lines.append(f"{tipo} ({perms}): {g.root}")
        return lines

    def _find_grant(self, resolved: Path) -> Grant | None:
        try:
            resolved.relative_to(self.default_root)
            return Grant(root=self.default_root, read=True, write=True)
        except ValueError:
            pass
        for g in self.grants:
            if g.is_file:
                if resolved == g.root:
                    return g
            else:
                try:
                    resolved.relative_to(g.root)
                    return g
                except ValueError:
                    continue
        return None

    def check(self, raw_path: str, need_write: bool) -> tuple[Path | None, str | None]:
        """
        Resolve raw_path e confere se está autorizado.
        Retorna (path_resolvido, None) se ok, ou (None, mensagem_de_erro).
        """
        if not raw_path:
            return None, "Path vazio."
        try:
            resolved = Path(raw_path).expanduser().resolve()
        except Exception as e:
            return None, f"Path inválido: {e}"

        grant = self._find_grant(resolved)
        if grant is None:
            return None, (
                f"Acesso negado: '{raw_path}' está fora do workspace atual "
                f"({self.default_root}). Use /workspace {raw_path} pra liberar."
            )
        if need_write and not grant.write:
            return None, (
                f"'{raw_path}' está liberado só pra leitura. "
                f"Use /workspace {grant.root} pra pedir permissão de escrita."
            )
        return resolved, None

    # ── modificação ──────────────────────────────────────────────────

    def add_grant(self, path: Path, write: bool) -> Grant:
        path = path.resolve()
        is_file = path.is_file()
        g = Grant(root=path, read=True, write=write, is_file=is_file)
        self.grants = [x for x in self.grants if x.root != path]
        self.grants.append(g)
        self._save()
        return g

    def remove_grant(self, path: Path) -> bool:
        path = path.resolve()
        before = len(self.grants)
        self.grants = [x for x in self.grants if x.root != path]
        changed = len(self.grants) != before
        if changed:
            self._save()
        return changed

    # ── persistência ─────────────────────────────────────────────────

    def _config_path(self) -> Path:
        return self.default_root / CONFIG_FILENAME

    def _load(self) -> None:
        cfg = self._config_path()
        if not cfg.exists():
            return
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            for item in data.get("grants", []):
                p = Path(item["root"])
                if not p.exists():
                    continue  # pasta/arquivo sumiu — não recria grant morto
                self.grants.append(Grant(
                    root=p.resolve(),
                    read=item.get("read", True),
                    write=item.get("write", False),
                    is_file=item.get("is_file", False),
                ))
        except Exception:
            pass  # config corrompida — segue só com o workspace padrão

    def _save(self) -> None:
        data = {
            "grants": [
                {"root": str(g.root), "read": g.read, "write": g.write, "is_file": g.is_file}
                for g in self.grants
            ]
        }
        try:
            self._config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass  # não trava a sessão por causa de erro de disco aqui


# instância única do processo
_workspace: Workspace | None = None


def init_workspace(root: Path | None = None) -> Workspace:
    global _workspace
    _workspace = Workspace(root or Path.cwd())
    return _workspace


def get_workspace() -> Workspace:
    if _workspace is None:
        init_workspace()
    return _workspace

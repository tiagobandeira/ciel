"""Recria o demo de bugfix em data/user/bugfix_demo (estado com falha).

Uso:
    python examples/reset_bugfix_demo.py

O demo é intencionalmente ignorado pelo git (data/), então este script é a
fonte reproduzível para rodar o processo `corrigir_bug`.
"""

from pathlib import Path

DEMO = Path("data/user/bugfix_demo")

CALC = '''"""Funções matemáticas simples do demo de bugfix."""


def media(nums):
    """Retorna a média aritmética da lista."""
    return sum(nums) / len(nums)


def soma(nums):
    """Retorna a soma da lista."""
    return sum(nums)
'''

TEST = '''from calc import media, soma


def test_media_lista_normal():
    assert media([2, 4, 6]) == 4


def test_media_lista_vazia():
    # Regra do domínio: média de lista vazia é 0.
    assert media([]) == 0


def test_soma():
    assert soma([1, 2, 3]) == 6
'''

README = """# Demo de bugfix

`calc.media([])` deve retornar `0` (regra do domínio), mas hoje levanta
`ZeroDivisionError`. O teste `test_media_lista_vazia` reproduz a falha.

Para rodar:

```powershell
cd data/user/bugfix_demo
python -m pytest -q
```

Para restaurar o estado bugado depois de um teste:

```powershell
python examples/reset_bugfix_demo.py
```
"""


def main() -> None:
    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / "calc.py").write_text(CALC, encoding="utf-8")
    (DEMO / "test_media.py").write_text(TEST, encoding="utf-8")
    (DEMO / "README.md").write_text(README, encoding="utf-8")
    for extra in ("BUG.md", "VERIFICACAO.md"):
        path = DEMO / extra
        if path.exists():
            path.unlink()
    print(f"demo restaurado em {DEMO} (media([]) quebrada)")


if __name__ == "__main__":
    main()

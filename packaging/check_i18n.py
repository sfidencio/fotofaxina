"""Confere se todo texto marcado com _("...") tem tradução em inglês (roda nos testes do build)."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import CATEGORIES, SOURCES  # noqa: E402
from app.i18n import LANGUAGES  # noqa: E402
from app.i18n_en import EN  # noqa: E402


def marked_strings():
    found = {}
    for path in [*ROOT.glob("app/**/*.py"), ROOT / "main.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{path.relative_to(ROOT)}:{node.lineno}")
    for v in [*CATEGORIES.values(), *SOURCES.values(), LANGUAGES["auto"]]:
        found.setdefault(v, "config")
    return found


if __name__ == "__main__":
    strings = marked_strings()
    missing = {s: where for s, where in strings.items() if s not in EN}
    unused = [s for s in EN if s not in strings]
    import string
    bad = [s for s in strings if s in EN and
           {f for _, f, _, _ in string.Formatter().parse(s) if f} != {f for _, f, _, _ in string.Formatter().parse(EN[s]) if f}]
    for s, where in missing.items():
        print(f"SEM TRADUÇÃO  {where}: {s!r}")
    for s in bad:
        print(f"PLACEHOLDER DIFERENTE: {s!r}")
    for s in unused:
        print(f"(não usada) {s!r}")
    print(f"{len(strings)} textos, {len(missing)} sem tradução, {len(bad)} com placeholder diferente")
    sys.exit(1 if missing or bad else 0)

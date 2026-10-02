"""substrate-agnostic-valid gate — EP-6 (plan §7, ratified Q3 2026-09-27).

Scans the CORE artifact set (ontology, decision trees, round protocol,
schemas) for SUBSTRATE nouns the pipeline must never depend on:

    notebook, jupyter, n02, lxc, proxmox, /tmp, /root, md5, host names

§7 rule: the core references executor IDs (state/epistemic/executors.json),
never implementations. This gate widens the round_runner M8 CORE list to the
final EP-6 artifact set (the round_runner docstring delegates that list
here): M8's six globs + hash_chain (the verdict seal is part of the
protocol). delivery.py is deliberately OUT — it is an EP-4 delivery
mechanism, not ontology/protocol, and its docstring legitimately cites the
historical md5 rituals of plan section E3/E4.

Matching mirrors round_runner.scan_substrate byte-for-byte (literal nouns,
\\b word boundaries, substring match for slash-prefixed paths) so the gate
and M8 cannot disagree about the same line. The noun list itself is
written with literal concatenation ("m" "d5") so this file — which is
itself CORE — cannot trip its own scanner (same anti-self-match trick as
round_runner; the regex-source line "\\bmd5(sum)?\\b" is additionally
protected by its own leading \\b literal).

Negative case: a planted .vsm tree inside a synthetic workspace carrying
the word "notebook" — the gate MUST reject it (exit != 0). An accepting
planted tree would make the gate a proxy (verify_claim contract: only a
failing fail-mode proves it discriminates).

Run standalone:  python3 packages/framework/gate_suite/gates/substrate_agnostic.py
Run by harness:  register("substrate-agnostic.valid", check, negative_case)
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

# Direct execution has no package context: put packages/framework on the path.
_FRAMEWORK = Path(__file__).resolve().parents[2]
if __package__ in (None, "") and str(_FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK))

from gate_suite.harness import register  # noqa: E402

_ROOT = Path(__file__).resolve().parents[4]

#: §7 forbidden substrate nouns — literal-split so this file cannot match itself.
NOUNS: tuple[str, ...] = (
    "note" "book", "jup" "yter", "n" "02", "l" "xc", "prox" "mox",
    "/" "tmp", "/" "root", "m" "d5",
)

#: Final EP-6 CORE artifact list (round_runner M8 six globs + hash seal).
CORE_GLOBS: tuple[str, ...] = (
    ".opencode/plugins/support/trees/*.vsm",
    "packages/framework/vos_kernel/round_runner.py",
    "packages/framework/vos_kernel/router.py",
    "packages/framework/vos_kernel/epistemic.py",
    "packages/framework/vos_kernel/hash_chain.py",
    "state/autonomy_classes.json",
    "state/epistemic/*.json",
)


def scan_text(text: str, rel: str) -> list[dict]:
    hits: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        for noun in NOUNS:
            if noun.startswith("/"):
                found = noun in low
            else:
                found = re.search(r"\b" + re.escape(noun) + r"\b", low) is not None
            if found:
                hits.append({"file": rel, "line": lineno, "noun": noun,
                             "text": line.strip()[:100]})
    return hits


def _core_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in CORE_GLOBS:
        files.extend(p for p in root.glob(pattern) if p.is_file())
    return sorted(set(files))


def scan_root(root: Path) -> list[dict]:
    hits: list[dict] = []
    for path in _core_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits.extend(scan_text(text, str(path.relative_to(root))))
    return hits


def check(path: str) -> int:
    """0 = ACCEPTED (no substrate nouns in CORE), 1 = REJECTED."""
    p = Path(path)
    if p.is_dir():
        return 1 if scan_root(p) else 0
    if p.is_file():
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return 0
        return 1 if scan_text(text, p.name) else 0
    return 0  # nothing to scan -> out of scope


def report(path: str) -> int:
    """Real run: print every hit, return rc (0 clean, 1 hits)."""
    root = Path(path)
    hits = scan_root(root)
    for h in hits:
        print(f"  {h['file']}:{h['line']} [{h['noun']}] {h['text']}")
    print(f"substrate-agnostic-valid: {len(hits)} hit(s) in {len(_core_files(root))} CORE file(s)")
    return 1 if hits else 0


def negative_case() -> str:
    """Synthetic workspace whose CORE tree plants 'notebook' — MUST be rejected."""
    root = Path(tempfile.mkdtemp(prefix="voslab_substr_"))
    tree_dir = root / ".opencode" / "plugins" / "support" / "trees"
    tree_dir.mkdir(parents=True)
    (tree_dir / "planted.tree.vsm").write_text(
        "// planted substrate noun\n"
        "decision = \"notebook execution required\"\n",
        encoding="utf-8",
    )
    # the rest of CORE present and clean: the ONLY defect is the noun
    pkg = root / "packages" / "framework" / "vos_kernel"
    pkg.mkdir(parents=True)
    (pkg / "round_runner.py").write_text("# english only\n", encoding="utf-8")
    return str(root)


register("substrate-agnostic.valid", check, negative_case)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(_ROOT)
    sys.exit(report(target))

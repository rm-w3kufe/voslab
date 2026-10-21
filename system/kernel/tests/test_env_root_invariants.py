# design: docs/plans/structural_tensions_plan_2026_10_20.vsm (T8: env root invariant)
"""T8 — VOSLAB_PATH setdefault sites must resolve to the repo root.

Structural-tensions plan (2026-10-20) T8: a module-level
`os.environ.setdefault("VOSLAB_PATH", <expr>)` that statically resolves
anywhere but the repository root poisons the whole pytest/session env
(root/TASKS.vsm not found -> bridge live=0 + tasks-reconcile red — the
poisoning incident documented in test_audit_pipeline.py).

Detector, not importer: pure AST over the repo (no module executes, no
side effects, deterministic R10). Fail-loud (R9): an expression pattern
the resolver does not understand FAILS with the site — review it, never
skip silently. Scope = setdefault (first-write-wins, session-wide);
test-scoped direct `environ[...] = ` assignments (fixtures, ep6 env
swap-and-restore) are a different class, out of scope here.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCAN_DIRS = ("packages", "system", "scripts", ".opencode")

# Exact inventory (review, never auto-extend): a NEW setdefault site must be
# reviewed and added here; a DISAPPEARED site must be reviewed and removed.
# Both directions fail -> the inventory cannot drift silently (R9).
EXPECTED_SITES = {
    "system/kernel/vosi.py",
    "system/kernel/tests/test_audit_pipeline.py",
    "system/kernel/measure_latency.py",
}

MAX_HOPS = 8  # module-level name indirection guard (loops -> unresolvable)


def _collect_module_assignments(tree: ast.AST) -> dict[str, ast.AST]:
    """Module-level (top-of-file) assignments only — the ROOT/voslab idiom."""
    out: dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                out[node.target.id] = node.value
    return out


def _at(module_path: Path, idx: int) -> Path:
    """Position model: the file itself is idx=-1; .parent steps +1;
    .parents[N] lands on N (from the file) or idx+1+N (from a directory)."""
    if idx < -1:
        return Path("__negative_idx__")
    try:
        return module_path.resolve() if idx == -1 else module_path.resolve().parents[idx]
    except IndexError:
        return Path("__too_deep__")  # relative -> never equals REPO (violation)


def _resolve(
    node: ast.AST,
    module_path: Path,
    assigns: dict[str, ast.AST],
    hops: int = 0,
    idx: int = -1,
) -> Path | None:
    """Resolve a setdefault value expression to an absolute path.

    Known patterns: str()/Path() wrappers, Path(__file__).resolve() with
    .parent* / .parents[N] chains, module-level name indirection, absolute
    string literals. Anything else -> None (unresolvable = violation).
    """
    if hops > MAX_HOPS:
        return None
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            # x.resolve() / x.absolute() — position unchanged
            if node.func.attr in ("resolve", "absolute", "as_posix"):
                return _resolve(node.func.value, module_path, assigns, hops + 1, idx)
            return None
        fname = node.func.id
        if fname in ("str", "Path", "PurePath") and node.args:
            return _resolve(node.args[0], module_path, assigns, hops + 1, idx)
        # Path(__file__)
        if (
            fname == "Path"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "__file__"
        ):
            return _at(module_path, idx)
        return None
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":  # one step down from current position
            return _resolve(node.value, module_path, assigns, hops + 1, idx + 1)
        if node.attr == "__file__":
            return _at(module_path, idx)
        return None
    if isinstance(node, ast.Subscript):
        # .parents[N]
        if (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
        ):
            n = node.slice.value
            new_idx = n if idx == -1 else idx + 1 + n
            return _resolve(node.value.value, module_path, assigns, hops + 1, new_idx)
        return None
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return _at(module_path, idx)
        if node.id in assigns:
            # Name indirection resolves the TARGET's own chain from the file.
            return _resolve(assigns[node.id], module_path, assigns, hops + 1, -1)
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Absolute literal resolves for comparison; relative never equals root.
        return Path(node.value)
    return None


def _find_setdefault_sites() -> list[tuple[Path, ast.Call, ast.AST]]:
    sites: list[tuple[Path, ast.Call, ast.AST]] = []
    py_files: list[Path] = list(REPO.glob("*.py"))
    for d in SCAN_DIRS:
        base = REPO / d
        if base.is_dir():
            py_files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    for f in sorted(set(py_files)):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            # Parse failure of repo code is itself a finding (R9: loud).
            raise AssertionError(f"T8: cannot AST-parse {f.relative_to(REPO)}")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setdefault"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "VOSLAB_PATH"
                and len(node.args) >= 2
            ):
                sites.append((f, node, node.args[1]))
    return sites


def test_inventory_exact():
    """EXPECTED set == observed set — both drift directions fail (R9)."""
    sites = _find_setdefault_sites()
    found = {str(f.relative_to(REPO)) for f, _, _ in sites}
    assert found == EXPECTED_SITES, (
        f"VOSLAB_PATH setdefault inventory drifted: added={sorted(found - EXPECTED_SITES)} "
        f"removed={sorted(EXPECTED_SITES - found)} — review each site, then update "
        "EXPECTED_SITES deliberately in the same commit."
    )


def test_every_site_resolves_to_repo_root():
    """Each setdefault value statically resolves to the repository root."""
    failures: list[str] = []
    for f, call, value_node in _find_setdefault_sites():
        assigns = _collect_module_assignments(
            ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        )
        resolved = _resolve(value_node, f, assigns)
        if resolved is None:
            failures.append(
                f"{f.relative_to(REPO)}:{call.lineno} — unhandled setdefault pattern; "
                "extend _resolve deliberately after review (R9: never skip)"
            )
            continue
        if resolved.resolve() != REPO.resolve():
            failures.append(
                f"{f.relative_to(REPO)}:{call.lineno} — resolves to {resolved}, "
                f"expected {REPO} (poisons VOSLAB_PATH session-wide)"
            )
    assert not failures, "T8 env-root violations:\n" + "\n".join(failures)


def test_detector_catches_wrong_depth_fixture():
    """Negative control: resolver flags a 2-parent root from a tests/ file."""
    src = "import os\nfrom pathlib import Path\n"
    src += 'os.environ.setdefault("VOSLAB_PATH", str(Path(__file__).resolve().parent.parent))\n'
    tree = ast.parse(src)
    call = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "setdefault"
    )
    fake_module = REPO / "system" / "kernel" / "tests" / "fake_module.py"
    resolved = _resolve(call.args[1], fake_module, {})
    assert resolved is not None, "fixture must resolve"
    assert resolved.resolve() != REPO.resolve(), "wrong-depth fixture not detected"


def test_detector_fails_loud_on_unknown_pattern():
    """Negative control: unknown expression -> unresolvable (violation, R9)."""
    tree = ast.parse('os.environ.setdefault("VOSLAB_PATH", str(unknown_factory()))')
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert _resolve(call.args[1], REPO / "x.py", {}) is None

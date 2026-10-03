#!/usr/bin/env python3
"""Tests de vsl_tree_loader (fix errors.txt 2026-10-03).

Regresión: comentarios `//` inline dentro de children de un bloque
socratic se parseaban como nodos string y engine.evaluate lanzaba
`ValueError: Nodo inválido ... Recibido: //` (classify.tree.vsm con
doc-types sin short-circuit: REGISTRY, PLAN, vacío).
"""
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent          # scripts/vsl/tools/
REPO_ROOT = TOOLS_DIR.parent.parent.parent           # vOSlab/
CLASSIFIER_DIR = TOOLS_DIR.parent / "classifier"     # scripts/vsl/classifier/
for _p in (TOOLS_DIR, CLASSIFIER_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from vsl_tree_loader import load_tree_file, strip_vsl_comments  # noqa: E402

CLASSIFY_TREE = REPO_ROOT / ".opencode/plugins/support/trees/classify.tree.vsm"


def _all_string_leaves(node, acc=None):
    if acc is None:
        acc = []
    if isinstance(node, str):
        acc.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            _all_string_leaves(v, acc)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _all_string_leaves(v, acc)
    return acc


class TestStripVslComments:
    def test_strips_full_line_comment(self):
        assert strip_vsl_comments("a\n// comment\nb\n") == "a\n\nb\n"

    def test_strips_trailing_comment_keeps_code(self):
        out = strip_vsl_comments('home: "x" // ruta\n')
        assert out.strip() == 'home: "x"'

    def test_preserves_url_inside_string(self):
        text = '{ note: "see http://example.com//path" }'
        assert strip_vsl_comments(text) == text

    def test_comment_to_eof_without_newline(self):
        assert strip_vsl_comments("x\n// fin") == "x\n"

    def test_escaped_quote_inside_string(self):
        text = '{ s: "a\\"// b" }'
        assert strip_vsl_comments(text) == text


class TestClassifyTreeRegression:
    def test_load_classify_tree_no_comment_nodes(self):
        tree = load_tree_file(CLASSIFY_TREE)
        assert tree is not None, "classify.tree.vsm must load"
        strings = _all_string_leaves(tree)
        # home/labels/predicates son strings legitimos; comentarios jamas
        assert "//" not in strings, "comment node leaked into tree"
        for s in strings:
            assert not s.startswith("//"), f"comment fragment leaked: {s!r}"

    def test_evaluate_all_branches_no_crash(self):
        """Repro errors.txt: doc-types sin short-circuit llegan al nodo //."""
        from socratic_engine import SocraticEngine
        import vsf_predicates

        tree = load_tree_file(CLASSIFY_TREE)
        eng = SocraticEngine()
        vsf_predicates.register_vsf_predicates(eng)
        # los tres doc-types que crasheaban + uno que matchea temprano
        for doc_type in ("REGISTRY", "PLAN", "", "PLAN-REGISTRY"):
            ev = eng.evaluate(tree, {"type": doc_type})
            assert ev.truth.name in ("TRUE", "FALSE", "UNKNOWN")

    def test_stripped_matches_line_filter_oracle(self):
        """El sanitizer = eliminar lineas comment (oraculo independiente)."""
        from socratic_engine.tree import parse_socratic_block

        raw = CLASSIFY_TREE.read_text(encoding="utf-8")
        oracle_lines = [l for l in raw.splitlines()
                        if not l.strip().startswith("//")]
        assert parse_socratic_block(strip_vsl_comments(raw)) == \
            parse_socratic_block("\n".join(oracle_lines))
        # y el archivo realmente contiene comments (el test no es vacio)
        assert any(l.strip().startswith("//") for l in raw.splitlines())


class TestLoadTreeFile:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_tree_file(tmp_path / "nope.vsm") is None

    def test_json_tree(self, tmp_path):
        p = tmp_path / "t.json"
        p.write_text(json.dumps({"op": "AND", "children": [True, True]}))
        tree = load_tree_file(p)
        assert tree == {"op": "AND", "children": [True, True]}

    def test_no_socratic_block_returns_none(self, tmp_path):
        p = tmp_path / "plain.vsm"
        p.write_text("⟦ x | T-v1 | vsm-1.2.1 | t ⟧\n\n@vsm 1.2.1\n")
        assert load_tree_file(p) is None

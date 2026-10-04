#!/usr/bin/env python3
"""
vsf_hooks_predicates.py — VSF hook-specific socratic-engine predicates.

RSI Level 3 auto-generated + manually-curated predicates backing the
proactive document/script/version hooks:
  doc_auto_associate, doc_staging_process, doc_duplicate_detect,
  doc_hierarchy_enforce, doc_snowball_prevent, script_auto_associate,
  script_staging_process, version_bump_enforce, language_change_protocol.

Kept SEPARATE from vsf_predicates.py (classifier predicates) so the
public classifier path (vsf_socratic_engine.register_vsf_predicates)
is untouched. Loaded by eval_tree_vsf.py wrapper so socratic-engine
stays domain-agnostic.

Predicate signature: args resolved by engine.
  "$ctx"          → full context dict
  "$ctx.key"      → ctx.get("key")
  literal string  → passed as-is
Return: bool
"""

from pathlib import Path
import os
import re
from typing import Any, Dict, List, Optional

# Use VOSLAB_ROOT env var, fallback to vOSlab directory
VOSLAB_ROOT = os.environ.get("VOSLAB_ROOT", os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# S5 containment 2026-10-04: workspace root default (VSF_ROOT env still
# wins for upstream/covenant workflows).
VSF_ROOT = os.environ.get("VSF_ROOT") or os.environ.get("VOSLAB_PATH") \
    or str(Path(__file__).resolve().parents[3])
DOCS_DIRS = [
    os.path.join(VOSLAB_ROOT, "docs"),
    os.path.join(VSF_ROOT, "child", "docs"),
    os.path.join(VSF_ROOT, "docs", "spec_revision", "system"),
    os.path.join(VSF_ROOT, "docs"),
]


def _find_docs(pattern: str = None, ext: str = ".vsm") -> List[str]:
    results = []
    for d in DOCS_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith(ext):
                    if pattern is None or pattern.lower() in f.lower():
                        results.append(os.path.join(root, f))
    return results


def _doc_header_name(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline().strip()
        m = re.search(r"⟦\s*([^|\s]+)", first)
        return m.group(1) if m else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# CONTEXT PREDICATES (new: ctx_gt; ctx_equals/ctx_not_has/ctx_has_pattern
# already exist in vsf_predicates.py — aliased here for hook trees)
# ═══════════════════════════════════════════════════════════════════════

def ctx_gt(a: Any, b: Any) -> bool:
    """True if a > b (numeric comparison, tolerant of str)."""
    try:
        return float(a) > float(b)
    except (TypeError, ValueError):
        return str(a) > str(b)


# ═══════════════════════════════════════════════════════════════════════
# DOCUMENT PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def doc_extract_topic(content: str) -> str:
    """Extract topic identifier from document content (header name / first line)."""
    if not content:
        return ""
    m = re.search(r"⟦\s*([^|\s]+)", content)
    if m:
        return m.group(1)
    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("//") and not line.startswith("⟦"):
            return line[:60]
    return ""


def doc_search_existing(topic: str) -> List[str]:
    """Search existing docs for the same topic (header name match)."""
    if not topic:
        return []
    topic_l = topic.lower()
    return [p for p in _find_docs(ext=".vsm") if _doc_header_name(p) and _doc_header_name(p).lower() == topic_l]


def doc_topic_exact_match(found_docs: List[str]) -> bool:
    """True if an exact topic match was found."""
    return bool(found_docs)


def doc_topic_partial_match(scores: Any, threshold: float = 0.70) -> bool:
    """True if any similarity score >= threshold."""
    if isinstance(scores, (list, tuple)):
        return any(isinstance(s, (int, float)) and s >= threshold for s in scores)
    if isinstance(scores, (int, float)):
        return scores >= threshold
    return False


def doc_has_content(content: str) -> bool:
    """True if document has non-trivial content."""
    if not content:
        return False
    meaningful = [l for l in content.split("\n") if l.strip() and not l.strip().startswith("//")]
    return len(meaningful) > 2


def has_duplicates(found_docs: List[str]) -> bool:
    """True if more than one document matches (duplicate)."""
    return len(found_docs) > 1


def is_source(ctx: Dict[str, Any]) -> bool:
    """True if document is a FUENTE (source of truth, no approval needed)."""
    status = ctx.get("doc_status", ctx.get("status", ""))
    path = ctx.get("new_doc_path", ctx.get("file_path", ""))
    return "fuente" in path.lower() or status == "ratified"


def is_reference(ctx: Dict[str, Any]) -> bool:
    """True if document is a REFERENCIA (consult-only)."""
    status = ctx.get("doc_status", ctx.get("status", ""))
    path = ctx.get("new_doc_path", ctx.get("file_path", ""))
    return "referencia" in path.lower() or status == "reference"


def high_overlap(a: str, b: str) -> bool:
    return _overlap(a, b) > 0.7


def low_overlap(a: str, b: str) -> bool:
    return _overlap(a, b) < 0.3


def _overlap(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    sa = set(re.findall(r"\w+", a.lower()))
    sb = set(re.findall(r"\w+", b.lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def is_doc_about_doc(content: str) -> bool:
    """True if the document is itself about documents (snowball risk)."""
    if not content:
        return False
    doc_refs = len(re.findall(r"documento|\.vsm|este documento|el doc", content, re.I))
    total_lines = len([l for l in content.split("\n") if l.strip() and not l.startswith("//")])
    if total_lines == 0:
        return False
    return doc_refs >= 3 and (doc_refs / total_lines) > 0.1


def doc_analyze(content: str) -> Dict[str, Any]:
    return {
        "topic": doc_extract_topic(content),
        "has_content": doc_has_content(content),
        "is_about_doc": is_doc_about_doc(content),
        "size": len(content or ""),
    }


def doc_classify(analysis: Dict[str, Any]) -> str:
    if not analysis.get("has_content"):
        return "EMPTY"
    if analysis.get("is_about_doc"):
        return "SNOWBALL"
    if analysis.get("topic"):
        return "CONTENT"
    return "UNKNOWN"


def classification_equals(a: str, b: str) -> bool:
    return str(a) == str(b)


def no_match_found(found_count: int) -> bool:
    return int(found_count) == 0


# ═══════════════════════════════════════════════════════════════════════
# SCRIPT PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def script_analyze(content: str) -> Dict[str, Any]:
    imports = re.findall(r"^\s*(?:import|from)\s+(\S+)", content or "", re.M)
    return {
        "imports": imports,
        "has_main": "if __name__" in (content or ""),
        "has_tree": "socratic(" in (content or ""),
        "size": len(content or ""),
    }


def script_has_tree(name: str) -> bool:
    tree_path = os.path.join(VSF_ROOT, ".opencode", "plugins", "support", "trees", f"{name}.tree.vsm")
    return os.path.exists(tree_path)


def script_needs_integration(analysis: Dict[str, Any]) -> bool:
    if not isinstance(analysis, dict):
        return False
    return analysis.get("size", 0) > 500 or len(analysis.get("imports", [])) > 5


def script_classify(analysis: Dict[str, Any]) -> str:
    if not isinstance(analysis, dict):
        return "UNKNOWN"
    if analysis.get("has_tree"):
        return "HAS_TREE"
    if analysis.get("has_main"):
        return "STANDALONE"
    return "MODULE"


def script_read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def staging_has_scripts(staging_dir: str) -> bool:
    if not staging_dir or not os.path.isdir(staging_dir):
        return False
    return any(f.endswith(".py") for f in os.listdir(staging_dir))


# ═══════════════════════════════════════════════════════════════════════
# STAGING PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def staging_has_docs(staging_dir: str) -> bool:
    if not staging_dir or not os.path.isdir(staging_dir):
        return False
    return any(f.endswith(".vsm") for f in os.listdir(staging_dir))


def staging_read_doc(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════
# VERSION / CHANGE PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def spec_changed(change_type: str) -> bool:
    return str(change_type).lower() in ("spec", "language", "vsl")


def version_bumped(file_path: str) -> bool:
    try:
        with open(file_path, encoding="utf-8") as fh:
            content = fh.read()
        m = re.search(r"@vsm\s+([\d.]+)", content)
        if not m:
            return False
        version = [int(x) for x in m.group(1).split(".")]
        return version > [1, 2, 1]
    except Exception:
        return False


def code_updated(change_type: str) -> bool:
    return str(change_type).lower() in ("code", "spec", "language", "parser")


def plugins_updated(change_type: str) -> bool:
    return str(change_type).lower() in ("plugins", "code", "spec", "hook")


def changelog_updated(change_type: str) -> bool:
    changelog = os.path.join(VSF_ROOT, "child", "docs", "changelog.vsm")
    if not os.path.exists(changelog):
        return False
    try:
        with open(changelog, encoding="utf-8") as fh:
            return "2026-08-28" in fh.read()
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# PROCEDURE PREDICATES (alias to original — kept here for hook trees)
# ═══════════════════════════════════════════════════════════════════════

def procedure_match_context(a: str, b: str) -> bool:
    return str(a) == str(b)


def procedure_match_instrument(a: str, b: str) -> bool:
    return str(a) == str(b)


# ═══════════════════════════════════════════════════════════════════════
# COMPOSITE / SELF-CONTAINED PREDICATES (take raw content, compute internally)
# These avoid the engine's lack of predicate-output → ctx propagation.
# ═══════════════════════════════════════════════════════════════════════

def doc_duplicate_check(content: str) -> bool:
    """Self-contained: extract topic, search, True if any existing doc matches."""
    topic = doc_extract_topic(content)
    found = doc_search_existing(topic)
    return bool(found)


def doc_exact_duplicate(content: str) -> bool:
    """Self-contained: True if MORE THAN ONE existing doc shares the topic."""
    topic = doc_extract_topic(content)
    found = doc_search_existing(topic)
    return len(found) > 1


def doc_snowball_check(content: str) -> bool:
    """Self-contained: True if the document is about documents (snowball risk)."""
    return is_doc_about_doc(content)


def const_true() -> bool:
    """Always-true predicate — used as the default branch in converted
    decision() chains (TRUE → {home:...})."""
    return True


# ── Classifier/security predicates (back converted decision() trees) ──

def has_pattern(ctx: Dict[str, Any], pattern: str) -> bool:
    """True if any string value in ctx matches the regex pattern.
    Used by covenant_validate / security_validate / adversarial_pipeline."""
    import re as _re
    try:
        rx = _re.compile(pattern)
    except _re.error:
        return False
    hay = " ".join(str(v) for v in ctx.values() if isinstance(v, (str, int, float)))
    return bool(rx.search(hay))


def purpose_in_forbidden_set(ctx: Dict[str, Any]) -> bool:
    """True if the requested action's purpose is in the forbidden set
    (vsf_root_gate). Checks ctx.purpose / ctx.action against a small
    blocklist of autonomy-violating intents."""
    purpose = str(ctx.get("purpose", ctx.get("action", ""))).lower()
    forbidden = ["disable safety", "bypass covenant", "overwrite rules",
                 "self modify core", "delete state", "exfiltrate"]
    return any(f in purpose for f in forbidden)


def resource_coercion_detected(ctx: Dict[str, Any]) -> bool:
    """True if the action coerces a protected resource (vsf_root_gate).
    Checks ctx.command / ctx.content for destructive patterns."""
    cmd = str(ctx.get("command", ctx.get("content", ""))).lower()
    coercion = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd", "chmod -r 000 /"]
    return any(c in cmd for c in coercion)


def has_approval(ctx: Dict[str, Any]) -> bool:
    """True if the document carries an approval/ratification marker.
    Checks CONTENT for 'approved by' / 'ratified' / an approver footer.
    NOTE: must NOT check the path for 'fuente' — that is the is_source
    signal and would make every FUENTE auto-approved (defeating the gate)."""
    content = ctx.get("new_doc_content", ctx.get("content", "")) or ""
    markers = ["approved by", "ratified", "aprobado por", "rmw3", "approver"]
    return any(m.lower() in content.lower() for m in markers)


# ═══════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════

def register_hooks_predicates(engine) -> int:
    """Register all hook-specific predicates with a SocraticEngine instance."""
    predicates = {
        "ctx_gt": ctx_gt,
        "doc_extract_topic": doc_extract_topic,
        "doc_search_existing": doc_search_existing,
        "doc_topic_exact_match": doc_topic_exact_match,
        "doc_topic_partial_match": doc_topic_partial_match,
        "doc_has_content": doc_has_content,
        "doc_topic_match": doc_topic_exact_match,
        "has_duplicates": has_duplicates,
        "is_source": is_source,
        "is_reference": is_reference,
        "high_overlap": high_overlap,
        "low_overlap": low_overlap,
        "is_doc_about_doc": is_doc_about_doc,
        "doc_analyze": doc_analyze,
        "doc_classify": doc_classify,
        "classification_equals": classification_equals,
        "no_match_found": no_match_found,
        "script_analyze": script_analyze,
        "script_has_tree": script_has_tree,
        "script_needs_integration": script_needs_integration,
        "script_classify": script_classify,
        "script_read": script_read,
        "staging_has_scripts": staging_has_scripts,
        "staging_has_docs": staging_has_docs,
        "staging_read_doc": staging_read_doc,
        "spec_changed": spec_changed,
        "version_bumped": version_bumped,
        "code_updated": code_updated,
        "plugins_updated": plugins_updated,
        "changelog_updated": changelog_updated,
        "procedure_match_context": procedure_match_context,
        "procedure_match_instrument": procedure_match_instrument,
        "doc_duplicate_check": doc_duplicate_check,
        "doc_exact_duplicate": doc_exact_duplicate,
        "const_true": const_true,
        "has_pattern": has_pattern,
        "purpose_in_forbidden_set": purpose_in_forbidden_set,
        "resource_coercion_detected": resource_coercion_detected,
        "doc_snowball_check": doc_snowball_check,
        "has_approval": has_approval,
    }
    count = 0
    for name, func in predicates.items():
        if name not in engine.predicates:
            engine.register(name)(func)
            count += 1
    return count


if __name__ == "__main__":
    from socratic_engine import SocraticEngine
    eng = SocraticEngine()
    # also load original classifier predicates if available
    try:
        import vsf_predicates
        vsf_predicates.register_vsf_predicates(eng)
    except Exception:
        pass
    n = register_hooks_predicates(eng)
    print(f"Registered {n} hook predicates. Total engine predicates: {len(eng.predicates)}")

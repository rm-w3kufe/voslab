#!/usr/bin/env python3
"""symbol_table.py — index every identifier and glyph in a VSL corpus.

WHY THIS EXISTS
---------------
Certifying docs/spec_revision needs three questions answered exactly:

    identifier -> namespace | where DEFINED | where CITED | arity
    glyph      -> where DECLARED | where USED
    document   -> @status | which anchors it validates against

On 2026-08-07 those were answered with ad-hoc greps, one per question, and
most of them were wrong:

  * the list-separator sweep reported 8 findings; 7 were the declaration of
    the symbol itself, or a continuation line of a multiplication
  * the dash sweep flagged every ISO date as a misplaced minus
  * the historical_record sweep skipped the certification rubric, because the
    rubric's own TEXT contains the string it searches for
  * the loop-class sweep filtered by keyword and missed Ax_ReframeScope in
    two documents

Each error cost a round of over-reporting and correction. Over boot/'s six
documents that was tolerable. The rest of system/ is 20 documents and 6375
lines, with ~34 identifiers to sweep against four namespaces -- there, a tool
that is wrong 7 times out of 8 is worse than no tool, because its output gets
believed.

WHAT MAKES THIS DIFFERENT FROM A GREP
-------------------------------------
1. Comments are stripped structurally (`//` to EOL, `://` protected), so an
   identifier discussed in prose is never counted as declared.
2. DEFINITION and CITATION are distinguished by POSITION, not by keyword: an
   identifier that opens a line is a definition; one that appears mid-line is
   a citation. Blocks annotated as citation blocks force everything inside
   them to CITATION regardless.
3. Namespaces are matched longest-first, so `A8.vOS` is never read as `A8`,
   `D4-L2` is never read as `L2`, and `DP1` is never read as `D1`.
4. `@status` is read from the document HEADER REGION only -- the first 40
   lines -- so a document that merely mentions a status value in its body is
   not classified by it.

Usage:
  python3 scripts/vsl/symbol_table.py                # summary
  python3 scripts/vsl/symbol_table.py --dupes        # ids defined >1 place
  python3 scripts/vsl/symbol_table.py --id A5        # one identifier
  python3 scripts/vsl/symbol_table.py --glyph ×      # one glyph
  python3 scripts/vsl/symbol_table.py --undeclared   # glyphs used, ¬declared
  python3 scripts/vsl/symbol_table.py --json         # the whole index

Deterministic, stdlib-only. No LLM in this path (R10).
"""
from __future__ import annotations
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tokenizer import tokenize   # one structural read, shared by every tool

ROOT = Path(__file__).resolve().parents[3]

# SCOPE, ratified rmw3 (S5) 2026-08-07: the object of work is system/ ONLY.
# docs/spec_revision/ outside system/ is META -- revision_plan, the census,
# the worklist, the compression ledger, this rubric. Those are the work's
# GUIDES, not the work. Certifying them was scope creep: it produced 41 D7
# findings in a ledger that is a record of translation operations, not a
# specification.
# D-07 fix (2026-10-01): the local mirror held 1 doc after the archive
# migration, so --d7 reported a false clean ("0 in 0") on an empty tree.
# The LIVE system corpus (113 docs) is the upstream read-only copy; default
# there, allow D7_CORPUS to point elsewhere, and refuse to report clean on
# an empty corpus (guard in --d7 below). Scope (system/ ONLY) unchanged.
# S5 second-order repair (2026-10-03): the canonical system/ corpus now
# LIVES in this repo (canon-over-recall: bring the canon home).
# S5 external-paths repair (2026-10-06): the ~/vsf fallback is gone — local
# mirror only, D7_CORPUS still overrides; a missing mirror refuses clean
# (exit 2, guard in --d7 below) instead of silently scanning an external tree.
_MIRROR_CORPUS = ROOT / "docs/spec_revision/system"
CORPUS = (Path(os.environ["D7_CORPUS"]) if os.environ.get("D7_CORPUS")
          else _MIRROR_CORPUS)
META = ROOT / "docs/spec_revision"
SKIP_DIRS = {"agent_layer"}

# Identifier shapes, LONGEST FIRST. Order is load-bearing: `A8` would swallow
# the `A8` inside `A8.vOS` and report a collision that does not exist.
ID_PATTERNS = [
    # Greek in a formal identifier: the charset was ΩψτσλμΩ only, so `Ax_Aε`
        # matched as `Ax_A` and was reported as an axiom cited nowhere. The
        # truncated name looked like a real orphan for as long as nobody
        # opened the line. Widened to the Greek block.
    (r"(?:Ax|Def|Thm|Cor|Lemma)_[A-Za-z_0-9Ͱ-Ͽἀ-῿]+", "formal"),
    (r"[ADR]\d+(?:\.\d+)?\.[A-Za-z][A-Za-z0-9]*", "namespaced"),   # A8.vOS
    (r"D4-L[123]", "loop_class"),
    (r"VSI-L[1-4]", "protocol_layer"),
    (r"DP\d+", "session_pattern"),
    (r"A\d+(?:\.\d+)?", "axiom"),
    (r"D\d+[a-z]?", "definition"),
    (r"R\d+(?:_\d+)?", "rule"),
]
# Superscript digits before an identifier mean it is a fragment of a
# Unicode numeral, ¬an identifier: ℝ²⁵⁶ was being read as `A256` because the
# match started after the ℝ. Guard both edges.
ID_RE = re.compile(
    r"(?<![A-Za-z0-9_⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉])"
    + "(?:" + "|".join(f"(?:{p})" for p, _ in ID_PATTERNS) + ")"
    + r"(?![⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉])")


def kind_of(ident: str) -> str:
    for pat, kind in ID_PATTERNS:
        if re.fullmatch(pat, ident):
            return kind
    return "unknown"


# Decorative and prose punctuation carry no notation meaning.
DECORATIVE = set("═─│┌┐└┘├┤┬┴┼—–…“”‘’")


# Quoted non-Latin script the alphabet declares wholesale: the etymology
# ἀλγηδών. Listed explicitly so ANY other Greek-script prose is reported
# rather than absorbed by a category rule.
SCRIPT_QUOTE = set("ἀλγηδών")

# Natural-language scripts that must NEVER appear in this corpus. Named
# explicitly rather than as "not LATIN": ℝ ℱ ℚ 𝐄 𝐏 ℓ ᵀ ˣ µ are all
# category-L characters whose names carry no LATIN, and they are declared
# NOTATION. A first version of this check reported all nine as foreign and
# would have been switched off within a day -- an over-reporting gate is an
# ignored gate.
NATURAL_SCRIPT = (
    "CYRILLIC", "ARABIC", "HEBREW", "CJK", "HIRAGANA", "KATAKANA",
    "HANGUL", "DEVANAGARI", "THAI", "ARMENIAN", "GEORGIAN", "BENGALI",
    "TAMIL", "TELUGU", "KANNADA", "MALAYALAM", "SINHALA", "MYANMAR",
    "KHMER", "LAO", "TIBETAN", "MONGOLIAN", "ETHIOPIC", "CHEROKEE",
)

# D7: every committed file is in English. ONE exception, ratified rmw3 (S5)
# 2026-08-07: covenant.vsm is bilingual BY DESIGN -- its preamble, A0.1
# corollary and governance clauses carry paired ES/EN, and the Spanish is the
# original. Nothing else in the corpus may be.
#
# Accents alone do not find Spanish: `para que los archivos` has none, and
# `Naïve` is English. These are function words that are unambiguously Spanish
# and frequent enough that any Spanish sentence trips at least one.
D7_EXEMPT = {"covenant.vsm"}

# DOCUMENT epistemic state, declared in boot/vsl_language §@status(doc). NOT
# the V-lifecycle enum (planned/testing/production) -- that one is written
# inside a system definition and says what the SYSTEM is doing. Two fields,
# one name, and until 2026-08-09 only the second was declared: the corpus had
# already drifted to 13 distinct values against 7 declared, overlapping in 3.
PARAM = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\s*=\s*(-?\d+(?:\.\d+)?)\b")
# SUBSTRATE-AGNOSTIC ⟹ CANON. rmw3 (S5) 2026-08-09: "todos los valores
# invariables, agnósticos del sustrato, son canon... todos los que son
# artefactos de la instancia, a la instancia."
# These are declared ONCE in the canon or the kernel and CITED by name; an
# instance may not override them. Restating one in a second document is still
# a defect — but it is a DUPLICATE-DECLARATION defect, gated by
# spec_kernel_reconcile against the Rust, ¬by this check.
# Named rather than pattern-matched: the discriminator is a judgement, and
# this list is where the judgement is written down. If it grows without an
# argument, the rule is being eroded.
CANON_CONST = {
    "READY", "WATCHDOG",
    # f₀'s state-space geometry — identical on any substrate. Empirically
    # measured and revisable; a constant refined by a better instrument is
    # still a constant.
    "BASIN_FLOOR", "D_KY", "VIABLE_THRESHOLD", "LAMBDA_CALIBRATED",
    "LYAP_R_CORE", "VR_EPSILON_COSINE",
}

DOC_STATUS = {"active", "ratified", "proposed", "conjecture", "developing",
              "template", "historical_record"}
# ONE exception, and it is a DEFERRAL, not a waiver: covenant.vsm carries a
# pending 1.1 -> 1.2 amendment and a SHA256 registered in
# docs/spec/covenant_hash_registry.vsm. Its status line rides with rmw3's own
# covenant promotion, not with a tooling pass -- editing a constitutional
# document to satisfy a gate I wrote the same day is the wrong order.
#   debt(COVENANT-STATUS-DEFERRED, class=doc, owner=rmw3, gate=covenant_1_2)
STATUS_EXEMPT = {"boot/covenant.vsm"}
# BLIND SPOT, stated rather than papered over: this axis detects SPANISH. It
# was built for the one language the corpus was translated FROM, and it cannot
# see any other. `voir A1/P17` -- French -- sat in a fused document and passed
# every run, exactly as two Cyrillic letters did on 2026-08-08.
# The non-Latin script check catches scripts; nothing catches another
# LATIN-script language. Adding French/German/Italian word lists would trade
# one blind spot for four, so the honest guard is the one already in place:
# an English-only corpus is verified by READING, and this axis narrows the
# search, it does not close it.
OTHER_LATIN_LANG_UNCHECKED = True
# Deliberately EXCLUDED, each a live false positive found on the first run:
#   todo   -> the TODO marker            sin  -> "cardinal sin"
#   solo   -> "SOLO" as emphasis         para -> too weak alone
# A line trips only on TWO distinct markers, or on ONE accented Spanish word
# that is not an English loanword. One weak signal is not evidence.
SPANISH = {
    "que", "con", "los", "las", "del", "por", "una", "este", "esta",
    "pero", "más", "cuando", "donde", "desde", "hasta", "sobre", "entre",
    "muy", "así", "todos", "cada", "sus", "fue", "hay", "está", "están",
    "ser", "hacer", "puede", "debe", "tiene", "según", "porque", "también",
    "aunque", "mientras", "durante", "antes", "después", "ahora", "aquí",
    "otro", "otra", "misma", "mismo", "ningún", "alguna", "algún",
    "cualquier", "para",
    # CONTENT words, added 2026-08-07 after reading s5_policy_core found five
    # the function-word rule could not see: `design ratificado`, `autoridad:`,
    # `protocolo rmw3`, `absorbidos en`, `pedido rmw3`. One Spanish content
    # word with no accent in an otherwise-English line trips neither the
    # two-marker rule nor the accent rule. Each of these is unambiguous —
    # ¬an English homograph.
    "ratificado", "ratificada", "autoridad", "protocolo", "absorbidos",
    "absorbido", "pedido", "diseño", "archivo", "archivos", "fuente",
    "fuentes", "documento", "documentos", "revisión", "cambios", "sesión",
    "actual", "estado", "nivel", "niveles", "reglas", "detalle",
}
# Single unambiguous Spanish content words trip on their own -- one is enough
# when the word cannot be English.
SPANISH_STRONG = {
    "ratificado", "ratificada", "autoridad", "protocolo", "absorbidos",
    "absorbido", "pedido", "diseño", "archivos", "documento", "documentos",
    "revisión", "sesión", "fuentes", "reglas", "niveles",
}
# Accented words that ARE English (or proper nouns the corpus legitimately
# carries). Anything else with a Spanish accent is Spanish.
ACCENT_OK = {"naïve", "valparaíso", "résumé", "café", "über", "señor",
              # proper nouns the corpus legitimately carries
              "raúl", "bézout", "poincaré", "lyapunov", "krasnoselskii",
              # ENSO index names. El Niño / La Niña / Niño 3.4 are the terms
              # the English climatological literature uses; they are Spanish
              # in origin and English in use.
              "niño", "niña", "el", "la"}
# The alphabet's own diacritic marks (x̄ mean, x̂ estimate) and the letters
# of proper nouns it legitimately carries.
DECLARED_MARKS = set("\u0302\u0304") | set("áéíóúüñÁÉÍÓÚÜÑïÏ")
ACCENTED = re.compile(r"\b[a-z]*[áéíóúüñ][a-záéíóúüñ]*\b", re.I)
WORD = re.compile(r"\b[a-záéíóúüñ]+\b", re.I)


def classify(ch: str) -> str:
    """Every non-ASCII character lands in exactly ONE class. Nothing is
    silently dropped.

    The first version returned False for any Latin letter. That meant `Ê` in
    `P_Ê = P with the E-complement absorbing` was never examined -- while the
    alphabet declares the circumflex as ESTIMATE (x̂). Two meanings, one
    diacritic, and the tool reported "all glyphs declared". Spanish accents
    (explicit, down -- D7) were dropped by the same rule.

    A checker that discards part of its input and reports clean is worse than
    no checker. Calibrated 2026-08-07, after rmw3 found `Ê` by reading what
    the tool had passed.
    """
    if ch.isascii() or ch.isspace():
        return "ascii"
    if ch in DECORATIVE:
        return "decorative"
    if ch in SCRIPT_QUOTE:
        return "script_quote"
    cat = unicodedata.category(ch)
    name = unicodedata.name(ch, "")
    if cat.startswith("L"):
        if "GREEK" in name:
            return "glyph"                      # Greek letters ARE VSL variables
        if "DOUBLE-STRUCK" in name or "SCRIPT CAPITAL" in name:
            return "glyph"                      # ℝ ℱ ℚ: category-L, declared
                                                # NOTATION (core_boot_primer.
                                                # notation, 2026-08-14). The
                                                # comment at NATURAL_SCRIPT
                                                # said this; the code never
                                                # did it — they fell to
                                                # "latin", the one class
                                                # nothing reports, so 75 ℝ in
                                                # system/ passed every gate.
        if any(name.startswith(sc) for sc in NATURAL_SCRIPT):
            return "foreign_script"
            # 2026-08-08. Cyrillic а and Latin a are the SAME PIXELS. Two  # foreign-script-allow: homoglyph illustration
            # Cyrillic letters sat in s3star_audit.vsm:54 -- model output
            # bleeding Russian into an English spec -- and passed EVERY gate,
            # because this function returned "latin" for any alphabetic
            # character whose name it had not checked, and "latin" is the one
            # class nothing reports. Third instance of this blind spot: first
            # Ê, then Latin letters generally, now every non-Latin script.
            # A homoglyph in a spec is an identifier that silently mismatches.
        nfd = unicodedata.normalize("NFD", ch)
        if any(unicodedata.category(c) == "Mn" for c in nfd):
            return "latin_diacritic"            # notation OR non-English prose
        return "latin"
    if cat == "Mn":
        return "latin_diacritic"                # a bare combining mark
    return "glyph"


def is_glyph(ch: str) -> bool:
    return classify(ch) == "glyph"


COMMENT = re.compile(r"(?<!:)//.*$")          # `://` in a URL is not a comment

# hard_rules.R_ref_resolution: `explicit_path_in_system_body ⟹ ⊥`. A system/
# document names external things by @var; instance/instance.vsm binds @var to
# a concrete path. The stated reason is publication safety -- a spec on GitHub
# must ¬carry this repository's layout.
#
# This lived as ad-hoc python until 2026-08-07, which is why boot/ accumulated
# 19 explicit paths (16 of them written the same day, declaring the gates).
# A rule with no query is a rule nobody can check.
# Two shapes leak this repository's layout into a published spec:
#   repo-relative   scripts/… docs/… projects/… core/…
#   user-absolute   ~/… /home/… /root/…
# Only the first was matched. lagrange_reduction carried
# /home/rmw3/tda-data2/traj_full.npy through every green run until
# 2026-08-08. OS ABI paths (/proc, /sys, /etc) stay unmatched on purpose
# -- those are substrate, ¬layout, and R_ref_resolution is about layout.
EXPLICIT_PATH = re.compile(
    r"(?<!@)(?:\b(?:scripts|docs|projects|core)/[A-Za-z0-9_./-]+"
    r"|(?:~|/home|/root)/[A-Za-z0-9_./-]+)")

# RELATIVE paths with an extension — `vault/triage/x.md`, `src/attractor.rs`.
# The pattern above anchors on scripts/ docs/ projects/ core/ ~/ /home /root
# and missed anything rooted elsewhere: 4 real violations in 2 documents sat
# unreported while --paths printed 0. Measured on the corpus: this finds
# exactly those 4 and ∄ false positive.
# `@vault triage/x.md` is the CORRECT form — a binding followed by a relative
# path — so a match preceded by `@word ` is ¬a violation. Without that guard
# the fix for three literal paths reported the three replacements.
# The binding REGISTRY names itself, and so does the rule that governs it.
# hard_rules §R_ref_resolution must say WHERE bindings live, and documents
# inside instance/ are the one place concrete paths are legal. Naming the
# registry is ¬a layout leak.
REGISTRY_NAME = {"instance/instance.vsm"}

EXPLICIT_PATH_REL = re.compile(
    # `(?<![/@\w] )` and `(?<!/)`: an ABSOLUTE path is SUBSTRATE, ¬layout —
    # /var/lib/vsf-state/…, /run/vsf/… — and the anchored pattern above
    # already excludes /proc /sys /etc for that reason. This one strips the
    # leading slash and caught four of them in s4_anticipation. R_ref_resolution
    # is about REPO LAYOUT.
    r"(?<![/\w@.-])(?<![@\w] )(?!https?:)[a-z_][a-z_0-9-]*(?:/[a-z_0-9.-]+)+"
    r"\.(?:vsm|md|py|rs|json|sh|toml|ttl)\b")
# THREE roots, all three legal in instance.vsm and nowhere else:
#   */         this repository        spec_root:  the published spec
#   node:      an absolute node path
# The first version matched */ ALONE. Rebasing three bindings onto spec_root:
# and node: on 2026-08-08 made them invisible to this query -- the binding
# count silently fell and the references they serve read as unbound.
BINDING = re.compile(r'^\s{4}([a-z_0-9]+):\s*"(?:\*/|spec_root:|node:)([^"]+)"', re.M)
# A binding is REFERENCED by @var or by the document's own NAME: naming
# covenant_ops or state.db in prose is not a path and needs no substitution.
BINDING_ALIAS = {"covenant_ops": "covenant_ops", "notation_spec": "vsm_notation_spec",
                 "state_db": "state.db", "connection_schema": "connection_schema",
                 "envelope_validator": "envelope"}
# @tokens that are NOT path bindings: header keys, enum values, annotation
# markers. Anything @-prefixed and absent from BOTH this set and the bindings
# is a DANGLING reference. Declared as an allowlist deliberately -- a new
# unknown @token must surface as a finding, not pass because the check was
# written to notice only what it already knew about.
# `param` joins the directive allowlist: hard_rules §R_param_resolution
# writes `bind(@param) ∈ instance.vsm` to state the RULE — it is a
# METAVARIABLE, ¬a citation of a binding called `param`. Same class as
# the `@src_*` glob already excluded here.
DIRECTIVE = {
    # header / structural keys
    "vsm", "status", "ref", "var", "version", "commit", "level",
    # role + provenance annotations (authorship, signatory, channel lines)
    "human", "witness", "experimenter", "idea_origin", "formalization",
    "analysis", "channel", "session", "external", "bbh",
    # enum values on declarations
    "required", "forbidden", "strict", "requires", "governed", "free",
    "degraded", "optional", "always", "sporadic", "configurable", "approved",
    "approval_required", "consulted", "condition", "target", "tick",
    "updated", "pinned_version", "full_vsm",
    # METAVARIABLE, ¬a binding: hard_rules §R_param_resolution writes
    # `bind(@param) ∈ instance.vsm` to state the RULE. Same class as the
    # `@src_*` glob already excluded here.
    "param",
}
# @canal and @experimentador were caught here first, ¬by --d7: the D7 axis
# reads prose words and an annotation token is neither prose nor a word it
# scores. Two Spanish tokens sat inside a CERTIFIED document. Renamed
# 2026-08-08; the allowlist is now the second place D7 gets enforced.
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# `IDENT:` or `IDENT =` opening a line is a DECLARATION, whatever the
# surrounding string state.
DECL_OP = re.compile(r"^[A-Za-z_][A-Za-z_0-9.\-]*\s*[:=](?![:=])")
CITATION_BLOCK = re.compile(r"^\s*(compliance|references|basis|sources)\s*[:=]")
# SOLVED 2026-08-09 by quote parity, after being recorded as a known limit.
# --dupes had reported D6 as "defined" in s4_anticipation and s4_visualization.
# Both documents were CORRECT; the index was wrong. The offending lines were
#   s4_anticipation:1095   `D6: removing the LLM`
#   s4_visualization:122   `D6 (no LLM at L<2) gated; panel never emits…`
# -- each the WRAPPED TAIL of a quoted string, where the positional rule
# ("an identifier opening a line is a definition") cannot apply.
# The fix is structure, ¬a heuristic: a line that BEGINS while a string is
# still open is a continuation, never a declaration site. Verified both ways --
# D6 is now defined ONLY in boot/vsl_language.vsm, and 0 identifiers ended up
# cited-but-defined-nowhere, which is the failure mode of over-correcting.


def strip_comment(line: str) -> str:
    return COMMENT.sub("", line)


class Index:
    def __init__(self) -> None:
        self.defined: dict[str, set[str]] = defaultdict(set)
        self.cited: dict[str, set[str]] = defaultdict(set)
        self.arity: dict[str, set[int]] = defaultdict(set)
        self.glyph_used: dict[str, set[str]] = defaultdict(set)
        self.glyph_declared: dict[str, set[str]] = defaultdict(set)
        # Latin letters carrying a diacritic. NEVER dropped: each is either
        # notation needing a declaration (Ê, x̄, x̂) or non-English prose (D7).
        self.diacritic: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
        # Non-Latin script. Homoglyph risk: Cyrillic а and Latin a are the  # foreign-script-allow: homoglyph illustration
        # same pixels, so this can never be a silent class.
        self.foreign: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
        self.docs: dict[str, dict] = {}

    # ---- ingestion ----------------------------------------------------
    def add_file(self, path: Path) -> None:
        rel = str(path.relative_to(CORPUS))
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # @status is read from the HEADER REGION only. Scanning the whole body
        # made the certification rubric classify itself as a historical_record,
        # because the rubric DESCRIBES that status in its own rules.
        head = "\n".join(lines[:40])
        m = re.search(r"@status\s+([a-z_]+)", head)
        status = m.group(1) if m else None
        hdr = re.match(r"⟦([^⟧]*)⟧", lines[0].strip()) if lines else None
        self.docs[rel] = {
            "status": status,
            "identity": hdr.group(1).split("|")[0].strip() if hdr else None,
            "lines": len(lines),
        }

        # A document declaring its own alphabet DECLARES the glyphs inside it;
        # every other occurrence is a use. boot/ carries both sections.
        decl_lo, decl_hi = self._declaration_span(text, lines)

        in_citation_block = False
        # Structure comes from the tokenizer now, ¬from counting quotes here.
        tok = tokenize(path).lines
        for i, raw in enumerate(lines):
            body = strip_comment(raw)
            if CITATION_BLOCK.match(body):
                in_citation_block = True
            elif body.strip() in ("}", "],", "}"):
                in_citation_block = False

            for ch in raw:
                cls = classify(ch)
                if cls == "glyph":
                    if decl_lo <= i <= decl_hi:
                        self.glyph_declared[ch].add(rel)
                    else:
                        self.glyph_used[ch].add(rel)
                elif cls == "latin_diacritic":
                    j = raw.index(ch)
                    self.diacritic[ch].append(
                        (rel, i + 1, raw[max(0, j - 34):j + 30].strip()))
                elif cls == "foreign_script":
                    j = raw.index(ch)
                    self.foreign[ch].append(
                        (rel, i + 1, raw[max(0, j - 34):j + 30].strip()))

            if not body.strip():
                continue
            stripped = body.strip()
            first = ID_RE.match(stripped)
            # A line that BEGINS while a string is still open is a wrapped
            # CONTINUATION, never a declaration site. Without this, the
            # positional rule read `D6: removing the LLM` (mid-sentence, inside
            # a quoted block) as a DEFINITION of D6 -- in two documents, both
            # correct, and both then reported as redefining a canon rule.
            # A DECLARATION SURVIVES AN OPEN STRING. In VSL a quoted block is
            # a CONTAINER for declarations, ¬only prose: boot/regulation_layer
            # writes `Ax_TraceabilityClosure:` inside `boundary: "…"`, and
            # dynamics_choice writes `Ax_QuasiStationary:` inside
            # `final_axioms:`. Quote parity alone marked five real declarations
            # as continuations.
            # Found by exporting the index to RDF and asking which identifiers
            # are cited and defined nowhere — 5 of the 29 answers were the
            # index being wrong, ¬the corpus.
            #
            # 2026-08-09: quote parity RETIRED here. It desynchronised on any
            # line with an odd quote count and then poisoned every line after
            # it — which is how two unterminated strings survived certification
            # in s3star_audit and s4_visualization. tokenizer.py answers the
            # question once, structurally, for every tool.
            # VSL declares in TWO forms and both are real:
            #   operator     `Ax_QuasiStationary: "∃ π …"`
            #   juxtaposition `A1   S1(L) = { V_i(L+1) }`   ← the canon's axioms
            # Requiring the operator alone dropped `defined` 116 → 57 and made
            # A1..A15, D1..D21, DP1..DP5 and every VSI-L* "cited nowhere".
            # So the operator is ¬the discriminator. The discriminator is
            # whether the line begins INSIDE a string: outside, an identifier
            # opening a line declares; inside, it declares only if it carries a
            # definition operator (a quoted VSL block still holds declarations).
            # That is the old rule — what changed is that `in_string` now comes
            # from a real scan instead of quote parity.
            was_open = tok[i].in_string and tok[i].kind != "declaration"
            # SECOND declaration on the same line: `D16 adaptive_τ:
            # Def_Adaptiveτ: …` declares three. The tokenizer carries them
            # in names[]; without this they read as CITED.
            for extra in tok[i].names[1:]:
                if ID_RE.fullmatch(extra):
                    self.defined[extra].add(rel)
            for m2 in ID_RE.finditer(body):
                ident = m2.group(0)
                opens_line = (first is not None
                              and m2.start() == body.index(stripped)
                              and not in_citation_block
                              and not was_open)
                (self.defined if opens_line else self.cited)[ident].add(rel)

            # A document may declare in FUNCTIONAL form -- vos_proofs.vsm
            # writes `corollary(Cor_4, "trust mismatch", ...)` rather than
            # `Cor_4:` at line start. The position rule alone reported 14 of
            # its identifiers as cited-but-never-defined.
            for m4 in re.finditer(
                    r"\b(?:axiom|theorem|corollary|lemma|definition)\s*\(\s*"
                    r"([A-Za-z][A-Za-z0-9_]*)", body):
                ident = m4.group(1)
                self.defined[ident].add(rel)
                self.cited[ident].discard(rel)

            for m3 in re.finditer(r"\b([a-z_][a-z_0-9]{2,})\s*\(([^()]*)\)",
                                  body):
                args = [a for a in m3.group(2).split(",") if a.strip()]
                self.arity[m3.group(1)].add(len(args))

    @staticmethod
    def _declaration_span(text: str, lines: list[str]) -> tuple[int, int]:
        """Line range of the document's own alphabet/notation block."""
        # ("alphabet:", "2. AXIOMS") matched the pre-2026-08-13 single-file
        # vsl_language.vsm. The promoted primer (vsl_language_primer.vsm)
        # numbers its sections: its alphabet block ends at "4. TYPES".
        # Added 2026-08-13 (DS, S3) — required for the v1→primer+set split;
        # vos_core_theory.vsm has no "4. TYPES" so its behavior is unchanged.
        for opener, closer in (("alphabet:", "2. AXIOMS"),
                               ("alphabet:", "4. TYPES"),
                               ("notation:", "structure:")):
            if opener in text and closer in text:
                lo = next(i for i, l in enumerate(lines) if opener in l)
                hi = next(i for i, l in enumerate(lines) if closer in l)
                return lo, hi
        return -1, -2      # empty range

    # ---- queries -------------------------------------------------------
    def duplicates(self) -> dict[str, set[str]]:
        live = {d for d, meta in self.docs.items()
                if meta["status"] != "historical_record"}
        return {i: (d & live) for i, d in self.defined.items()
                if len(d & live) > 1}

    def undeclared(self) -> dict[str, set[str]]:
        declared = set(self.glyph_declared)
        pattern = set("¹²³⁴⁵⁶⁷⁸⁹⁰₀₁₂₃₄₅₆₇₈₉⁺⁻")   # xⁿ/xₙ, declared as a pattern
        return {g: d for g, d in self.glyph_used.items()
                if g not in declared and g not in pattern}


def main() -> int:
    idx = Index()
    for f in sorted(CORPUS.rglob("*.vsm")):
        if any(s in f.parts for s in SKIP_DIRS):
            continue
        idx.add_file(f)

    if "--json" in sys.argv:
        print(json.dumps({
            "documents": idx.docs,
            "defined": {k: sorted(v) for k, v in idx.defined.items()},
            "cited": {k: sorted(v) for k, v in idx.cited.items()},
            "glyphs_declared": {k: sorted(v) for k, v in idx.glyph_declared.items()},
        }, indent=2, ensure_ascii=False))
        return 0

    if "--params" in sys.argv:
        # R_param_resolution (rmw3 S5, 2026-08-09). A calibration literal
        # restated in a system/ body is a SECOND source of truth for a value
        # that must have one. Measured at ratification: BASIN_FLOOR appeared
        # in 3 documents, and D_KY was already written `3` in one and `3.00`
        # in another — divergent in FORM, which is how the class begins.
        #
        # CONSTITUTIVE constants are NOT parameters and are excluded by name,
        # per the discriminator: could two conforming nodes disagree on this
        # and both stay conforming? For A1's +1 and D6's L_min the answer is
        # no, so they stay in the canon where an instance cannot override
        # them. The exclusion list is the discriminator made executable — if
        # it grows without an argument, the rule is being eroded.
        bound = set(idx.bindings) if hasattr(idx, "bindings") else set()
        hits = defaultdict(list)
        for rel, path in [(str(f.relative_to(CORPUS)), f)
                          for f in sorted(CORPUS.rglob("*.vsm"))
                          if not any(s in f.parts for s in SKIP_DIRS)]:
            if rel.startswith("instance"):
                continue                  # the bindings registry IS the place
            for i, raw in enumerate(path.read_text(encoding="utf-8")
                                    .splitlines(), 1):
                for m in PARAM.finditer(strip_comment(raw)):
                    if m.group(1) in CANON_CONST or m.group(1) in bound:
                        continue
                    hits[m.group(1)].append((rel, i, m.group(2)))
        multi = {k: v for k, v in hits.items()
                 if len({r for r, _, _ in v}) > 1}
        for k, v in sorted(hits.items()):
            vals = sorted({val for _, _, val in v})
            n_doc = len({r for r, _, _ in v})
            mark = "✗" if k in multi else "◐"
            print(f"  {mark} {k:<22} {n_doc} doc(s) · {vals}"
                  f"{'  ← DIVERGENT' if len(vals) > 1 else ''}")
            for r, i, val in v[:3]:
                print(f"        {r}:{i}")
        if multi:
            print(f"  ✗ {len(multi)} calibration literal(s) restated in more "
                  f"than one system/ document — R_param_resolution")
            return 1
        if hits:
            print(f"  ◐ {len(hits)} calibration literal(s) in a system/ body, "
                  f"each in ONE document — bind them in instance.vsm")
            return 0
        print("  ✓ params: ∄ substrate-artifact literal in a system/ body")
        return 0

    if "--status" in sys.argv:
        missing = [k for k, v in sorted(idx.docs.items())
                   if not v.get("status") and k not in STATUS_EXEMPT]
        wrong = [(k, v["status"]) for k, v in sorted(idx.docs.items())
                 if v.get("status") and v["status"] not in DOC_STATUS]
        for k in missing:
            print(f"  ✗ {k}: ∄ @status — a reader must GUESS how much weight "
                  f"this document carries")
        for k, s in wrong:
            print(f"  ✗ {k}: @status '{s}' ¬in the declared vocabulary "
                  f"{sorted(DOC_STATUS)}")
        if missing or wrong:
            print(f"  ✗ @status: {len(missing)} missing, {len(wrong)} "
                  f"off-vocabulary — declared in boot/vsl_language §@status(doc)")
            return 1
        print(f"  ✓ @status: {len(idx.docs) - len(STATUS_EXEMPT)} documents, "
              f"all declared and in vocabulary "
              f"({len(STATUS_EXEMPT)} declared exception)")
        return 0

    if "--gates" in sys.argv:
        # A document whose FUSE GATE is still open is a DRAFT, whatever its
        # header says. Found 2026-08-10: three s5-policy documents carried
        # `@status active` — in force, describes what IS — while the ledger
        # still recorded their fuse as "DRAFT pending claude_review".
        # I assigned those statuses by READING each document and never looked
        # at its gate. The header and the ledger disagreed and nothing asked.
        led = (ROOT / "docs/spec_revision/ledger/compression-ledger-v1/compression_ledger.vsm")
        if not led.exists():
            print("  ◐ gates: ∄ ledger to check against")
            return 0
        text = led.read_text(encoding="utf-8")
        open_gate = set()
        for blk in text.split("op(")[1:]:
            head = blk[:blk.find("\n  }")] if "\n  }" in blk else blk
            if "DRAFT pending claude_review" in head or \
               "claude_review — DRAFT" in head:
                for line in head.splitlines():
                    if "fuse:" in line and "system/" in line:
                        open_gate.add(line.split("system/")[1].split('"')[0])
        bad = [(k, v["status"]) for k, v in sorted(idx.docs.items())
               if k in open_gate and v.get("status") == "active"]
        for k, s in bad:
            print(f"  ✗ {k}: @status '{s}' but its fuse gate is still OPEN "
                  f"— a document under review is a DRAFT")
        if bad:
            print(f"  ✗ gates: {len(bad)} document(s) claim to be in force "
                  f"while awaiting review")
            return 1
        print(f"  ✓ gates: {len(open_gate)} open review gate(s), none claiming "
              f"to be in force")
        return 0

    if "--dupes" in sys.argv:
        dup = idx.duplicates()
        print(f"  identifiers DEFINED in >1 live document: {len(dup)}")
        hist = [d for d, m in idx.docs.items()
                if m["status"] == "historical_record"]
        if hist:
            print(f"  skipped (@status historical_record): {', '.join(hist)}")
        print()
        for i in sorted(dup, key=lambda x: (-len(dup[x]), x)):
            print(f"    {i:<16} [{kind_of(i)}]  {' · '.join(sorted(dup[i]))}")
        return 0

    for flag, store in (("--id", None), ("--glyph", None)):
        if flag in sys.argv:
            arg = sys.argv[sys.argv.index(flag) + 1]
            if flag == "--id":
                print(f"  {arg}  [{kind_of(arg)}]")
                print(f"    defined : {sorted(idx.defined.get(arg, [])) or '—'}")
                print(f"    cited   : {sorted(idx.cited.get(arg, [])) or '—'}")
            else:
                print(f"  {arg}  U+{ord(arg):04X} "
                      f"{unicodedata.name(arg, '?')}")
                print(f"    declared: {sorted(idx.glyph_declared.get(arg, [])) or '— NOWHERE'}")
                print(f"    used    : {len(idx.glyph_used.get(arg, []))} docs")
            return 0

    if "--density" in sys.argv:
        # VSL is a COMPRESSED notation. Prose in a spec is undetected by every
        # other axis: it parses, it closes, it encodes clean -- and it says in
        # a paragraph what notation says in a line. Thresholds calibrated
        # against boot/, which runs at 4.2 words/line and 0% prose.
        # THIRD AXIS, added 2026-08-08: COMMENT SHARE.
        # The two axes above measure LINE SHAPE, and a narrative wrapped at 70
        # columns has the shape of dense notation: short lines, few words each.
        # seven_ideas_deep is 659 comment lines and 3 code lines -- a 736-line
        # essay -- and scored 3% prose, 4.4 w/l, INSIDE both targets. It was
        # never flagged because wrapping is what both axes reward.
        # The corpus splits cleanly on this axis and on nothing else: four
        # documents sit at 98-99% comment, every other one at ≤35%. Nothing
        # in between. That gap is a document CLASS, ¬a threshold to tune.
        PROSE = re.compile(r"\b[a-z]{2,}\b")
        OPS = re.compile(r"[⟹⟺∈∉∀∃≤≥⊆⊂∧∨¬←→↑↓·⊕Ω∅≡σφψτλ]")
        NARRATIVE = 60.0          # comment share above which a doc is an essay
        rows = []
        for f in sorted(CORPUS.rglob("*.vsm")):
            if any(s in f.parts for s in SKIP_DIRS):
                continue
            lines = [l for l in f.read_text(encoding="utf-8").splitlines()
                     if l.strip()]
            if not lines:
                continue
            prose = sum(1 for l in lines
                        if len(PROSE.findall(l)) >= 12 and not OPS.search(l))
            cmt = sum(1 for l in lines if l.lstrip().startswith("//"))
            # ORPHAN LINES — the axis that makes words/line ungameable.
            # w/l falls if you split a sentence, so a document can hit the
            # target by breaking prose at arbitrary points. s4_anticipation
            # was reflowed 907 → 1459 lines to reach ≤5.0 and arrived
            # carrying 91 lines of ≤2 words, with `// ─── N. TITLE ───`
            # headers split MID-PHRASE across two lines. The metric was
            # satisfied and the document was harder to read than before.
            # Rejoining them left it at 1305 lines and 4.52 w/l — still
            # inside target, which proves the splitting bought nothing.
            # The rubric already says each line must be "readable alone";
            # a line containing only the word `kernel` is not.
            orphan = sum(1 for l in lines
                         if 0 < len(PROSE.findall(l)) <= 2
                         and not any(c in l for c in "⟦⟧{}[]:,\"")
                         and not l.lstrip().startswith("// ─"))
            words = sum(len(PROSE.findall(l)) for l in lines)
            rows.append((str(f.relative_to(CORPUS)), len(lines), prose,
                         100 * prose / len(lines), words / len(lines),
                         100 * cmt / len(lines),
                         100 * orphan / len(lines)))
        # ORPHAN SHARE IS REPORTED, ¬GATED — and this is settled, ¬deferred.
        # THREE discriminators were built and measured across the corpus:
        #   v1  ≤2 words                      → boot/hard_rules 9%, reg_layer 8%
        #   v2  ≤2 words ∧ ∄ notation glyph   → covenant 12%, s5_algedonic 10%
        #   v3  ≤2 words ∧ line OPENS inside
        #       an unterminated string        → core_boot_primer 8.4% (highest)
        # ALL THREE put the CALIBRATION BASELINE at or near the top. That is
        # not a threshold to tune — it is the signal not being there.
        # In VSL a quoted block holds prose AND notation indifferently, and a
        # short line is legitimate in both. Telling "tail of a broken sentence"
        # apart from "dense notation line" requires knowing whether the line
        # CONTINUES A SENTENCE, which is a language question, ¬a structural
        # one — and answering it with a model is barred here by R10.
        # (Quote parity, v3's signal, DOES solve a different problem exactly:
        # see the definition/citation note above. Same signal, one question it
        # answers and one it cannot.)
        # So this stays an OBSERVATION beside the targets. It earned its keep
        # once, by eye: s4_anticipation had been reflowed 907 → 1459 lines to
        # reach w/l ≤ 5.0 and arrived with 91 fragments and five section
        # headers split MID-PHRASE. Rejoining left it at 1303 lines and 4.53
        # w/l — still inside target, so the splitting had bought nothing.
        # Reviewers read this column. Gates do ¬.
        ORPHAN_MAX = 4.0        # % of lines carrying ≤2 words — ADVISORY
        bad = [r for r in rows if r[3] > 5.0 or r[4] > 5.0]
        essay = [r for r in rows if r[5] > NARRATIVE]
        print(f"  target: prose ≤ 5% · words/line ≤ 5.0   (boot/ = 0% · 4.2)"
              f"\n  orphan share (≤2-word lines) is REPORTED, ¬gated — see the "
              f"note in --density")
        print(f"  over target: {len(bad)} of {len(rows)}\n")
        for n, ln, pr, pc, wl, cs, orf in sorted(bad, key=lambda x: -x[3]):
            flag = "  ◐ orphan-split?" if orf > ORPHAN_MAX else ""
            print(f"    {n:<42}{ln:>5} lines{pc:>5.0f}% prose"
                  f"{wl:>7.1f} w/l{cs:>5.0f}% cmt{orf:>5.0f}% orph{flag}")
        if essay:
            print(f"\n  NARRATIVE class — >{NARRATIVE:.0f}% comment, "
                  f"{len(essay)} of {len(rows)}. Both axes above are blind "
                  f"here:")
            for n, ln, pr, pc, wl, cs, orf in sorted(essay, key=lambda x: -x[5]):
                print(f"    {n:<42}{ln:>5} lines{pc:>5.0f}%{wl:>7.1f} w/l"
                      f"{cs:>5.0f}% cmt")
        return 1 if bad else 0

    if "--d7" in sys.argv:
        offenders = {}
        scanned = 0
        for f in sorted(CORPUS.rglob("*.vsm")):
            if any(s in f.parts for s in SKIP_DIRS) or f.name in D7_EXEMPT:
                continue
            scanned += 1
            hits = []
            for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                w = {x.lower() for x in WORD.findall(ln)}
                found = w & SPANISH
                acc = {x.lower() for x in ACCENTED.findall(ln)} - ACCENT_OK
                strong = w & SPANISH_STRONG
                if len(found) >= 2 or acc or strong:
                    mark = sorted(found | strong)[:2] + sorted(acc)[:2]
                    hits.append((i, mark, ln.strip()[:62]))
            if hits:
                offenders[str(f.relative_to(CORPUS))] = hits
        if scanned == 0:
            # D-07 guard: an empty/missing corpus used to print "0 in 0" and
            # exit 0 — a false clean. Refuse instead.
            print(f"  D7 — corpus empty: {CORPUS} (0 documents scanned)")
            print("  refusing to report clean on no corpus (D-07 guard)")
            return 2
        n = sum(len(v) for v in offenders.values())
        print(f"  D7 — non-English lines: {n} in {len(offenders)} documents")
        print(f"  exempt (bilingual by ratified design): "
              f"{', '.join(sorted(D7_EXEMPT))}\n")
        for d, hits in sorted(offenders.items(), key=lambda x: -len(x[1])):
            print(f"    {d:<44}{len(hits):>4} lines")
            for i, w, ctx in hits[:2]:
                print(f"        {i:>5}  [{','.join(w)}]  {ctx}")
        return 1 if offenders else 0

    if "--paths" in sys.argv:
        sysdir = CORPUS
        idx = Index()
        for f in sorted(CORPUS.rglob("*.vsm")):
            if not any(s in f.parts for s in SKIP_DIRS):
                idx.add_file(f)
        inst = (sysdir / "instance/instance.vsm").read_text(encoding="utf-8")
        bound = dict(BINDING.findall(inst))
        body, offenders = "", {}
        for f in sorted(sysdir.rglob("*.vsm")):
            if f.name == "instance.vsm":
                continue
            txt = f.read_text(encoding="utf-8")
            body += txt          # binding USAGE counts comments — a @var named
                                 # in a comment is still named. Reading code
                                 # here left 110 bindings looking orphaned.
            # The PATH check needs COMMENTS OUT and STRINGS IN. Two wrong
            # answers on the way, in one sitting:
            #   raw   — every document opens with a comment naming its own
            #           path: 42 false positives of 48.
            #   code  — the tokenizer blanks string BODIES too, and in VSL a
            #           path lives inside a value. The negative test caught it:
            #           `y: "vault/triage/x.md"` went undetected.
            # So: drop whole-line comments, strip inline ones, keep the strings.
            code = "\n".join(strip_comment(l.raw)
                             for l in tokenize(f).lines if l.kind != "comment")
            hits = sorted({m.group(0) for m in EXPLICIT_PATH.finditer(code)}
                          | {m.group(0) for m in EXPLICIT_PATH_REL.finditer(code)}
                          - REGISTRY_NAME)
            if hits:
                offenders[str(f.relative_to(sysdir))] = hits
        # instance.vsm's own resolution.check claims BOTH directions are
        # verified. Only one ever was: this block computed `dangling` twice,
        # the second as `v not in bound and v in bound` -- a predicate that is
        # empty by construction -- and then printed neither. Half a rule,
        # green forever. Rewritten 2026-08-08.
        # `@src_*` is a GLOB over the binding namespace, ¬a reference to a
        # binding named `src_`. Excluded by the trailing-* guard.
        # `@param` is likewise a METAVARIABLE: hard_rules §R_param_resolution
        # writes `bind(@param) ∈ instance.vsm` to state the RULE, ¬to cite a
        # binding called `param`. Same class, same exclusion.
        refs = set(re.findall(r"@([a-z_][a-z_0-9]*)\b(?!\*)",
                              EMAIL.sub("", body)))
        dangling = sorted(refs - set(bound) - DIRECTIVE)
        orphan = sorted(v for v in bound
                        if f"@{v}" not in body
                        and BINDING_ALIAS.get(v, v) not in body)
        print(f"  documents with an explicit path: {len(offenders)}")
        for d, h in offenders.items():
            print(f"    {d:<42}{len(h)}  {h[0]}"
                  + (f" +{len(h)-1}" if len(h) > 1 else ""))
        # IDENTIFIERS cited and defined NOWHERE. A separate question from
        # @var bindings, and one ∄ gate asked until 2026-08-09 — it surfaced
        # by exporting the index to RDF and letting a graph engine ask it.
        # 29 answers on first run: 5 were the index reading a declaration
        # inside a quoted block as a continuation (fixed), 3 are broken
        # references, 21 are axioms the FUSES CITED AND NEVER ABSORBED.
        # Reported ∧ counted, ¬blocking: the 21 are a pass of real work
        # (debt CITED-AXIOMS-NOT-ABSORBED), and a gate that blocks on a
        # standing backlog gets switched off within a week.
        ident_dangling = sorted(i for i in idx.cited if i not in idx.defined)
        print(f"\n  bindings: {len(bound)} · dangling: {dangling or '—'}"
              f" · orphan: {orphan or '—'}")
        print(f"  identifiers cited ∧ defined NOWHERE: {len(ident_dangling)}")
        if ident_dangling:
            print(f"    {' '.join(ident_dangling[:6])}"
                  + (f" … +{len(ident_dangling)-6}" if len(ident_dangling) > 6
                     else ""))
        return 1 if offenders or orphan or dangling else 0

    if "--undeclared" in sys.argv:
        und = idx.undeclared()
        print(f"  glyphs used but declared NOWHERE: {len(und)}")
        for g, docs in sorted(und.items()):
            print(f"    {g}  U+{ord(g):04X}  {unicodedata.name(g,'?')[:30]:<30}"
                  f"{len(docs)} docs")
        foreign = idx.foreign
        if foreign:
            nf = sum(len(v) for v in foreign.values())
            print(f"\n  ✗ NON-LATIN SCRIPT: {len(foreign)} distinct, "
                  f"{nf} occurrences — BLOCKING")
            print("    Homoglyph risk: Cyrillic а and Latin a are the same "  # foreign-script-allow: homoglyph illustration
                  "pixels.\n    A spec carrying one has an identifier that "
                  "silently does not match.")
            for g, hits in sorted(foreign.items()):
                print(f"    {g}  U+{ord(g):04X}  "
                      f"{unicodedata.name(g,'?')[:34]:<34}")
                for rel, ln, ctx in hits[:3]:
                    print(f"         {rel}:{ln}  …{ctx}")
        dia = idx.diacritic
        n = sum(len(v) for v in dia.values())
        print(f"\n  Latin letters with a diacritic: {len(dia)} distinct, "
              f"{n} occurrences")
        print("    each is EITHER notation needing a declaration (the alphabet"
              " declares x̂ = estimate)")
        print("    OR non-English prose (D7). Neither is allowed to pass"
              " unexamined.")
        # A diacritic BLOCKS only when it is neither declared notation nor
        # inside a D7-exempt document. Reporting is not blocking: the covenant
        # is bilingual by ratified design and x̄ / x̂ are the alphabet's own
        # mean/estimate marks. Blocking on those made the gate reject correct
        # content, which is the fastest way to get a gate switched off.
        blocking = {g: [h for h in hits
                        if Path(h[0]).name not in D7_EXEMPT
                        and g not in DECLARED_MARKS]
                    for g, hits in dia.items()}
        blocking = {g: h for g, h in blocking.items() if h}
        for g, hits in sorted(dia.items()):
            mark = "BLOCKING" if g in blocking else "ok"
            print(f"    {g}  U+{ord(g):04X}  "
                  f"{unicodedata.name(g,'?')[:32]:<34}{mark}")
            for rel, ln, ctx in (blocking.get(g) or hits)[:2]:
                print(f"         {rel}:{ln}  …{ctx[:62]}")
        return 1 if (und or blocking or idx.foreign) else 0

    print(f"  documents  : {len(idx.docs)}")
    print(f"  identifiers: {len(idx.defined)} defined · {len(idx.cited)} cited")
    print(f"  glyphs     : {len(idx.glyph_declared)} declared · "
          f"{len(idx.glyph_used)} used")
    print(f"  duplicates : {len(idx.duplicates())}   (--dupes)")
    print(f"  undeclared : {len(idx.undeclared())}   (--undeclared)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

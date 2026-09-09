#!/usr/bin/env python3
"""envelope.py — VSL inter-agent envelope (Phase 1: formality + compression).

An envelope is the formal unit of agent-to-agent communication. It replaces
free-text tmux messages with a typed structure that states, formally:
  WHO -> WHO, at what LEVEL, of what TYPE, referencing what canonical detail.

Compression is the point as much as formality: the envelope carries INTENT plus
a `ref:` pointer to the canonical detail (a queue item, a spec), not the full
instruction. A 40-line tmux message collapses to ~6 lines. (bbh-wsl's .vsm form
already measured -83% tokens against the .md it replaced.)

Grammar (Phase 1):

    φ(<from_id>@<from_level> -> <to_id>@<to_level>, <msg_type>) {
      ref:  <token>          # pointer to canonical detail (q13, a spec id, ...)
      <key>: <value>         # body lines; free keys (act/gate/stop/result/...)
      ...
    }

  msg_type ∈ {directive, report, query, ack}
  level    ∈ {S1..S5, L0..L9}   (declared identity — NOT cryptographic in Phase 1)

Phase 2 will add a `sig:` field over the canonical serialization; this parser
already tolerates and round-trips an opaque `sig:` line so the format is
forward-compatible (envelope bytes do not change when the signature arrives).

Deterministic, stdlib-only. No LLM in this path (R10). `envelope.py selftest`.
"""
from __future__ import annotations
import re
import sys
import pathlib

# Protocol version. Bump on any change to the envelope grammar or origin rules.
# A distributed copy is STALE if its PROTOCOL_VERSION < canon's. This turns the
# copy-drift I created 2026-07-24 (three copies, two versions, silently) into a
# detectable diff: `envelope.py version` prints it; a dependent compares against
# what VSF publishes down φ↓. Minimum viable step toward a real update channel —
# see docs/spec/signed_vsl_envelope.spec.vsm §update_channel.
PROTOCOL_VERSION = 2   # v1: base grammar. v2: + origin() convention.

MSG_TYPES = {"directive", "report", "query", "ack"}
_LEVEL_RE = re.compile(r"^(S[1-5]|L[0-9])$")
_HEADER_RE = re.compile(
    r"^\s*(?:\u03c6|phi)\s*\(\s*"
    r"(?P<from_id>\[[^\]]+\]|[A-Za-z0-9_\-]+)@(?P<from_level>\S+?)\s*(?:->|\u2192)\s*"
    r"(?P<to_id>\[[^\]]+\]|[A-Za-z0-9_\-]+)@(?P<to_level>\S+?)\s*,\s*"
    r"(?P<msg_type>\w+)\s*\)\s*\{"
)
# Widened 2026-08-10 to the form the canon itself writes: \u03c6 and \u2192, not only
# ASCII phi/->. The two real cross-provider exchanges on file (Qwen, Kimi,
# 2026-08-04) use the Unicode form, and this parser rejected them — it was
# narrower than the spec it enforces (R9: align, never concede silently).
# Bracketed ids keep their brackets, as before; bare ids are also accepted
# because the primer's own grammar line is written without them.

_TEMPLATE_IDS = {"from_id", "to_id", "from", "to", "a", "b", "sender", "receiver"}

# mistaken for messages: a template is a specification, not an exchange.

class EnvelopeError(ValueError):
    pass


class Envelope:
    __slots__ = ("from_id", "from_level", "to_id", "to_level",
                 "msg_type", "ref", "body", "sig")

    def __init__(self, from_id, from_level, to_id, to_level, msg_type,
                 ref=None, body=None, sig=None):
        self.from_id = from_id
        self.from_level = from_level
        self.to_id = to_id
        self.to_level = to_level
        self.msg_type = msg_type
        self.ref = ref
        self.body = body or {}          # ordered dict of str->str
        self.sig = sig                  # opaque, Phase 2; round-tripped if present

    def validate(self) -> "Envelope":
        if self.msg_type not in MSG_TYPES:
            raise EnvelopeError(
                f"msg_type '{self.msg_type}' not in {sorted(MSG_TYPES)}")
        for who, lvl in (("from", self.from_level), ("to", self.to_level)):
            if not _LEVEL_RE.match(lvl):
                raise EnvelopeError(f"{who}_level '{lvl}' is not S1-S5 or L0-L9")
        # A directive that tells someone to DO something should point at the
        # canonical detail rather than inline it — that is the compression contract.
        if self.msg_type == "directive" and not self.ref:
            raise EnvelopeError("directive must carry a ref: to canonical detail")
        return self

    def render(self) -> str:
        head = (f"φ({self.from_id}@{self.from_level} -> "
                f"{self.to_id}@{self.to_level}, {self.msg_type}) {{")
        lines = [head]
        if self.ref is not None:
            lines.append(f"  ref:  {self.ref}")
        for k, v in self.body.items():
            lines.append(f"  {k}: {v}")
        if self.sig is not None:
            lines.append(f"  sig:  {self.sig}")
        lines.append("}")
        return "\n".join(lines)


def parse(text: str) -> Envelope:
    lines = [ln for ln in text.strip().splitlines()]
    if not lines:
        raise EnvelopeError("empty envelope")
    m = _HEADER_RE.match(lines[0])
    if not m:
        raise EnvelopeError(f"bad header: {lines[0]!r}")
    from_id, from_level, to_id, to_level, msg_type = m.groups()
    ref = None
    sig = None
    body = {}
    # Continuation lines: the documented format (vsl_communication_protocol
    # message_shape, and every real dispatch since 2026-08-03) wraps long
    # values across lines. This parser used to abort on the second line with
    # "body line without key", which made it reject the entire corpus it was
    # written to validate — 0 of 19 phi blocks in the repo parsed. Widened to
    # the format the canon actually documents, per R9: align, do not concede
    # silently. A continuation is an indented line whose first token is not a
    # `key:`; it appends to the value opened above it.
    _last = None
    for ln in lines[1:]:
        s = ln.strip()
        if s in ("}", ""):
            continue
        m_kv = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$', s)
        if not m_kv:
            if _last is None:
                raise EnvelopeError(f"body line without key: {s!r}")
            if _last == "ref":
                ref = (ref + " " + s).strip()
            elif _last == "sig":
                sig = (sig + " " + s).strip()
            else:
                body[_last] = (body[_last] + " " + s).strip()
            continue
        k, v = m_kv.group(1), m_kv.group(2)
        _last = k
        if k == "ref":
            ref = v
        elif k == "sig":
            sig = v
        else:
            body[k] = v
    return Envelope(from_id, from_level, to_id, to_level, msg_type,
                    ref=ref, body=body, sig=sig).validate()


_ENVELOPE_INTENT = re.compile(r"^\s*(?:φ|phi)\s*\(")


def origin(text: str):
    """Classify WHO a message is from, per the Phase-1 identity convention.

    Agents MUST wrap messages in envelopes; the human (rmw3 @S5) does not — so
    the ABSENCE of a formal envelope IS the human's identity, with no signature
    required. Note the inversion: unwrapped plaintext is the HIGHEST authority
    (rmw3 is S5), not the lowest.

      - a valid envelope           -> ("agent", from_id)
      - plaintext, no envelope form -> ("human", None)   # = rmw3 @S5
      - an envelope ATTEMPT (starts with φ/phi() that fails to parse
                                    -> raises EnvelopeError

    That last case is load-bearing: a malformed or forged agent envelope must
    NOT be silently attributed to the human, or a broken agent message could
    borrow S5 authority through the back door. A broken envelope is an error to
    query back on, never a human instruction.
    """
    if _ENVELOPE_INTENT.match(text):
        return ("agent", parse(text).from_id)   # malformed -> EnvelopeError
    return ("human", None)


def selftest() -> int:
    fail = 0

    def check(name, cond):
        nonlocal fail
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")
        if not cond:
            fail = 1

    # round-trip a real directive
    src = ("φ([O]@S5 -> [S]@S1, directive) {\n"
           "  ref:  q13\n"
           "  act: build+deploy 5ba7834 -> nucleus\n"
           "  gate: diff 108/src vs HEAD; R4; record deploy\n"
           "  stop: step 5, verify live\n"
           "}")
    e = parse(src)
    check("parse from_id", e.from_id == "[O]")
    check("parse levels", e.from_level == "S5" and e.to_level == "S1")
    check("parse type", e.msg_type == "directive")
    check("parse ref", e.ref == "q13")
    check("parse body", e.body.get("act", "").startswith("build+deploy"))
    check("render round-trips", parse(e.render()).body == e.body)

    # forward-compat: a Phase-2 sig line survives round-trip untouched
    signed = src[:-1] + '  sig:  ed25519:deadbeef\n}'
    es = parse(signed)
    check("sig round-trips", parse(es.render()).sig == "ed25519:deadbeef")

    # rejections
    def rejects(name, txt):
        try:
            parse(txt); check(name, False)
        except EnvelopeError:
            check(name, True)

    rejects("reject bad level",
            "φ([O]@S9 -> [S]@S1, directive) {\n  ref: x\n}")
    rejects("reject bad type",
            "φ([O]@S5 -> [S]@S1, shout) {\n  ref: x\n}")
    rejects("reject directive without ref",
            "φ([O]@S5 -> [S]@S1, directive) {\n  act: go\n}")
    # a report needs no ref
    try:
        parse("φ([S]@S1 -> [O]@S5, report) {\n  result: q13 deployed\n}")
        check("report without ref ok", True)
    except EnvelopeError:
        check("report without ref ok", False)

    # origin convention: plaintext = human (S5), valid envelope = agent,
    # broken envelope attempt = error (must NOT pass as human)
    check("origin: envelope -> agent", origin(src) == ("agent", "[O]"))
    check("origin: plaintext -> human", origin("just do the deploy") == ("human", None))
    check("origin: human is S5-authority (None id, not an agent)",
          origin("dale, seguí")[0] == "human")
    try:
        origin("φ([O]@S5 -> broken")
        check("origin: broken envelope rejected (not human)", False)
    except EnvelopeError:
        check("origin: broken envelope rejected (not human)", True)

    print("  == PASS ==" if not fail else "  == FAIL ==")
    return fail


def check_file(path: str) -> int:
    """Validate the phi() envelope inside a .vsm file. Used by the pre-commit
    gate — R15 says formal cross-agent exchange IS VSL, and until 2026-08-10
    nothing enforced it: 0 of 19 phi blocks in the repo parsed, and no module
    imported this one. A rule with no gate is a decoration."""
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^\s*(?:φ|phi)\s*\([^)\n]*\)\s*\{", text, re.M)
    if not m:
        return 0                      # no envelope in this file: nothing to check
    head = text[m.start():].lstrip().splitlines()[0]
    hm = _HEADER_RE.match(head)
    _bare = lambda x: x.strip("[]")
    if hm and (_bare(hm.group("from_id")) in _TEMPLATE_IDS
               or _bare(hm.group("to_id")) in _TEMPLATE_IDS
               or hm.group("msg_type") == "msg_type"):
        return 0                      # grammar template, not an exchange
    try:
        parse(text[m.start():])
        return 0
    except EnvelopeError as e:
        print(f"  {path}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "check":
        raise SystemExit(max(check_file(a) for a in sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "version":
        print(PROTOCOL_VERSION)
        sys.exit(0)
    # else: parse stdin, re-render canonically (a linter for hand-written envelopes)
    try:
        print(parse(sys.stdin.read()).render())
    except EnvelopeError as ex:
        print(f"envelope error: {ex}", file=sys.stderr)
        sys.exit(1)

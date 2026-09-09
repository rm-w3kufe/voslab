#!/usr/bin/env python3
"""
VSL interpreter — VSL v2.0 (task U), deterministic core.

Closes the S4->S1 self-execution loop in three deterministic stages (steps 1-3 of
task U; step 4 — Qwen proposes next_experiment.vsm — is gated on task(S), Qwen-native).

Pipeline:  spec.vsm  --plan-->  execution plan (commands it WOULD run; never executes here)
           metrics.json + spec  --eval-->  per-hypothesis pass/fail  -->  report.vsm

A spec keeps its human `hypotheses { H1: "prose" ... }` block unchanged. The interpreter
reads an OPTIONAL machine-evaluable `evaluation { Hn: <metric> <op> <args> }` block that
sits alongside it — so every existing corpus spec stays valid VSL v1.0, and a spec opts in
to automatic evaluation by adding predicates. Hypotheses with no predicate are reported as
MANUAL (honest: prose-only claims are not auto-judged, never silently passed).

Predicate grammar (one per line inside `evaluation { }`):
    Hn: <metric> >=|<=|>|<|==|!= <value>
    Hn: <metric> between <lo> <hi>          # inclusive
    Hn: defined <metric>                      # metric present in metrics.json
  <value> ::= number | true | false | "string"
  <metric> is a key looked up in the metrics JSON (e.g. the nucleus final_report).

Safety (RULES + covenant A0/A5 + feedback_wsl_role_only):
  - `plan`  is read-only and the default.
  - `eval`  is read-only (reads a metrics file produced elsewhere) and emits a report.
  - `run`   would DEPLOY+LAUNCH on the cluster — it is GATED. This tool refuses to do that:
            deployment goes through the canonical deploy path, never autonomously from here.
  - `propose` (step 4) calls Qwen via SSH → pct exec → curl (task(S) complete).
    Requires SSH access to n02; writes proposed next_experiment.vsm to --out or stdout.

Usage:
    python3 scripts/vsl/vsl_run.py plan   SPEC.vsm
    python3 scripts/vsl/vsl_run.py eval   SPEC.vsm --metrics M.json [--report OUT.vsm] [--index]
    python3 scripts/vsl/vsl_run.py run    SPEC.vsm              # gated -> refuses (exit 3)
    python3 scripts/vsl/vsl_run.py propose REPORT.vsm [--out next_experiment.vsm]

Exit codes: 0=ok/all-pass  1=eval has FAIL  2=parse/usage error  3=gated (refused)
"""

import sys, os, re, json, datetime, subprocess

# Reuse the VSL v1.0 reference parser as the validation front-end (no duplication).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vsl_parser   # noqa: E402
import s4_store     # noqa: E402  RAG store: FTS5 retrieval for EP + eval indexing (rag-nucleus.db)
import qwen_client  # noqa: E402  shared hardened Qwen transport (probe+cooldown+lock+self-alerts)

# ── Block + predicate extraction ───────────────────────────────────────────────

RE_HYPO_LINE = re.compile(r'^\s*(H[\w]*)\s*[:=]\s*(.*)$')


def _strip_line_comment(line: str) -> str:
    """Remove a // comment to end-of-line, ignoring // inside double-quoted strings."""
    in_str = False
    for k in range(len(line) - 1):
        if line[k] == '"':
            in_str = not in_str
        elif not in_str and line[k] == '/' and line[k + 1] == '/':
            return line[:k]
    return line


def _decomment(text: str) -> str:
    """Strip // comments line by line so block scans never match commented examples."""
    return "\n".join(_strip_line_comment(ln) for ln in text.splitlines())


def _extract_block(text: str, name: str) -> str | None:
    """Return the brace-balanced body of `name { ... }` (or `name: { ... }`), else None."""
    m = re.search(rf'\b{re.escape(name)}\s*[:=]?\s*\{{', text)
    if not m:
        return None
    i = m.end() - 1  # at the opening brace
    depth, start = 0, i
    in_str = False
    while i < len(text):
        c = text[i]
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[start + 1:i]
        i += 1
    return None  # unbalanced -> treated as absent


def _coerce(tok: str):
    """number | bool | quoted-string | bare-string."""
    tok = tok.strip()
    if tok.lower() == 'true':
        return True
    if tok.lower() == 'false':
        return False
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1]
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        return tok  # bare string (enum-like)


def parse_predicate(label: str, expr: str) -> dict:
    """Parse one `evaluation` line into a predicate dict (or an 'invalid' marker)."""
    toks = expr.split()
    if len(toks) >= 2 and toks[0] == 'defined':
        return {'label': label, 'op': 'defined', 'metric': toks[1], 'raw': expr}
    if len(toks) == 4 and toks[1] == 'between':
        return {'label': label, 'op': 'between', 'metric': toks[0],
                'lo': _coerce(toks[2]), 'hi': _coerce(toks[3]), 'raw': expr}
    if len(toks) >= 3 and toks[1] in ('>=', '<=', '>', '<', '==', '!='):
        return {'label': label, 'op': toks[1], 'metric': toks[0],
                'value': _coerce(' '.join(toks[2:])), 'raw': expr}
    return {'label': label, 'op': None, 'raw': expr,
            'error': f"unrecognized predicate: {expr!r}"}


def load_spec(path: str) -> dict:
    """Validate via vsl_parser, then extract hypotheses + evaluation predicates + protocol."""
    pr = vsl_parser.parse_file(path)
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    text = _decomment(raw)  # block scans must ignore commented `hypotheses { }` examples

    hypotheses, predicates = {}, {}
    hb = _extract_block(text, 'hypotheses')
    if hb:
        for line in hb.splitlines():
            m = RE_HYPO_LINE.match(line)
            if m and m.group(2).strip():
                hypotheses[m.group(1)] = m.group(2).strip().strip('"')
    eb = _extract_block(text, 'evaluation')
    if eb:
        for line in eb.splitlines():
            m = RE_HYPO_LINE.match(line)
            if m and m.group(2).strip():
                predicates[m.group(1)] = parse_predicate(m.group(1), m.group(2).strip())

    # protocol: collect cmd = "..." occurrences (phases) for the plan view
    pb = _extract_block(text, 'protocol') or ''
    cmds = re.findall(r'cmd\s*=\s*"([^"]*(?:\\\n[^"]*)*)"', pb)
    binary = (re.search(r'binary\s*=\s*"([^"]*)"', pb) or [None, None])[1] \
        if re.search(r'binary\s*=\s*"([^"]*)"', pb) else None
    deploy = (re.search(r'deploy\s*=\s*"([^"]*)"', pb) or [None, None])[1] \
        if re.search(r'deploy\s*=\s*"([^"]*)"', pb) else None

    return {
        'path': path,
        'valid': pr.valid,
        'errors': pr.errors,
        'warnings': pr.warnings,
        'exp_id': pr.ast.get('exp_id') or pr.ast.get('id') or os.path.basename(os.path.dirname(path)),
        'domain_context': pr.ast.get('domain_context', {}),
        'hypotheses': hypotheses,
        'predicates': predicates,
        'protocol': {'binary': binary, 'deploy': deploy, 'cmds': cmds},
    }


# ── Evaluator ──────────────────────────────────────────────────────────────────

def _cmp(op, a, b):
    return {'>=': a >= b, '<=': a <= b, '>': a > b, '<': a < b,
            '==': a == b, '!=': a != b}[op]


def evaluate(spec: dict, metrics: dict) -> list:
    """Evaluate each hypothesis. Returns a list of result dicts (PASS/FAIL/MANUAL/ERROR)."""
    results = []
    labels = list(dict.fromkeys(list(spec['hypotheses']) + list(spec['predicates'])))
    for label in labels:
        prose = spec['hypotheses'].get(label, '')
        pred = spec['predicates'].get(label)
        if pred is None:
            results.append({'label': label, 'status': 'MANUAL', 'prose': prose,
                            'detail': 'no machine predicate — manual review required'})
            continue
        if pred.get('op') is None:
            results.append({'label': label, 'status': 'ERROR', 'prose': prose,
                            'detail': pred.get('error', 'invalid predicate')})
            continue
        metric = pred['metric']
        present = metric in metrics
        if pred['op'] == 'defined':
            ok = present
            detail = f"{metric} {'present' if present else 'ABSENT'}"
        elif not present:
            ok = False
            detail = f"{metric} ABSENT in metrics"
        else:
            actual = metrics[metric]
            try:
                if pred['op'] == 'between':
                    ok = pred['lo'] <= actual <= pred['hi']
                    detail = f"{metric}={actual} in [{pred['lo']},{pred['hi']}]"
                else:
                    ok = _cmp(pred['op'], actual, pred['value'])
                    detail = f"{metric}={actual} {pred['op']} {pred['value']}"
            except TypeError as e:
                results.append({'label': label, 'status': 'ERROR', 'prose': prose,
                                'detail': f"type mismatch evaluating {pred['raw']}: {e}"})
                continue
        results.append({'label': label, 'status': 'PASS' if ok else 'FAIL',
                        'prose': prose, 'detail': detail})
    return results


def verdict(results: list) -> str:
    statuses = {r['status'] for r in results}
    if 'FAIL' in statuses or 'ERROR' in statuses:
        return 'FAIL'
    if statuses <= {'MANUAL'}:
        return 'INCONCLUSIVE'  # nothing auto-judged
    if 'MANUAL' in statuses:
        return 'PARTIAL'        # auto part passed, prose remains
    return 'PASS'


# ── Report emitter (valid VSL v1.0) ────────────────────────────────────────────

def emit_report(spec: dict, metrics_path: str, results: list) -> str:
    dc = spec['domain_context']
    dctx = (f"{{target={dc.get('target', 'vsf')}, env=VSF-session, "
            f"layer={dc.get('layer', 'S3')}}}")
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    v = verdict(results)
    lines = [
        "@vsm 1.2.1",
        f"// domain_context: {dctx}",
        f"// VSL v2.0 interpreter report — generated by scripts/vsl/vsl_run.py",
        "",
        f'report("{spec["exp_id"]}") {{',
        f'  spec           = "{spec["path"]}"',
        f'  metrics_source = "{metrics_path}"',
        f'  generated      = "{now}"',
        f'  verdict        = {v}',
        "",
        "  results {",
    ]
    for r in results:
        prose = r['prose'].replace('\n', ' ').strip()
        lines.append(f'    {r["label"]}: {r["status"]:6s} // {r["detail"]}'
                     + (f'  | {prose}' if prose else ''))
    lines.append("  }")
    manual = [r for r in results if r['status'] == 'MANUAL']
    if manual:
        lines += ["", "  manual_review: ["]
        for r in manual:
            lines.append(f'    "{r["label"]}: {r["prose"][:90]}",')
        lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


# ── CLI ────────────────────────────────────────────────────────────────────────

def cmd_plan(spec_path: str) -> int:
    spec = load_spec(spec_path)
    print(f"PLAN — {spec['exp_id']}   ({spec_path})")
    print(f"  VSL v1.0 valid: {spec['valid']}  ({len(spec['errors'])} err, "
          f"{len(spec['warnings'])} warn)")
    for e in spec['errors']:
        print(f"    {e}")
    p = spec['protocol']
    print(f"  binary: {p['binary']}")
    print(f"  deploy: {p['deploy']}")
    print(f"  commands it WOULD run ({len(p['cmds'])}) — NOT executed here:")
    for c in p['cmds']:
        print(f"    $ {' '.join(c.split())}")
    print(f"  hypotheses: {len(spec['hypotheses'])}  | machine predicates: "
          f"{len(spec['predicates'])}")
    for label in spec['hypotheses']:
        pred = spec['predicates'].get(label)
        tag = f"[{pred['raw']}]" if pred else "[prose-only -> MANUAL]"
        print(f"    {label}: {tag}")
    print("\n  run is GATED (A0/A5 + WSL): deploy/launch via the canonical path, not here.")
    return 0 if spec['valid'] else 2


def cmd_eval(spec_path: str, metrics_path: str, report_path: str | None,
             do_index: bool = False) -> int:
    spec = load_spec(spec_path)
    if not spec['valid']:
        print(f"SPEC INVALID — refusing to evaluate:\n  " + "\n  ".join(spec['errors']))
        return 2
    with open(metrics_path, encoding='utf-8') as f:
        metrics = json.load(f)
    # allow nesting: if there is a top-level final_report, merge it up
    if isinstance(metrics.get('final_report'), dict):
        metrics = {**metrics, **metrics['final_report']}
    results = evaluate(spec, metrics)
    v = verdict(results)
    print(f"EVAL — {spec['exp_id']}   verdict={v}")
    for r in results:
        print(f"  {r['label']}: {r['status']:6s}  {r['detail']}")
    if report_path:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(emit_report(spec, metrics_path, results))
        print(f"  report -> {report_path}")
        if do_index:
            s4_store.index(spec_path, report_path, store='nucleus')
    elif do_index:
        print("  --index requires --report (no report written, skipping CRAG index)")
    return 0 if v in ('PASS', 'PARTIAL', 'INCONCLUSIVE') else 1


def cmd_run(spec_path: str) -> int:
    print("REFUSED (gated). `run` would DEPLOY a binary and LAUNCH it on the cluster.")
    print("  - covenant A0/A5: no autonomous double-loop execution without human approval.")
    print("  - feedback_wsl_role_only: builds/deploys never originate from WSL.")
    print("  Deploy through the canonical deploy path, then use `eval` on captured metrics.")
    return 3


_PROPOSE_PRIMER = """\
VSL 1.0 format — write .vsm files exactly like this:

@vsm 1.2.1
exp("name") {
  id       = EXP-XX-NN
  status   = seed
  priority = high|medium|low
  question: prose
  hypotheses {
    H1: "prose claim"
    H2: "prose claim"
  }
  evaluation {
    H1: metric_key >= value
    H2: metric_key between lo hi
  }
  protocol {
    binary = "/path/to/binary"
    deploy = "shell command"
    phase_A: { cmd = "shell command" goal = "prose" }
  }
}

Rules: status=seed for new proposals. Evaluation operators: == != >= <= > < between lo hi defined.
Prose-only hypotheses (no predicate) get MANUAL verdict. metric_key comes from the final_report JSON.
"""


def _detect_domain(report_path: str, report_text: str) -> str:
    """Infer the S1 domain of a report for EP domain-first retrieval
    (S4-MULTI-S1 Phase 3). Checks the file path first, then content
    keywords. Defaults to 'nucleus' (the original single-store corpus).
    """
    path = (report_path or '').lower()
    text = (report_text or '').lower()

    # Path hints (strongest — experiment dirs are domain-named)
    if 'clima' in path or 's1-clima' in path:
        return 'clima'
    if 'econ' in path or 's1-econ' in path or 'll-01' in path:
        return 'econ'

    # Content hints
    if any(k in text for k in ('s1-clima', 's1_clima', 'clima', 'enso', 'oni',
                               'el_nino', 'excursion_zones', 'ensos')):
        return 'clima'
    if any(k in text for k in ('s1-econ', 's1_econ', 'economy', 'chile-economy',
                               'tatonnement', 'ta^tonnement', 'copper_force',
                               'excess_demand', 'stasis_cos')):
        return 'econ'

    return 'nucleus'


def cmd_propose(report_path: str, out_path: str | None = None) -> int:
    try:
        with open(report_path, encoding='utf-8') as f:
            report = f.read()
    except OSError as e:
        print(f"ERROR: cannot read {report_path}: {e}")
        return 2

    # EP (Enriched Propose): domain-first retrieval (S4-MULTI-S1 Phase 3) —
    # query rag-{domain}.db first (clima/econ bundle stores), fall back
    # cross-domain to rag-nucleus.db when k < 3. Empty string if no store
    # has entries yet — graceful degradation to base primer.
    domain = _detect_domain(report_path, report)
    retrieved_ctx = s4_store.context_for_prompt_domain_first(report, domain=domain, k=3)
    if retrieved_ctx:
        print(f"  EP: retrieved context from rag-{domain}.db (+ fallback, k≤3)")
    else:
        print("  CRAG: domain + nucleus corpus empty — using base primer only")

    instruction = (
        "Based on the experiment report below"
        + (" and the retrieved context above" if retrieved_ctx else "")
        + ", write the next experiment as a complete next_experiment.vsm file."
        + (" Use real metric names, binary paths, and protocol patterns from the "
           "retrieved context where applicable." if retrieved_ctx else "")
        + " Output ONLY valid VSL starting with @vsm 1.2.1 — no explanation, no markdown fences."
    )
    prompt = f"{_PROPOSE_PRIMER}\n{retrieved_ctx}{instruction}\n\n{report}"

    print(f"PROPOSE — {report_path} → Qwen ({qwen_client.MODEL}) ...")

    # Shared hardened transport (qwen_client): tri-state generate probe, restart
    # cooldown, qwen.lock serialisation, self-alerts on every failure path.
    raw = qwen_client.generate('ep', prompt, num_predict=300, temperature=0.2)
    if not raw:
        print("ERROR: Qwen call failed (self-alerted to s5-alerts.db)")
        return 2

    # Extract VSL content starting at @vsm header
    vsm_m = re.search(r'(@vsm\s+\d+\.\d+.*)', raw, re.DOTALL)
    vsm = vsm_m.group(1).rstrip() if vsm_m else raw

    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(vsm + '\n')
        print(f"  proposal -> {out_path}")
    else:
        print("\n" + vsm)
    return 0


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    try:
        if cmd == 'plan' and len(argv) == 3:
            return cmd_plan(argv[2])
        if cmd == 'eval' and len(argv) >= 5 and '--metrics' in argv:
            mp = argv[argv.index('--metrics') + 1]
            rp = argv[argv.index('--report') + 1] if '--report' in argv else None
            return cmd_eval(argv[2], mp, rp, do_index='--index' in argv)
        if cmd == 'run' and len(argv) == 3:
            return cmd_run(argv[2])
        if cmd == 'propose' and len(argv) >= 3:
            op = argv[argv.index('--out') + 1] if '--out' in argv else None
            return cmd_propose(argv[2], op)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: {e}")
        return 2
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""formaid — a general diagram studio (form + mermaid). Generate + visualise + deploy mermaid diagrams.

Re-aims the view-host from "one live RAG panel" to the general tool rmw3 asked for: a studio where a
diagram comes from (a) raw mermaid you write/edit, (b) a TEMPLATE you start from, or (c) a live GENERATOR
(state → mermaid; the cybernetic-rag loop + system-topology are now just generators, not the product).
You preview it live and EXPORT a standalone HTML to deploy on any web. No LLM yet (deterministic).

Registry kinds: template | generator | saved. Saved diagrams persist in DIAGRAMS_DIR as {id}.json.
Runs on the view-host LXC (109). Authoring WSL.
"""
import os
import re
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DIAGRAMS_DIR = os.environ.get("DIAGRAMS_DIR", "/root/view_host/diagrams")
EVENTS_PATH = os.environ.get("EVENTS_PATH", "/mnt/telemetry/events.jsonl")
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
_ID_RE = re.compile(r"[^a-z0-9_-]")

# ── spec → mermaid (the deterministic "spec mode") ───────────────────────────────────────────────
def spec_to_mermaid(spec):
    """A structured diagram spec → mermaid flowchart. spec = {direction, nodes:[{id,label,cls}],
    edges:[{from,to,kind,label}], classes:{cls: 'fill:..,stroke:..'}}."""
    out = [f"flowchart {spec.get('direction', 'LR')}"]
    for n in spec.get("nodes", []):
        nid = re.sub(_ID_RE, "_", str(n["id"]).lower()).upper() or "N"
        lab = str(n.get("label", n["id"])).replace('"', "")
        cls = f":::{n['cls']}" if n.get("cls") else ""
        out.append(f'  {nid}["{lab}"]{cls}')
    for e in spec.get("edges", []):
        a = re.sub(_ID_RE, "_", str(e["from"]).lower()).upper()
        b = re.sub(_ID_RE, "_", str(e["to"]).lower()).upper()
        arrow = "-.->" if e.get("kind") in ("feedback", "dotted", "aspirational") else "-->"
        lbl = f"|{e['label']}|" if e.get("label") else ""
        out.append(f"  {a} {arrow}{lbl} {b}")
    for cls, style in (spec.get("classes") or {}).items():
        out.append(f"classDef {cls} {style}")
    return "\n".join(out)


# ── live generators: system state → mermaid (the cybernetic-rag loop + the topology) ─────────────
_STATUS_CLS = {"healthy": "h", "degraded": "d", "critical": "c", "idle": "i"}
_LOOP_CLASSES = {
    "h": "fill:#16331b,stroke:#3fb950,color:#e6edf3,stroke-width:2px",
    "d": "fill:#3a2f10,stroke:#d29922,color:#e6edf3,stroke-width:2px",
    "c": "fill:#3a1518,stroke:#f85149,color:#e6edf3,stroke-width:2px",
    "i": "fill:#1c2128,stroke:#6e7681,color:#8b949e",
}


def _view_to_spec(view):
    nodes = []
    for n in view.get("nodes", []):
        lab = (n.get("label") or n["id"])
        impl = n.get("implemented")
        lab += " ◐" if impl == "partial" else (" ◌" if impl is False else "")
        nodes.append({"id": n["id"], "label": lab, "cls": _STATUS_CLS.get(n.get("status"), "i")})
    edges = [{"from": e["from"], "to": e["to"], "kind": e.get("kind"),
              "label": e.get("guard"),
              "_dotted": (e.get("kind") == "feedback" or e.get("state") == "aspirational")}
             for e in view.get("edges", [])]
    for e in edges:
        if e.pop("_dotted", False):
            e["kind"] = "dotted"
    return {"direction": "LR", "nodes": nodes, "edges": edges, "classes": _LOOP_CLASSES}


def _gen_cybernetic_rag():
    import cybernetic_rag_view as crv
    if os.path.exists(EVENTS_PATH):
        tick, _, _ = crv.build_tick_from_events(EVENTS_PATH)
    else:
        con = crv.synthetic_source_con()
        tick = {"view": crv.build_view(con)}
        con.close()
    return spec_to_mermaid(_view_to_spec(tick["view"]))


def _gen_system_topology():
    import system_topology_view as stv
    v = stv.build_tick()["view"]
    nodes = [{"id": f"l{x['id']}", "label": f"{x['id']} {x['role']}\\n{x.get('ip','')}", "cls": "box"}
             for x in v.get("lxcs", [])]
    cnodes = [{"id": f"c_{c['resource']}", "label": f"{c['resource']}\\n{c['kind']} · {c['status']}",
               "cls": ("on" if c["status"] == "active" else "off")} for c in v.get("couplings", [])]
    classes = {"box": "fill:#161b22,stroke:#30363d,color:#e6edf3",
               "on": "fill:#16331b,stroke:#3fb950,color:#e6edf3",
               "off": "fill:#1c2128,stroke:#6e7681,color:#8b949e"}
    return spec_to_mermaid({"direction": "TB", "nodes": nodes + cnodes, "edges": [], "classes": classes})


# Path for clima bundle (bind-mount from LXC 101, same pattern as EVENTS_PATH)
CLIMA_BUNDLE_PATH = os.environ.get("CLIMA_BUNDLE_PATH", "/mnt/telemetry/s4_clima_bundle.json")


def _gen_clima_topology():
    """Live generator: read s4_clima_bundle.json → mermaid diagram showing clima domain topology."""
    try:
        if not os.path.exists(CLIMA_BUNDLE_PATH):
            err = f"Clima bundle not found at {CLIMA_BUNDLE_PATH}"
            return f"flowchart LR\n  EMPTY[\"{err}\"]\n  style EMPTY fill:#3a1518,stroke:#f85149,color:#e6edf3"
        with open(CLIMA_BUNDLE_PATH) as f:
            cb = json.load(f)
    except Exception as e:
        return f"flowchart LR\n  ERR[\"Error reading clima bundle: {e}\"]\n  style ERR fill:#3a1518,stroke:#f85149,color:#e6edf3"

    bl = cb.get("baseline", {})
    g_stasis = bl.get("global_stasis_cos", "?")
    g_regime = bl.get("global_regime", "?")
    g_viab = bl.get("global_viability", "?")
    n_sys = bl.get("n_systems", 0)
    algedonic = cb.get("algedonic_status", "?")
    recv_count = cb.get("_recv_count", 0)

    # Build nodes per subsystem
    lines = ["flowchart TB"]
    lines.append(f"  GLOBAL[\"🌍 Global<br/>stasis={g_stasis}<br/>regime={g_regime}<br/>viability={g_viab}<br/>algedonic={algedonic}<br/>{recv_count} msgs\"]")

    subs = cb.get("events", [])
    for i, s in enumerate(subs):
        sid = s.get("system_id", f"sys_{i}").upper().replace("-", "_")
        scos = s.get("stasis_cos_sys", "N/A")
        smin = s.get("stasis_cos_min", "N/A")
        sreg = s.get("regime", "?")
        scoher = s.get("system_coherence", "?")
        svr = s.get("viability_ratio", "?")
        nz = s.get("n_zones", 0)
        nez = s.get("n_excursion_zones", 0)
        exc = f" ⚠️{nez} excursions" if nez and nez > 0 else ""
        lines.append(f"  {sid}[\"{sid}<br/>stasis={scos}<br/>regime={sreg}<br/>coherence={scoher}<br/>{nz} zones{exc}\"]")
        lines.append(f"  GLOBAL --> {sid}")

        # Style per regime
        if sreg == "quiescent":
            lines.append(f"  style {sid} fill:#16331b,stroke:#3fb950,color:#e6edf3")
        elif sreg in ("stressed", "excursion"):
            lines.append(f"  style {sid} fill:#3a1518,stroke:#f85149,color:#e6edf3")
        else:
            lines.append(f"  style {sid} fill:#3a2f10,stroke:#d29922,color:#e6edf3")

    # Show φ↑ pipeline status
    lines.append("  GLOBAL -.->|\"φ↑ vsf.clima.s4_context\"| NATS[\"NATS LXC 106\"]")
    lines.append("  NATS --> BRIDGE[\"s4_clima_bridge.py<br/>✅ {recv_count} msgs\"]")
    lines.append("  BRIDGE --> FILE[\"📄 s4_clima_bundle.json\"]")
    if n_sys == 0:
        lines.append("  FILE -.-> NUC[\"⚙️ Nucleus<br/>❌ no subscribe\"]")
        lines.append("  style NUC fill:#3a1518,stroke:#f85149,color:#e6edf3")
    else:
        lines.append("  FILE -.-> NUC[\"⚙️ Nucleus<br/>stasis=0.9998<br/>❌ interno\"]")
        lines.append("  style NUC fill:#3a2f10,stroke:#d29922,color:#e6edf3")

    # Style root
    gcls = "fill:#16331b" if g_regime == "quiescent" else ("fill:#3a1518" if g_regime in ("stressed", "excursion") else "fill:#3a2f10")
    lines.append(f"  style GLOBAL {gcls},stroke:#3fb950,color:#e6edf3")

    return "\n".join(lines)


# ── PNG export ────────────────────────────────────────────────────────────────────────────────────
MMDC_BIN = os.environ.get("MMDC_BIN", "")  # set to /usr/bin/mmdc or npx path if installed


def export_png(mermaid_source, out_path=None):
    """Render mermaid source → PNG file.

    Backends (tried in order):
      1. mmdc (local, best quality) — set MMDC_BIN env or install @mermaid-js/mermaid-cli
      2. Save .mmd source for manual rendering (always works as fallback)

    Returns dict: {ok: bool, path: str, note: str}
    """
    if out_path is None:
        out_path = os.path.join(DIAGRAMS_DIR, "_export.png")
    mmd_path = out_path.rsplit(".", 1)[0] + ".mmd"

    # Always save the .mmd source
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(mmd_path, "w", encoding="utf-8") as f:
        f.write(mermaid_source)

    # Try mmdc
    if MMDC_BIN:
        import subprocess
        try:
            r = subprocess.run(
                [MMDC_BIN, "-i", mmd_path, "-o", out_path, "-b", "#0d1117"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0 and os.path.exists(out_path):
                return {"ok": True, "path": out_path, "note": f"rendered via {MMDC_BIN}"}
            else:
                return {"ok": False, "path": mmd_path,
                        "note": f"mmdc failed (rc={r.returncode}): {r.stderr[:200]}"}
        except FileNotFoundError:
            pass  # mmdc not installed, fall through
        except Exception as e:
            return {"ok": False, "path": mmd_path, "note": f"mmdc error: {e}"}

    mmdc_hint = "npm install -g @mermaid-js/mermaid-cli"
    return {"ok": False, "path": mmd_path,
            "note": f".mmd saved. Install mmdc: {mmdc_hint}, then set MMDC_BIN env"}


GENERATORS = {
    "cybernetic-rag-loop": ("Cybernetic RAG loop (live)", _gen_cybernetic_rag),
    "system-topology": ("System topology (live)", _gen_system_topology),
    "clima-topology": ("S1-Clima domain topology (live from bundle)", _gen_clima_topology),
}

# ── templates (the "start from" catalog) ─────────────────────────────────────────────────────────
TEMPLATES = {
    "flowchart": ("Flowchart (basic)", "flowchart LR\n  A[Start] --> B{Decision}\n  B -->|yes| C[Do]\n  B -->|no| D[Skip]\n  C --> E[End]\n  D --> E"),
    "vsm-s1-s5": ("VSM S1–S5", "flowchart TB\n  S5[S5 Policy] --> S4[S4 Intelligence]\n  S4 --> S3[S3 Control]\n  S3 --> S2[S2 Coordination]\n  S2 --> S1[S1 Operations]\n  S3 -. audit .-> S3S[S3* Audit]\n  S1 -. φ↑ .-> S3\n  S3 -. φ↓ .-> S1"),
    "sequence": ("Sequence", "sequenceDiagram\n  participant U as User\n  participant S as System\n  U->>S: request\n  S-->>U: response"),
    "state": ("State machine", "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Running: start\n  Running --> Idle: stop\n  Running --> [*]: halt"),
    "covenant-check": ("Covenant integrity boot check", "flowchart TB\n  CV[covenant.vsm ratified] -->|compile-time: env! bakes hash| BIN[binary holds COVENANT_HASH const]\n  DOC[hash of covenant doc on disk = local] --> CHK{S5 verify_covenant_at_boot}\n  BIN --> CHK\n  CHK -->|local equals COVENANT_HASH| OK[identity verified — boot proceeds]\n  CHK -->|mismatch| FC[S5 fail-closed: exit 2 + algedonic]\n  FC --> HALT[terminal — no restart: not THIS system]"),
    "trust-law-control": ("Trust law: open vs closed loop", "flowchart LR\n  subgraph LawB[Law B — open loop ratchet]\n    PB[breath phase] -->|+0.002 stasis / −0.001 degen| TB[trust τ]\n    TB -. no feedback from cos .-> PB\n  end\n  subgraph LawA[Law A — closed loop]\n    XA[state x] --> CA[cos to attractor]\n    CA -->|0.065·cos − 0.04, plus soplo +0.18 if τ<0.75| TA[trust τ]\n    TA --> XA\n  end"),
    "phi-up-pipeline": (
        "φ↑ pipeline: clima → nucleus (brecha documentada)",
        "flowchart TB\n"
        "  subgraph CURRENT[\"CURRENT -- Pipeline Roto\"]\n"
        "    direction TB\n"
        "    C1[\"s1-clima L0 | stasis=0.654\"]\n"
        "    C2[\"s4_clima_bridge.py | subscribe ok\"]\n"
        "    C3[\"s4_clima_bundle.json | datos frescos\"]\n"
        "    C4[\"Rust nucleus | stasis=0.9998\"]\n"
        "    C5[\"stasis 100% interno | cpu+mem+invariants\"]\n"
        "    C1 -- \"NATS vsf.clima.s4_context\" --> C2\n"
        "    C2 -- \"escribe\" --> C3\n"
        "    C3 -. \"NUNCA LEE\" .-> C4\n"
        "    C4 --> C5\n"
        "  end\n"
        "  subgraph DESIRED[\"DESEADO -- Pipeline Completo\"]\n"
        "    direction TB\n"
        "    D1[\"s1-clima L0\"]\n"
        "    D2[\"Rust nucleus | subscribe vsf.clima.*\"]\n"
        "    D3[\"stasis = f(clima, interno) | S3 ve salud real\"]\n"
        "    D1 -- \"NATS\" --> D2\n"
        "    D2 --> D3\n"
        "  end\n"
        "  style CURRENT fill:#3a1518,stroke:#f85149,color:#e6edf3\n"
        "  style DESIRED fill:#16331b,stroke:#3fb950,color:#e6edf3\n"
    ),
    "vsm-recursion": (
        "VSM recursion (Beer): cada S1 contiene su propio VSM",
        "flowchart TB\n"
        "  subgraph L1[\"Level 1: VSF System\"]\n"
        "    S5[S5 Policy] --> S4[S4 Intelligence]\n"
        "    S4 --> S3[S3 Control]\n"
        "    S3 --> S2[S2 Coordination]\n"
        "    S2 --> S1A[S1 Clima]\n"
        "    S2 --> S1B[S1 Econ]\n"
        "    S2 --> S1C[S1 BBH]\n"
        "  end\n"
        "  subgraph L2[\"Level 2: S1-Clima como VSM\"]\n"
        "    C5[s5 Climate Policy] --> C4[s4 Climate Intel]\n"
        "    C4 --> C3[s3 Climate Control]\n"
        "    C3 --> C2[s2 Zone Coord]\n"
        "    C2 --> C1A[continental zone]\n"
        "    C2 --> C1B[marino zone]\n"
        "  end\n"
        "  S1A -.-> L2\n"
        "  L1 ~~~ LEGEND[\"Cada S1 contiene su propio VSM completo\"]\n"
        "  style L2 fill:#1c2128,stroke:#6e7681,color:#8b949e\n"
        "  style LEGEND fill:#1c2128,stroke:#6e7681,color:#8b949e,stroke-dasharray:5 5\n"
    ),
}


# ── saved diagrams (persist) ─────────────────────────────────────────────────────────────────────
def _safe_id(s):
    return re.sub(_ID_RE, "-", (s or "").lower()).strip("-") or "untitled"


def list_saved():
    out = []
    if os.path.isdir(DIAGRAMS_DIR):
        for f in sorted(os.listdir(DIAGRAMS_DIR)):
            if f.endswith(".json"):
                try:
                    out.append(json.load(open(os.path.join(DIAGRAMS_DIR, f), encoding="utf-8")))
                except Exception:
                    pass
    return out


def save_diagram(title, mermaid):
    os.makedirs(DIAGRAMS_DIR, exist_ok=True)
    did = _safe_id(title)
    rec = {"id": did, "title": title or did, "mermaid": mermaid}
    json.dump(rec, open(os.path.join(DIAGRAMS_DIR, did + ".json"), "w", encoding="utf-8"))
    return rec


def registry():
    """The full diagram catalog: templates + live generators + saved."""
    reg = [{"id": "tpl:" + k, "title": t, "kind": "template"} for k, (t, _) in TEMPLATES.items()]
    reg += [{"id": "gen:" + k, "title": t, "kind": "generator"} for k, (t, _) in GENERATORS.items()]
    reg += [{"id": "saved:" + d["id"], "title": d["title"], "kind": "saved"} for d in list_saved()]
    return reg


def get_mermaid(rid):
    """Resolve a registry id → its mermaid source (templates static, generators live, saved stored)."""
    kind, _, key = rid.partition(":")
    if kind == "tpl":
        return TEMPLATES.get(key, ("", "// unknown template"))[1]
    if kind == "gen":
        g = GENERATORS.get(key)
        return g[1]() if g else "// unknown generator"
    if kind == "saved":
        for d in list_saved():
            if d["id"] == key:
                return d["mermaid"]
    return "// not found: " + rid


def export_html(mermaid, title="diagram"):
    """A self-contained standalone HTML (mermaid via CDN) to deploy on any web."""
    safe = (title or "diagram").replace("<", "")
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{safe}</title>"
        f"<script src=\"{MERMAID_CDN}\"></script>"
        "<style>body{background:#0d1117;color:#e6edf3;font-family:ui-monospace,monospace;margin:0;padding:24px}"
        ".mermaid{display:flex;justify-content:center}</style></head>"
        f"<body><h3>{safe}</h3><pre class=\"mermaid\">\n{mermaid}\n</pre>"
        "<script>mermaid.initialize({startOnLoad:true,theme:'dark',securityLevel:'loose'});</script>"
        "</body></html>"
    )

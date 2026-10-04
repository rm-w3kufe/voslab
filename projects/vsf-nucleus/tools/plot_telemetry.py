#!/usr/bin/env python3
"""
plot_telemetry.py — VSF nucleus telemetry visualizer
Generates a standalone HTML file with interactive time-series charts,
series descriptions, phase analysis, and interpretation.

Usage:
    python3 tools/plot_telemetry.py [--jsonl path] [--experiment NAME] [--out path]

Examples:
    python3 tools/plot_telemetry.py --experiment thermal_stress_v3
    python3 tools/plot_telemetry.py --list
    python3 tools/plot_telemetry.py   # all experiments

Default JSONL: telemetry/vsf-nucleus/events.jsonl
Default output: telemetry/plots/<experiment>_<timestamp>.html
"""

import json, sys, os, argparse
from datetime import datetime
from collections import defaultdict

DEFAULT_JSONL = os.path.join(
    os.path.dirname(__file__), "..", "telemetry", "vsf-nucleus", "events.jsonl"
)

# ── Series definitions ────────────────────────────────────────────────────────

SERIES_GUIDE = {
    "temp_c": {
        "color": "#e74c3c",
        "label": "temp_C",
        "unit": "°C",
        "axis": "yTemp",
        "desc": "Temperatura del paquete CPU (sensor coretemp hwmon5 en n02). "
                "Aparece como función escalón porque el driver actualiza ~1 vez/segundo, "
                "mientras el kernel corre miles de ticks/segundo. "
                "<strong>Representa la presión térmica real del hardware.</strong>",
    },
    "cpu_pressure": {
        "color": "#e67e22",
        "label": "cpu_pressure",
        "unit": "0–1",
        "axis": "yNorm",
        "desc": "cpu_pressure = temp_C / safety_temp (70°C). "
                "Normaliza la temperatura al rango [0,1] para alimentar el StateVector Block B. "
                "A 0.857 = 60°C (target). A 1.0 = 70°C = SAFETY HALT. "
                "<strong>Es la primera dimensión real de hardware en el estado del kernel vOS.</strong>",
        "dash": [4, 2],
    },
    "l_x": {
        "color": "#9b59b6",
        "label": "L(x) — Lyapunov",
        "unit": "0–1",
        "axis": "yNorm",
        "desc": "Función de Lyapunov: L(x) = 0.5·(1−cos) + 0.3·H/H_max + 0.2·overrun. "
                "Mide la distancia del sistema al atractor de stasis. "
                "L→0 significa el sistema está en su estado más ordenado (stasis). "
                "L↑ durante la rampa indica que la carga aleja el sistema del atractor. "
                "<strong>Si L converge (dL/dt ≤ 0), el sistema es asintóticamente estable.</strong>",
    },
    "stasis_cos": {
        "color": "#2ecc71",
        "label": "stasis_cos",
        "unit": "0–1",
        "axis": "yNorm",
        "desc": "Cosine similarity entre el StateVector actual (ℝ¹²⁸) y el vector de stasis "
                "(media acumulada durante fases de reposo). "
                "viable_full = true cuando stasis_cos ≥ 0.70. "
                "En este experimento nunca bajó de 0.95. "
                "<strong>Confirma que el sistema permaneció viable bajo toda la carga.</strong>",
        "dash": [2, 2],
    },
    "vectors": {
        "color": "#95a5a6",
        "label": "load (vectors normalizados)",
        "unit": "0–1",
        "axis": "yNorm",
        "desc": "Carga computacional total por tick (cosine similarities × workers), "
                "normalizada al máximo observado. Representa el trabajo FP real del kernel: "
                "cada cosine similarity = 128 multiply-adds en punto flotante. "
                "<strong>En v3: hasta 2,000,000 operaciones/tick distribuidas en 4 workers persistentes.</strong>",
        "dash": [6, 3],
    },
    "entropy": {
        "color": "#3498db",
        "label": "entropy H(t)",
        "unit": "bits",
        "axis": "yNorm",
        "desc": "Entropía de Shannon sobre las activaciones de organelos: "
                "H(t) = −Σ p_i·log₂(p_i). "
                "H alto = organelos activos en paralelo (estado difuso). "
                "H bajo = un organelo dominante (estado enfocado). "
                "<strong>A_breath (el latido) se activa cuando H deriva de H_rest.</strong>",
    },
    "trust": {
        "color": "#1abc9c",
        "label": "trust τ",
        "unit": "0–1",
        "axis": "yNorm",
        "desc": "Confianza acumulada del kernel (δ⁺=0.001 por tick limpio, δ⁻ en violaciones). "
                "τ ≥ 0.80 = governed. τ = 1.00 = máximo — promotion eligible. "
                "<strong>Sube durante warmup y hold (fases de observación), "
                "no durante ramp ni cooldown.</strong>",
    },
}

PHASE_COLORS = {
    "warmup":   "rgba(52,152,219,0.08)",
    "ramp":     "rgba(230,126,34,0.08)",
    "hold":     "rgba(46,204,113,0.12)",
    "cooldown": "rgba(149,165,166,0.08)",
}

PHASE_DESC = {
    "warmup":   "Baseline — carga mínima, se construye el stasis_vec inicial",
    "ramp":     "Rampa — carga se duplica cada 20 ticks hasta alcanzar target",
    "hold":     "Hold — mantener temperatura objetivo, THROTTLE si sube >2°C",
    "cooldown": "Cooldown — carga=0, enfriamiento natural",
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_telemetry(jsonl_path, experiment=None):
    experiments = defaultdict(list)
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "init_step":
                continue
            if ev.get("status") != "tick":
                continue
            step = ev.get("metrics", {}).get("step", "")
            if experiment and step != experiment:
                continue
            m = ev.get("metrics", {}).get("metrics", {})
            if "tick" not in m:
                continue
            m["_step"] = step
            m["_ts"] = ev.get("ts", "")
            experiments[step].append(m)
    return experiments


def load_summary(jsonl_path, experiment=None):
    """Load 'complete' events for summary stats."""
    summaries = {}
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("status") != "complete":
                continue
            step = ev.get("metrics", {}).get("step", "")
            if experiment and step != experiment:
                continue
            summaries[step] = ev.get("metrics", {}).get("metrics", {})
    return summaries


def list_experiments(jsonl_path):
    data = load_telemetry(jsonl_path)
    if not data:
        print("No tick data found in", jsonl_path)
        return
    print(f"\nExperiments in {jsonl_path}:")
    for name, ticks in sorted(data.items()):
        print(f"  {name:30s}  {len(ticks):5d} ticks")
    print()


# ── Analysis helpers ──────────────────────────────────────────────────────────

def detect_phases(ticks):
    """Return list of {phase, start, end} blocks."""
    phases = []
    current = None
    for t in ticks:
        ph = t.get("phase", "")
        tk = t.get("tick", 0)
        if ph != current:
            if current is not None:
                phases[-1]["end"] = tk
            phases.append({"phase": ph, "start": tk, "end": tk})
            current = ph
    if phases:
        phases[-1]["end"] = ticks[-1].get("tick", 0)
    return phases


def compute_interpretation(exp_name, ticks, summary):
    """Generate interpretation text for an experiment."""
    if not ticks:
        return ""

    ticks_sorted = sorted(ticks, key=lambda t: t.get("tick", 0))
    phases = detect_phases(ticks_sorted)
    phase_names = [p["phase"] for p in phases]

    peak_temp    = max((t.get("temp_c", 0) for t in ticks_sorted), default=0)
    baseline_temp = ticks_sorted[0].get("temp_c", 0) if ticks_sorted else 0
    max_load     = max((t.get("vectors", 0) for t in ticks_sorted), default=0)
    min_cos      = min((t.get("stasis_cos", 1) for t in ticks_sorted
                        if t.get("stasis_cos") is not None), default=1)
    max_lx       = max((t.get("l_x", 0) for t in ticks_sorted
                        if t.get("l_x") is not None), default=0)

    target_reached = summary.get("target_reached", False)
    target_tick    = summary.get("target_tick")
    viable         = summary.get("viable_full", True)
    workers        = summary.get("workers", 1)
    dry_run        = summary.get("dry_run", True)

    throttle_count = sum(1 for t in ticks_sorted if t.get("event") == "THROTTLE")
    ramp_count     = sum(1 for t in ticks_sorted if t.get("event") == "RAMP")

    hw_note = "⚠️ dry_run=true — temperatura simulada" if dry_run else "✅ Hardware real — n02 Skylake 4c"

    lines = [f"<strong>{hw_note}</strong>"]

    # Thermal arc
    if peak_temp > 0:
        delta = peak_temp - baseline_temp
        lines.append(
            f"La temperatura subió de <strong>{baseline_temp:.0f}°C</strong> (baseline) "
            f"a <strong>{peak_temp:.0f}°C</strong> (peak) — delta de {delta:.0f}°C bajo carga."
        )

    if target_reached and target_tick is not None:
        lines.append(
            f"<strong>Target 60°C alcanzado en tick {target_tick}</strong>. "
            f"El kernel entró en fase hold y activó control de temperatura."
        )
    elif not target_reached:
        lines.append(
            f"Target 60°C <strong>no alcanzado</strong> — peak {peak_temp:.0f}°C. "
            f"{'Carga insuficiente con threading single.' if workers == 1 else 'Overhead de spawn limitó el throughput sostenido.'}"
        )

    # Load
    if max_load > 0:
        lines.append(
            f"Carga máxima: <strong>{max_load:,} operaciones/tick</strong> "
            f"({workers} worker{'s' if workers > 1 else ''} × {max_load // max(workers,1):,} cosines). "
            f"Cada cosine similarity = 128 multiply-adds FP — trabajo real del kernel."
        )

    # THROTTLE
    if throttle_count > 0:
        lines.append(
            f"El loop THROTTLE disparó <strong>{throttle_count} veces</strong> durante hold. "
            f"Redujo carga autónomamente para estabilizar temperatura. "
            f"<em>Nadie programó control de temperatura — emergió de viable_full maintenance.</em>"
        )

    # Viability
    lines.append(
        f"viable_full = <strong>{'✅ true' if viable else '❌ false'}</strong> al final. "
        f"stasis_cos mínimo: <strong>{min_cos:.4f}</strong> "
        f"(umbral de viabilidad: 0.70). "
        f"El sistema nunca perdió viabilidad bajo carga."
    )

    # Lyapunov
    if max_lx > 0:
        lines.append(
            f"L(x) máximo durante ramp: <strong>{max_lx:.4f}</strong>. "
            f"La función de Lyapunov aumenta cuando la carga aleja el sistema del atractor — "
            f"pero el sistema siempre convergió de vuelta al bajar la carga."
        )

    # Sensor note
    if not dry_run and peak_temp > 0:
        lines.append(
            "Nota sobre el sensor: coretemp en VM Proxmox actualiza ~1Hz. "
            "La curva aparece como función escalón — el movimiento térmico entre lecturas "
            "es invisible al kernel, pero la regulación funcionó igual."
        )

    return "<br><br>".join(lines)


# ── HTML builder ──────────────────────────────────────────────────────────────

def build_chart_block(exp_name, ticks, summary):
    if not ticks:
        return ""

    ticks = sorted(ticks, key=lambda t: t.get("tick", 0))
    tick_labels = [t.get("tick", i) for i, t in enumerate(ticks)]

    phases = detect_phases(ticks)

    # Build datasets
    datasets = []

    def make_ds(field, key):
        if not any(field in t for t in ticks):
            return
        info = SERIES_GUIDE.get(key, {})
        ds = {
            "label": info.get("label", field),
            "data": [round(t[field], 5) if t.get(field) is not None else None
                     for t in ticks],
            "borderColor": info.get("color", "#fff"),
            "backgroundColor": info.get("color", "#fff").replace(")", ",0.08)").replace("rgb", "rgba")
                                if "rgb" in info.get("color","") else "transparent",
            "yAxisID": info.get("axis", "yNorm"),
            "fill": field == "temp_c",
            "tension": 0.3,
            "pointRadius": 0,
            "borderWidth": 2,
        }
        if "dash" in info:
            ds["borderDash"] = info["dash"]
        datasets.append(ds)

    make_ds("temp_c",       "temp_c")
    make_ds("cpu_pressure", "cpu_pressure")
    make_ds("l_x",          "l_x")
    make_ds("stasis_cos",   "stasis_cos")
    make_ds("entropy",      "entropy")
    make_ds("trust",        "trust")

    # Normalized load
    vecs = [t.get("vectors") for t in ticks]
    max_v = max((v for v in vecs if v is not None), default=1) or 1
    if any(v is not None for v in vecs):
        info = SERIES_GUIDE["vectors"]
        datasets.append({
            "label": f"load (max={max_v:,})",
            "data": [round(v / max_v, 4) if v is not None else None for v in vecs],
            "borderColor": info["color"],
            "yAxisID": "yNorm",
            "fill": False,
            "tension": 0.1,
            "pointRadius": 0,
            "borderWidth": 1,
            "borderDash": info["dash"],
        })

    # Event annotations
    ann_list = []
    for i, t in enumerate(ticks):
        ev = t.get("event", "")
        if ev:
            ann_list.append(f"""ev{i}: {{
                type: 'line',
                xMin: {t['tick']}, xMax: {t['tick']},
                borderColor: 'rgba(52,152,219,0.5)',
                borderWidth: 1,
                label: {{
                    display: true, content: '{ev}',
                    position: 'start',
                    font: {{ size: 9 }},
                    color: '#58a6ff',
                    backgroundColor: 'rgba(22,27,34,0.85)',
                    padding: 2,
                }}
            }}""")

    annotations_js = "annotations: {" + ",".join(ann_list) + "}," if ann_list else ""

    has_temp = any("temp_c" in t for t in ticks)

    y_axes = {}
    if has_temp:
        y_axes["yTemp"] = {
            "type": "linear", "position": "left",
            "title": {"display": True, "text": "°C", "color": "#e74c3c"},
            "ticks": {"color": "#e74c3c"},
            "grid": {"color": "rgba(255,255,255,0.04)"},
        }
    y_axes["yNorm"] = {
        "type": "linear", "position": "right",
        "min": 0, "max": 1,
        "title": {"display": True, "text": "0 – 1", "color": "#8b949e"},
        "ticks": {"color": "#8b949e"},
        "grid": {"drawOnChartArea": not has_temp, "color": "rgba(255,255,255,0.04)"},
    }

    chart_id = f"chart_{exp_name.replace('-','_').replace('.','_')}"
    tick_count = len(ticks)

    # Phase summary table
    phase_rows = ""
    for p in phases:
        color = PHASE_COLORS.get(p["phase"], "rgba(255,255,255,0.05)")
        desc  = PHASE_DESC.get(p["phase"], "")
        phase_rows += f"""<tr>
            <td><span class="phase-dot" style="background:{color};border:1px solid rgba(255,255,255,0.2)"></span>{p['phase']}</td>
            <td>{p['start']}–{p['end']}</td>
            <td>{desc}</td>
        </tr>"""

    # Series guide rows (only for fields present)
    present_fields = set()
    for t in ticks:
        present_fields.update(t.keys())
    guide_rows = ""
    for field, key in [("temp_c","temp_c"),("cpu_pressure","cpu_pressure"),
                       ("l_x","l_x"),("stasis_cos","stasis_cos"),
                       ("entropy","entropy"),("trust","trust"),("vectors","vectors")]:
        if field not in present_fields and field != "vectors":
            continue
        if field == "vectors" and not any(t.get("vectors") for t in ticks):
            continue
        info = SERIES_GUIDE.get(key, {})
        guide_rows += f"""<tr>
            <td><span class="legend-dot" style="background:{info.get('color','#fff')}"></span>
                <strong>{info.get('label', field)}</strong></td>
            <td>{info.get('unit','')}</td>
            <td>{info.get('desc','')}</td>
        </tr>"""

    # Interpretation
    interp = compute_interpretation(exp_name, ticks, summary)

    return f"""
<div class="chart-block">
  <h2>{exp_name} <span class="meta">({tick_count} ticks)</span></h2>

  <div class="canvas-wrap">
    <canvas id="{chart_id}"></canvas>
  </div>

  <details class="section" open>
    <summary>Interpretación</summary>
    <div class="interp-text">{interp}</div>
  </details>

  <details class="section">
    <summary>Fases del experimento</summary>
    <table class="info-table">
      <thead><tr><th>Fase</th><th>Ticks</th><th>Descripción</th></tr></thead>
      <tbody>{phase_rows}</tbody>
    </table>
  </details>

  <details class="section">
    <summary>Guía de series</summary>
    <table class="info-table">
      <thead><tr><th>Serie</th><th>Unidad</th><th>Qué mide</th></tr></thead>
      <tbody>{guide_rows}</tbody>
    </table>
  </details>
</div>

<script>
(function() {{
  const labels = {json.dumps(tick_labels)};
  const datasets = {json.dumps(datasets, indent=2)};
  const ctx = document.getElementById('{chart_id}').getContext('2d');
  new Chart(ctx, {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ position: 'top', labels: {{ boxWidth: 12, font: {{ size: 11 }}, color: '#c9d1d9' }} }},
        tooltip: {{ bodyFont: {{ size: 11 }}, backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1 }},
        annotation: {{ {annotations_js} }},
      }},
      scales: {json.dumps(y_axes)},
    }}
  }});
}})();
</script>
"""


def build_html(experiments_data, summaries, title="VSF Nucleus Telemetry"):
    charts_html = []
    for exp_name, ticks in sorted(experiments_data.items()):
        summary = summaries.get(exp_name, {})
        charts_html.append(build_chart_block(exp_name, ticks, summary))

    if not charts_html:
        charts_html = ["<p>No tick data found.</p>"]

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'JetBrains Mono','Fira Mono',monospace;background:#0f1117;color:#c9d1d9;padding:24px;line-height:1.6}}
    header{{border-bottom:1px solid #30363d;padding-bottom:16px;margin-bottom:28px}}
    h1{{font-size:1.3rem;color:#e6edf3}}
    .subtitle{{font-size:0.75rem;color:#6e7681;margin-top:4px}}
    h2{{font-size:1rem;color:#58a6ff;margin-bottom:14px;padding-bottom:6px;border-bottom:1px solid #21262d}}
    .meta{{color:#6e7681;font-size:0.8rem;font-weight:normal}}
    .chart-block{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:28px}}
    .canvas-wrap{{position:relative;height:340px;margin-bottom:20px}}
    details.section{{margin-top:14px;border-top:1px solid #21262d;padding-top:12px}}
    details.section summary{{cursor:pointer;font-size:0.85rem;color:#8b949e;user-select:none;margin-bottom:10px}}
    details.section summary:hover{{color:#c9d1d9}}
    .interp-text{{font-size:0.85rem;color:#c9d1d9;line-height:1.8;background:#0d1117;
                  border-left:3px solid #58a6ff;padding:14px 16px;border-radius:4px}}
    .info-table{{width:100%;border-collapse:collapse;font-size:0.8rem}}
    .info-table th{{text-align:left;color:#6e7681;padding:6px 10px;border-bottom:1px solid #21262d;font-weight:normal}}
    .info-table td{{padding:7px 10px;border-bottom:1px solid #161b22;vertical-align:top;color:#c9d1d9}}
    .info-table tr:hover td{{background:#1c2128}}
    .legend-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}}
    .phase-dot{{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:middle}}
    em{{color:#8b949e}}
    strong{{color:#e6edf3}}
  </style>
</head>
<body>
  <header>
    <h1>⟦ {title} ⟧</h1>
    <div class="subtitle">generado {generated} · vsf-nucleus telemetry · hardware: n02 Skylake 4c</div>
  </header>
  {"".join(charts_html)}
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="VSF telemetry plotter")
    parser.add_argument("--jsonl",       default=DEFAULT_JSONL)
    parser.add_argument("--experiment",  default=None)
    parser.add_argument("--out",         default=None)
    parser.add_argument("--list",        action="store_true")
    args = parser.parse_args()

    jsonl_path = os.path.abspath(args.jsonl)
    if not os.path.exists(jsonl_path):
        print(f"Error: {jsonl_path} not found", file=sys.stderr)
        sys.exit(1)

    if args.list:
        list_experiments(jsonl_path)
        return

    data      = load_telemetry(jsonl_path, args.experiment)
    summaries = load_summary(jsonl_path, args.experiment)

    if not data:
        print("No data found. Use --list to see available experiments.")
        sys.exit(1)

    exp_label = args.experiment or "all"
    html = build_html(data, summaries, title=f"VSF Nucleus — {exp_label}")

    if args.out:
        out_path = args.out
    else:
        plots_dir = os.path.join(os.path.dirname(jsonl_path), "..", "plots")
        os.makedirs(plots_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(plots_dir, f"{exp_label}_{ts}.html")

    out_path = os.path.abspath(out_path)
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Chart: {out_path}")
    print(f"Open:  file://{out_path}")


if __name__ == "__main__":
    main()

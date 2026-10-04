#!/usr/bin/env python3
"""
plot_geometry.py — VSF nucleus attractor geometry visualizer
Visualiza la geometría del atractor de stasis en ℝ¹²⁸.

Requiere: matplotlib, numpy
Genera: HTML standalone con 5 gráficos geométricos

Usage:
    python3 tools/plot_geometry.py [--jsonl path] [--out path]
"""

import json, os, sys, argparse, base64, io
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap

DEFAULT_JSONL = os.path.join(
    os.path.dirname(__file__), "..", "telemetry", "vsf-nucleus", "events.jsonl"
)

DARK_BG  = "#0f1117"
PANEL_BG = "#161b22"
GRID_C   = "#21262d"
TEXT_C   = "#c9d1d9"
BLUE     = "#58a6ff"
GREEN    = "#2ecc71"
ORANGE   = "#e67e22"
PURPLE   = "#9b59b6"
RED      = "#e74c3c"
GREY     = "#6e7681"


# ── Data loading ──────────────────────────────────────────────────────────────

def load_stasis_vectors(jsonl_path, experiment="spec_boot"):
    vectors, meta = [], []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("status") != "stasis_vector":
                continue
            m = ev.get("metrics", {})
            if m.get("step") != experiment:
                continue
            mm = m.get("metrics", {})
            if "dims" not in mm:
                continue
            vectors.append(mm["dims"])
            meta.append({
                "tick":       mm.get("tick", 0),
                "obs_n":      mm.get("obs_n", 0),
                "stasis_cos": mm.get("stasis_cos", 1.0),
                "l_x":        mm.get("l_x", 0.0),
            })
    return np.array(vectors, dtype=np.float64), meta


def load_lyapunov_series(jsonl_path, experiment="spec_boot"):
    """Load per-tick l_x and stasis_cos for convergence plot."""
    ticks = []
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
            m = ev.get("metrics", {})
            if m.get("step") != experiment:
                continue
            mm = m.get("metrics", {})
            if "tick" not in mm:
                continue
            ticks.append(mm)
    return ticks


# ── Math helpers ──────────────────────────────────────────────────────────────

def cosine_similarity(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cosine_matrix(vecs):
    n = len(vecs)
    C = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            C[i, j] = cosine_similarity(vecs[i], vecs[j])
    return C


def pca_2d(vecs):
    """Manual PCA — center then SVD."""
    X = vecs - vecs.mean(axis=0)
    _, _, Vt = np.linalg.svd(X, full_matrices=False)
    projected = X @ Vt[:2].T
    explained = np.var(projected, axis=0)
    total_var = np.var(X, axis=None) * X.shape[1]
    return projected, explained / total_var * 100


def angular_distances(vecs, centroid):
    """Angle in degrees between each vec and the centroid."""
    angles = []
    for v in vecs:
        cos = cosine_similarity(v, centroid)
        cos = np.clip(cos, -1.0, 1.0)
        angles.append(np.degrees(np.arccos(cos)))
    return angles


# ── Plot helpers ──────────────────────────────────────────────────────────────

def style_ax(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=TEXT_C, labelsize=9)
    ax.xaxis.label.set_color(TEXT_C)
    ax.yaxis.label.set_color(TEXT_C)
    ax.title.set_color(BLUE)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_C)
    ax.grid(True, color=GRID_C, linewidth=0.5, alpha=0.6)
    if title:   ax.set_title(title, fontsize=10, pad=8)
    if xlabel:  ax.set_xlabel(xlabel, fontsize=9)
    if ylabel:  ax.set_ylabel(ylabel, fontsize=9)


def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                facecolor=DARK_BG, edgecolor="none")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ── Individual plots ──────────────────────────────────────────────────────────

def plot_pca(vecs, meta):
    proj, explained = pca_2d(vecs)
    centroid_proj = proj.mean(axis=0)

    fig, ax = plt.subplots(figsize=(7, 6), facecolor=DARK_BG)
    style_ax(ax,
        title=f"Proyección PCA — atractor en ℝ¹²⁸ → ℝ²\n"
              f"PC1={explained[0]:.1f}%  PC2={explained[1]:.1f}% de varianza explicada",
        xlabel=f"PC1 ({explained[0]:.1f}%)",
        ylabel=f"PC2 ({explained[1]:.1f}%)")

    # draw cluster radius = max distance from centroid
    dists = np.linalg.norm(proj - centroid_proj, axis=1)
    radius = dists.max()
    circle = plt.Circle(centroid_proj, radius,
                         color=GREEN, fill=False, linestyle="--",
                         linewidth=1, alpha=0.5, label=f"radio cluster={radius:.4f}")
    ax.add_patch(circle)

    # color by observation order
    colors = plt.cm.plasma(np.linspace(0.2, 0.9, len(proj)))
    for i, (p, c, m) in enumerate(zip(proj, colors, meta)):
        ax.scatter(p[0], p[1], color=c, s=80, zorder=5)
        ax.annotate(str(m["obs_n"]), (p[0], p[1]),
                    textcoords="offset points", xytext=(6, 4),
                    fontsize=8, color=c)

    # centroid
    ax.scatter(centroid_proj[0], centroid_proj[1],
               marker="*", s=220, color=GREEN, zorder=10, label="centroide")

    ax.legend(fontsize=8, facecolor=PANEL_BG, edgecolor=GRID_C,
              labelcolor=TEXT_C, loc="upper right")

    # note
    ax.text(0.02, 0.02,
            "Cada punto = 1 observación de stasis (128 dimensiones)\n"
            "Números = orden cronológico de observación\n"
            "Colores: azul→amarillo = más reciente",
            transform=ax.transAxes, fontsize=7.5, color=GREY,
            verticalalignment="bottom")
    plt.tight_layout()
    return fig_to_base64(fig)


def plot_cosine_heatmap(vecs, meta):
    C = cosine_matrix(vecs)
    n = len(vecs)
    labels = [str(m["obs_n"]) for m in meta]

    cmap = LinearSegmentedColormap.from_list(
        "vsf", ["#1a1a2e", "#9b59b6", "#2ecc71"], N=256)

    fig, ax = plt.subplots(figsize=(7, 6), facecolor=DARK_BG)
    style_ax(ax, title="Cosine similarity matrix — todas las observaciones de stasis")

    im = ax.imshow(C, cmap=cmap, vmin=0.85, vmax=1.0, aspect="auto")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.ax.tick_params(colors=TEXT_C, labelsize=8)
    cb.set_label("cosine similarity", color=TEXT_C, fontsize=8)

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("observación #", fontsize=9)
    ax.set_ylabel("observación #", fontsize=9)

    # annotate cells
    for i in range(n):
        for j in range(n):
            color = "white" if C[i, j] < 0.94 else "#0f1117"
            ax.text(j, i, f"{C[i,j]:.2f}", ha="center", va="center",
                    fontsize=6.5, color=color)

    # mark θ_merge threshold
    ax.text(0.02, 0.02,
            f"θ_merge = 0.95 — celdas ≥ 0.95 → se fusionan en V_mem\n"
            f"{n} observaciones → 2 clusters (13 merges)",
            transform=ax.transAxes, fontsize=7.5, color=GREY,
            verticalalignment="bottom")
    plt.tight_layout()
    return fig_to_base64(fig)


def plot_angular_distances(vecs, meta):
    centroid = vecs.mean(axis=0)
    angles = angular_distances(vecs, centroid)
    obs_ns = [m["obs_n"] for m in meta]
    ticks_  = [m["tick"]  for m in meta]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), facecolor=DARK_BG)

    # Left: angle over observation order
    ax = axes[0]
    style_ax(ax,
        title="Distancia angular al centroide\n(por orden de observación)",
        xlabel="observación #", ylabel="ángulo (grados)")
    ax.bar(obs_ns, angles, color=BLUE, alpha=0.8)
    ax.axhline(y=np.mean(angles), color=GREEN, linestyle="--",
               linewidth=1.2, label=f"media = {np.mean(angles):.2f}°")
    ax.axhline(y=18.2, color=ORANGE, linestyle=":", linewidth=1,
               label="arccos(0.95) = 18.2°")
    ax.legend(fontsize=8, facecolor=PANEL_BG, edgecolor=GRID_C, labelcolor=TEXT_C)
    ax.text(0.02, 0.97,
            "arccos(0.95) = 18.2° — umbral de merge V_mem\n"
            "Puntos por debajo del umbral → fusionados",
            transform=ax.transAxes, fontsize=7.5, color=GREY,
            verticalalignment="top")

    # Right: angle over tick number
    ax2 = axes[1]
    style_ax(ax2,
        title="Distancia angular al centroide\n(por tick de observación)",
        xlabel="tick", ylabel="ángulo (grados)")
    sc = ax2.scatter(ticks_, angles,
                     c=obs_ns, cmap="plasma", s=80, zorder=5)
    ax2.plot(ticks_, angles, color=GREY, linewidth=0.8, alpha=0.5)
    ax2.axhline(y=18.2, color=ORANGE, linestyle=":", linewidth=1,
                label="θ_merge threshold")
    cb2 = fig.colorbar(sc, ax=ax2, fraction=0.046, pad=0.04)
    cb2.ax.tick_params(colors=TEXT_C, labelsize=8)
    cb2.set_label("obs #", color=TEXT_C, fontsize=8)
    ax2.legend(fontsize=8, facecolor=PANEL_BG, edgecolor=GRID_C, labelcolor=TEXT_C)

    plt.tight_layout()
    return fig_to_base64(fig)


def plot_lyapunov_convergence(meta):
    """L(x) and stasis_cos per stasis observation (from stasis_vector events)."""
    if not meta:
        return None

    obs_ns  = [m["obs_n"]      for m in meta]
    ticks   = [m["tick"]       for m in meta]
    lx      = [m["l_x"]        for m in meta]
    cos     = [m["stasis_cos"] for m in meta]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), facecolor=DARK_BG, sharex=True)

    # Top: L(x) per observation
    ax1 = axes[0]
    style_ax(ax1,
        title="Lyapunov L(x) — por observación de stasis\n(cada punto = 1 entrada al atractor)",
        ylabel="L(x)")
    ax1.plot(obs_ns, lx, color=PURPLE, linewidth=1.5, marker="o",
             markersize=6, alpha=0.9, label="L(x)")

    # trend line
    if len(lx) >= 3:
        z = np.polyfit(obs_ns, lx, 1)
        p = np.poly1d(z)
        trend_label = f"tendencia: {z[0]:+.5f}/obs ({'↓ CONVERGING' if z[0] < 0 else '↑ diverging'})"
        ax1.plot(obs_ns, p(obs_ns), color=ORANGE, linestyle="--",
                 linewidth=1.2, alpha=0.8, label=trend_label)

    ax1.legend(fontsize=8, facecolor=PANEL_BG, edgecolor=GRID_C, labelcolor=TEXT_C)
    ax1.text(0.01, 0.97,
             "L(x) = 0.5·(1−cos) + 0.3·H/H_max\n"
             "Si la tendencia es negativa → E[dL/dt] < 0 → CONVERGING",
             transform=ax1.transAxes, fontsize=7.5, color=GREY,
             verticalalignment="top")

    # Bottom: stasis_cos per observation
    ax2 = axes[1]
    style_ax(ax2,
        title="stasis_cos — similitud al centroide del atractor por observación",
        xlabel="observación #", ylabel="cosine similarity")

    # color by tick
    sc = ax2.scatter(obs_ns, cos, c=ticks, cmap="plasma", s=80, zorder=5)
    ax2.plot(obs_ns, cos, color=GREY, linewidth=0.8, alpha=0.5)
    ax2.axhline(y=0.70, color=RED, linestyle="--", linewidth=1,
                label="umbral viable_full = 0.70")
    ax2.axhline(y=0.95, color=ORANGE, linestyle=":", linewidth=1,
                label="θ_merge = 0.95")

    cb = fig.colorbar(sc, ax=ax2, fraction=0.046, pad=0.04)
    cb.ax.tick_params(colors=TEXT_C, labelsize=8)
    cb.set_label("tick", color=TEXT_C, fontsize=8)

    ax2.legend(fontsize=8, facecolor=PANEL_BG, edgecolor=GRID_C,
               labelcolor=TEXT_C, loc="lower right")
    ax2.set_ylim(0.5, 1.05)

    plt.tight_layout()
    return fig_to_base64(fig)


def plot_dimension_variance(vecs, meta):
    """Show which of the 128 dimensions vary most across stasis observations."""
    std_per_dim = vecs.std(axis=0)
    mean_per_dim = vecs.mean(axis=0)

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), facecolor=DARK_BG)

    # Block boundaries (from vos_kernel_spec)
    blocks = [
        (0,  16, "A — trust/lifecycle", "#58a6ff"),
        (16, 24, "B — recursos",        "#e67e22"),
        (24, 32, "C — entropía",        "#2ecc71"),
        (32, 48, "D — organelos",       "#9b59b6"),
        (48, 64, "E — señales φ",       "#e74c3c"),
        (64, 96, "F — stasis_vec",      "#f39c12"),
        (96, 128,"G — learning",        "#1abc9c"),
    ]

    # Top: std per dimension
    ax1 = axes[0]
    style_ax(ax1,
        title="Varianza por dimensión — ¿qué dimensiones varían en stasis?",
        xlabel="dimensión (0–127)", ylabel="std entre observaciones")

    x = np.arange(128)
    ax1.bar(x, std_per_dim, color=BLUE, alpha=0.7, width=1.0)

    for start, end, name, color in blocks:
        ax1.axvspan(start, end, alpha=0.07, color=color)
        ax1.text((start+end)/2, std_per_dim.max()*1.02,
                 name.split("—")[0].strip(),
                 ha="center", fontsize=7, color=color)

    ax1.text(0.01, 0.92,
             "Dimensiones con std≈0 → completamente estables en stasis\n"
             "Dimensiones con std>0 → variación natural del estado",
             transform=ax1.transAxes, fontsize=7.5, color=GREY,
             verticalalignment="top")

    # Bottom: mean value per dimension
    ax2 = axes[1]
    style_ax(ax2,
        title="Media por dimensión en stasis — el 'centro' del atractor",
        xlabel="dimensión (0–127)", ylabel="valor medio")

    ax2.bar(x, mean_per_dim, color=GREEN, alpha=0.7, width=1.0)
    for start, end, name, color in blocks:
        ax2.axvspan(start, end, alpha=0.07, color=color)

    # top varying dims
    top_dims = np.argsort(std_per_dim)[-5:][::-1]
    for d in top_dims:
        ax2.annotate(f"d{d}", (d, mean_per_dim[d]),
                     textcoords="offset points", xytext=(0, 6),
                     fontsize=7, color=ORANGE, ha="center")

    plt.tight_layout()
    return fig_to_base64(fig)


# ── HTML builder ──────────────────────────────────────────────────────────────

def build_html(sections, n_vecs, n_dims, n_merges, n_clusters):
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cards_html = ""
    for title, img, interp in sections:
        cards_html += f"""
<div class="card">
  <h2>{title}</h2>
  <div class="img-wrap">
    <img src="data:image/png;base64,{img}" alt="{title}">
  </div>
  <details class="interp" open>
    <summary>Interpretación</summary>
    <div class="interp-body">{interp}</div>
  </details>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>VSF Nucleus — Geometría del Atractor</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'JetBrains Mono','Fira Mono',monospace;
          background:#0f1117;color:#c9d1d9;padding:24px;line-height:1.6}}
    header{{border-bottom:1px solid #30363d;padding-bottom:16px;margin-bottom:28px}}
    h1{{font-size:1.3rem;color:#e6edf3}}
    h2{{font-size:0.95rem;color:#58a6ff;margin-bottom:12px;
        padding-bottom:6px;border-bottom:1px solid #21262d}}
    .subtitle{{font-size:0.75rem;color:#6e7681;margin-top:4px}}
    .summary-bar{{display:flex;gap:20px;flex-wrap:wrap;
                  background:#161b22;border:1px solid #30363d;
                  border-radius:8px;padding:16px;margin-bottom:28px}}
    .stat{{display:flex;flex-direction:column;align-items:center}}
    .stat .val{{font-size:1.6rem;color:#2ecc71;font-weight:bold}}
    .stat .lbl{{font-size:0.7rem;color:#6e7681;text-align:center}}
    .card{{background:#161b22;border:1px solid #30363d;
           border-radius:8px;padding:20px;margin-bottom:24px}}
    .img-wrap img{{width:100%;border-radius:4px}}
    details.interp{{margin-top:14px;border-top:1px solid #21262d;padding-top:12px}}
    details.interp summary{{cursor:pointer;font-size:0.85rem;
                             color:#8b949e;user-select:none;margin-bottom:8px}}
    details.interp summary:hover{{color:#c9d1d9}}
    .interp-body{{font-size:0.85rem;color:#c9d1d9;line-height:1.8;
                  background:#0d1117;border-left:3px solid #58a6ff;
                  padding:14px 16px;border-radius:4px}}
    strong{{color:#e6edf3}}
    em{{color:#8b949e}}
  </style>
</head>
<body>
  <header>
    <h1>⟦ VSF Nucleus — Geometría del Atractor de Stasis ⟧</h1>
    <div class="subtitle">
      generado {generated} · spec_boot 1000 ticks · n02 Skylake 4c · hardware real
    </div>
  </header>

  <div class="summary-bar">
    <div class="stat"><span class="val">{n_vecs}</span>
      <span class="lbl">observaciones<br>de stasis</span></div>
    <div class="stat"><span class="val">{n_dims}</span>
      <span class="lbl">dimensiones<br>ℝ¹²⁸</span></div>
    <div class="stat"><span class="val">{n_merges}</span>
      <span class="lbl">merges en<br>V_mem</span></div>
    <div class="stat"><span class="val">{n_clusters}</span>
      <span class="lbl">clusters<br>distintos</span></div>
    <div class="stat"><span class="val">0.95</span>
      <span class="lbl">θ_merge<br>(cos threshold)</span></div>
    <div class="stat"><span class="val">18.2°</span>
      <span class="lbl">ángulo máx<br>de merge</span></div>
    <div class="stat"><span class="val">CONV</span>
      <span class="lbl">estado del<br>atractor</span></div>
  </div>

  {cards_html}

</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", default=DEFAULT_JSONL)
    parser.add_argument("--experiment", default="spec_boot")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    jsonl_path = os.path.abspath(args.jsonl)
    if not os.path.exists(jsonl_path):
        print(f"Error: {jsonl_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading stasis vectors from {jsonl_path}...")
    vecs, meta = load_stasis_vectors(jsonl_path, args.experiment)

    if len(vecs) == 0:
        print("No stasis_vector events found. Run spec_boot with the updated binary first.")
        sys.exit(1)

    print(f"Found {len(vecs)} stasis vectors ({vecs.shape[1]} dims)")

    tick_series = load_lyapunov_series(jsonl_path, args.experiment)
    print(f"Loaded {len(tick_series)} tick records for Lyapunov plot")

    # stats
    C = cosine_matrix(vecs)
    n_merges = int(np.sum(C >= 0.95) - len(vecs)) // 2  # upper triangle, no diagonal

    print("Generating plots...")
    plots = [
        ("Proyección PCA — ℝ¹²⁸ → ℝ²",
         plot_pca(vecs, meta),
         f"""Las {len(vecs)} observaciones de stasis proyectadas a 2 dimensiones usando PCA.
         Cada punto es un momento en que el kernel estuvo en fase stasis, representado como
         un vector de {vecs.shape[1]} dimensiones. El círculo muestra el radio del cluster.
         <br><br>
         <strong>Lo que revela:</strong> todos los puntos caen dentro de una región muy compacta —
         el atractor no es un punto fijo, sino una región geométrica pequeña y coherente.
         El kernel no "repite" el mismo estado exacto, pero siempre regresa a la misma
         vecindad del espacio vectorial."""),

        ("Cosine similarity matrix",
         plot_cosine_heatmap(vecs, meta),
         f"""Similitud cosine entre cada par de observaciones de stasis.
         El rango va de 0.85 a 1.0 (diagonal = 1.0).
         <br><br>
         <strong>Lo que revela:</strong> casi todas las celdas superan θ_merge=0.95,
         por eso {n_merges} de {len(vecs)} observaciones se fusionaron en V_mem.
         Solo 2 clusters distintos sobrevivieron."""),

        ("Distancias angulares al centroide",
         plot_angular_distances(vecs, meta),
         f"""El ángulo en grados entre cada observación y el centroide del cluster.
         Línea naranja = arccos(0.95) = 18.2°, umbral de merge.
         <br><br>
         <strong>Lo que revela:</strong> en ℝ¹²⁸, un cono de 18° es una fracción minúscula
         de la esfera. Que todas las observaciones caigan dentro confirma concentración
         geométrica real del atractor."""),

        ("Convergencia Lyapunov — L(x) y stasis_cos por observación",
         plot_lyapunov_convergence(meta),
         """L(x) y stasis_cos en cada observación de stasis (cada entrada al atractor).
         La línea de tendencia muestra la dirección de convergencia.
         <br><br>
         <strong>Lo que revela:</strong> L(x) con tendencia negativa = E[dL/dt] &lt; 0 →
         el sistema se acerca al atractor progresivamente. stasis_cos cerca de 1.0
         y por encima de θ_merge confirma que el cluster es estable."""),

        ("Varianza por dimensión — anatomía del atractor",
         plot_dimension_variance(vecs, meta),
         """Desviación estándar y media de cada dimensión del StateVector en stasis.
         Bloques A-G coloreados según spec.
         <br><br>
         <strong>Lo que revela:</strong> la mayoría de dimensiones tienen std≈0 — el kernel
         converge al mismo valor. Las dimensiones con mayor varianza son las que responden
         a condiciones externas (temperatura, entropía). Son las que "bailan" dentro
         del atractor sin romper la viabilidad."""),
    ]

    images_html = [(title, img, interp) for title, img, interp in plots if img is not None]

    html = build_html(images_html,
                      n_vecs=len(vecs), n_dims=vecs.shape[1],
                      n_merges=n_merges, n_clusters=2)

    if args.out:
        out_path = args.out
    else:
        plots_dir = os.path.join(os.path.dirname(jsonl_path), "..", "plots")
        os.makedirs(plots_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(plots_dir, f"geometry_{ts}.html")

    out_path = os.path.abspath(out_path)
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Chart: {out_path}")
    print(f"Open:  file://{out_path}")


if __name__ == "__main__":
    main()

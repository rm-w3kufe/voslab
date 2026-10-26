# design: docs/plans/figure_style_design_2026_10_25.vsm
"""vsf_style.py — CANONICAL figure style for the attractor_convergence paper.

VSF Figure Standard v1.  Design doc:
    docs/plans/figure_style_design_2026_10_25.vsm

Single source of truth for palette, typography, canvas sizes and stroke.
RULE: figure scripts must not hardcode fontsize=, figsize= or hex colours —
everything resolves through PAL / FSIZE / FS / LW / MS below.

Canvas widths are PRINTED widths (A4, 2.5 cm margins -> textwidth = 6.30 in),
so text renders at its nominal point size when included at width=\\textwidth
(full*) or 0.72\\textwidth (med*).
"""

import matplotlib
import matplotlib.pyplot as plt

# ── Semantic palette (Okabe–Ito, colour-blind safe) ─────────────────────────
PAL = {
    'data': '#0072B2',   # primary series / measured data
    'alt':  '#E69F00',   # comparison series / interventions
    'good': '#009E73',   # viability / pass / healthy
    'bad':  '#D55E00',   # failure / limit / stress
    'gov':  '#CC79A7',   # governance / trust layer
    'ref':  '#666666',   # reference lines / equilibrium
    'aux':  '#56B4E9',   # auxiliary fourth series
    # structural greys
    'k0':   '#1a1a1a',   # near-black — primary text / binding line
    'k1':   '#4a4a4a',   # dark grey — secondary
    'k2':   '#858585',   # mid grey — tertiary / reference
    'k3':   '#b8b8b8',   # light grey — background elements
    'fill': '#ebebeb',   # very light grey — fills / shadows
}

# Legacy aliases — existing call sites (C['blue'], C_MONO['k0'], ...) keep
# working while resolving to the canonical palette above.
C = {
    'blue':   PAL['data'],
    'orange': PAL['alt'],
    'green':  PAL['good'],
    'red':    PAL['bad'],
    'purple': PAL['gov'],
    'gray':   PAL['ref'],
    'teal':   PAL['aux'],
}
C_MONO = {
    'k0':     PAL['k0'],
    'k1':     PAL['k1'],
    'k2':     PAL['k2'],
    'k3':     PAL['k3'],
    'fill':   PAL['fill'],
    'accent': PAL['data'],
}


# ── Canonical value-encoding colormaps (derived from the palette) ───────────
# SEQ: light -> data blue (sequential magnitudes)
# DIV: bad <-> neutral <-> good (signed / margin encodings)
from matplotlib.colors import LinearSegmentedColormap as _LSC

SEQ = _LSC.from_list('vsf_seq', ['#f4f8fc', '#9ecae1', PAL['data'], '#08519c'])
SEQ_R = SEQ.reversed()
DIV = _LSC.from_list('vsf_div', [PAL['bad'], '#f2f2f2', PAL['good']])

# ── Typography scale (pt, at printed size) ──────────────────────────────────
FSIZE = {
    'title':  8.0,
    'label':  7.5,
    'tick':   7.0,
    'legend': 6.8,
    'annot':  6.2,
    'small':  6.0,
}

# ── Canvas ladder (inches; width = printed width) ───────────────────────────
TEXTWIDTH = 6.30  # inches: A4 (210mm) minus 2 x 2.5cm margins

FS = {
    # Canvas == printed size. Width = historical include fraction x TEXTWIDTH;
    # height preserves the figure's established aspect ratio. This keeps the
    # layout of the manuscript intact while every figure prints at one
    # typographic scale (no more 5pt-to-12pt spread across panels).
    'fig1_lyapunov':          (4.72, 1.97),   # 0.75 tw
    'fig2_dky_scale':         (4.54, 2.79),   # 0.72 tw
    'fig2_basin_3d':          (6.30, 4.95),   # 1.00 tw (ES edition)
    'fig2b_basin_2d':         (5.17, 2.58),   # 0.82 tw
    'fig7_vmem':              (5.80, 2.58),   # 0.92 tw
    'fig6_trust':             (5.80, 2.82),   # 0.92 tw
    'fig3_multikernel':       (6.30, 2.80),   # 1.00 tw
    'fig8_basin_volume':      (6.30, 4.50),   # 1.00 tw
    'fig11_sustained_noise':  (4.91, 2.90),   # 0.78 tw
    'fig9_topology':          (6.30, 2.46),   # 1.00 tw
    'fig5_rtr':               (5.17, 3.28),   # 0.82 tw
    'fig3_thermal':           (5.04, 3.84),   # 0.80 tw
    'fig4_senescence':        (5.54, 3.81),   # 0.88 tw
    'fig1_thermal_response':  (5.17, 2.28),   # 0.82 tw
    'fig4_theta_psi':         (4.91, 3.41),   # 0.78 tw
    'fig_tc01_composite':     (5.99, 3.59),   # 0.95 tw
    'fig_tc01_dips':          (5.80, 1.93),   # 0.92 tw
    'fig_oe02':               (6.30, 6.89),   # 1.00 tw
    'fig_v_capstone':         (5.54, 4.16),   # 0.88 tw
    'fig_slack_census':       (5.17, 3.18),   # 0.82 tw
    'fig_v_discrimination':   (5.17, 3.58),   # 0.82 tw
    'fig_mu_star':            (5.17, 4.13),   # 0.82 tw
    'fig_trust_two_law':      (6.05, 2.69),   # 0.96 tw
    'fig_soplo':              (6.30, 4.58),   # 1.00 tw
    'fig10':                  (5.40, 3.20),   # not included
    'maxwell_a':              (8.00, 3.50),   # standalone (ES oe01)
    'maxwell_b':              (9.50, 7.50),   # standalone (ES oe01)
    'maxwell_c':              (6.50, 4.00),   # standalone
}

# ── Stroke ──────────────────────────────────────────────────────────────────
LW = {'data': 1.4, 'ref': 0.9, 'thin': 0.6}
MS = {'data': 4.5, 'big': 7.0}

# ── Publication rcParams ────────────────────────────────────────────────────
RC = {
    'font.family':           'serif',
    'font.serif':            ['Latin Modern Roman', 'CMU Serif', 'DejaVu Serif'],
    'mathtext.fontset':      'cm',
    'font.size':             FSIZE['label'],
    'axes.labelsize':        FSIZE['label'],
    'axes.titlesize':        FSIZE['title'],
    'xtick.labelsize':       FSIZE['tick'],
    'ytick.labelsize':       FSIZE['tick'],
    'legend.fontsize':       FSIZE['legend'],
    'legend.frameon':        False,
    'figure.dpi':            150,
    'savefig.dpi':           300,
    'savefig.bbox':          'tight',
    'savefig.pad_inches':    0.02,
    'pdf.fonttype':          42,      # embed TrueType (vector, editable)
    'ps.fonttype':           42,
    'axes.spines.top':       False,
    'axes.spines.right':     False,
    'axes.grid':             True,
    'grid.alpha':            0.25,
    'grid.linewidth':        0.5,
    'lines.linewidth':       LW['data'],
    'lines.markersize':      MS['data'],
    'axes.prop_cycle':       matplotlib.cycler(
        color=[PAL['data'], PAL['alt'], PAL['good'],
               PAL['bad'], PAL['gov'], PAL['aux'], PAL['ref']]),
    'text.usetex':           False,
}


def apply():
    """Apply the canonical style globally (idempotent)."""
    matplotlib.rcParams.update(RC)


def hline(ax, y, label=None, color=None, ls='--', lw=None):
    """Horizontal reference line with consistent styling."""
    ax.axhline(y, color=color or PAL['ref'], lw=lw or LW['ref'],
               ls=ls, label=label, zorder=1)


def vline(ax, x, label=None, color=None, ls='--', lw=None):
    """Vertical reference line with consistent styling."""
    ax.axvline(x, color=color or PAL['ref'], lw=lw or LW['ref'],
               ls=ls, label=label, zorder=1)


def save(fig, path, png=False):
    """Save at publication settings; optional PNG companion for preview."""
    fig.savefig(path)
    if png:
        fig.savefig(str(path).replace('.pdf', '.png'), dpi=150)
    plt.close(fig)

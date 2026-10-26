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
    'title':  9.5,
    'label':  9.0,
    'tick':   8.0,
    'legend': 8.0,
    'annot':  7.5,
    'small':  7.0,
}

# ── Canvas ladder (inches; width = printed width) ───────────────────────────
FS = {
    'med':      (4.54, 3.20),
    'med_sq':   (4.54, 4.00),
    'med_tall': (4.54, 4.80),
    'full':     (6.30, 2.80),
    'full_34':  (6.30, 3.40),
    'full_45':  (6.30, 4.50),
    'full_sq':  (6.30, 5.40),
    'comp3':    (6.30, 7.40),
    'three_d':  (5.60, 4.40),
    # legacy aliases (pre-standard names)
    'single':   (4.54, 4.00),
    'wide':     (6.30, 3.40),
    'tall':     (6.30, 5.40),
    'quad':     (6.30, 5.40),
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

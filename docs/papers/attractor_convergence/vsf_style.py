"""vsf_style.py — Shared matplotlib style for VSF attractor_convergence paper."""

import matplotlib
import matplotlib.pyplot as plt

# ── Color palette — matplotlib tab10 colorblind-safe subset ──────────────────
C = {
    'blue':   '#1f77b4',   # primary data / condition A / free system
    'orange': '#ff7f0e',   # interventions / secondary metric / accent
    'green':  '#2ca02c',   # stasis_cos / viability / healthy state
    'red':    '#d62728',   # stress / limit / condition B / alert
    'purple': '#9467bd',   # trust / governance layer
    'gray':   '#7f7f7f',   # reference lines / equilibrium
    'teal':   '#17becf',   # auxiliary / fourth series
}

# ── Base palette — capstone figures and forward ──────────────────────────────
# Strategy: B&W + grays as structure; color only as support for 1-2 key elements.
#   Distinguish series via line weight + dash pattern, not hue.
#   Use C['orange']/C['red'] to highlight ONE binding/failing element per figure.
#   Use C['blue']/C['green'] only when a color axis carries explicit semantics.
C_MONO = {
    'k0':    '#1a1a1a',   # near-black — primary / binding
    'k1':    '#4a4a4a',   # dark gray — secondary
    'k2':    '#858585',   # mid gray — tertiary / reference lines
    'k3':    '#b8b8b8',   # light gray — background elements
    'fill':  '#ebebeb',   # very light gray — fills / shadows
    'accent':'#2171b5',   # single accent blue — one key element only
}

# ── Standard figure sizes (width × height, inches) ───────────────────────────
FS = {
    'single': (6.5, 4.0),    # single panel
    'wide':   (9.0, 4.0),    # two panels side-by-side
    'tall':   (8.0, 5.5),    # two panels stacked
    'quad':   (10, 6),       # four panels stacked (compact)
    'comp3':  (10, 8),       # three-panel composite
}

# ── Publication rcParams ──────────────────────────────────────────────────────
RC = {
    'font.family':         'serif',
    'font.size':           10,
    'axes.labelsize':      11,
    'axes.titlesize':      11,
    'xtick.labelsize':     9,
    'ytick.labelsize':     9,
    'legend.fontsize':     9,
    'figure.dpi':          150,
    'savefig.dpi':         300,
    'savefig.bbox':        'tight',
    'savefig.pad_inches':  0.05,
    'axes.spines.top':     False,
    'axes.spines.right':   False,
    'axes.grid':           True,
    'grid.alpha':          0.25,
    'grid.linewidth':      0.5,
    'lines.linewidth':     1.5,
    'text.usetex':         False,
}


def apply():
    """Apply VSF publication style globally."""
    matplotlib.rcParams.update(RC)


def hline(ax, y, label=None, color=None, ls='--', lw=0.9):
    """Horizontal reference line with consistent styling."""
    ax.axhline(y, color=color or C['gray'], lw=lw, ls=ls, label=label, zorder=1)

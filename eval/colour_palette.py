"""Colorblind-friendly colour palette for all evaluation plots.

Uses the Wong (2011) palette, which is designed to be distinguishable
by people with the most common forms of colour vision deficiency
(deuteranopia, protanopia, tritanopia).

Reference
---------
Wong, B. (2011). Points of view: Color blindness.
*Nature Methods*, 8(6), 441.
"""

# ── Wong palette (hex) ─────────────────────────────────────────────
BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"       # bluish-green
VERMILLION = "#D55E00"
PURPLE = "#CC79A7"      # reddish-purple
SKY_BLUE = "#56B4E9"
YELLOW = "#F0E442"
BLACK = "#000000"

# ── Categorical colour cycle (for strategy scatter, etc.) ──────────
CATEGORY_CYCLE = [BLUE, ORANGE, GREEN, VERMILLION, PURPLE, SKY_BLUE, YELLOW]

# ── Gantt / timeline charts ────────────────────────────────────────
GANTT_INITIAL = BLUE
GANTT_RESCHEDULE = ORANGE
GANTT_NEW = GREEN
GANTT_CONNECTOR = VERMILLION

# ── Staff heatmap (discrete legend) ───────────────────────────────
HEATMAP_NONE = "white"
HEATMAP_INITIAL = BLUE
HEATMAP_TARGET = ORANGE
HEATMAP_BOTH = PURPLE
# 5th entry required by BoundaryNorm (value 4 is not currently assigned
# in the matrix but the norm expects ncolors=5).
HEATMAP_DISCRETE = [HEATMAP_NONE, HEATMAP_INITIAL, HEATMAP_TARGET,
                     HEATMAP_BOTH, VERMILLION]

# ── Bar charts ─────────────────────────────────────────────────────
BAR_PRIMARY = BLUE          # solve-time bar
BAR_SECONDARY = ORANGE      # Gini bar
BAR_MIN = GREEN             # staff load – min
BAR_MEDIAN = BLUE           # staff load – median
BAR_MAX = VERMILLION        # staff load – max
BAR_INFEASIBLE = VERMILLION # infeasibility – true infeasible
BAR_TIMEOUT = ORANGE        # infeasibility – timeout

# ── Sequential colormaps (already colorblind-safe) ────────────────
CMAP_SEQUENTIAL = "viridis"

# ── Diverging colormaps (colorblind-safe replacement for coolwarm) ─
CMAP_DIVERGING = "PuOr"

# ── Heatmap colormaps (colorblind-safe replacement for YlOrRd) ────
CMAP_HEATMAP = "viridis"


def apply_colorblind_cycle():
    """Set matplotlib's default colour cycle to :data:`CATEGORY_CYCLE`.

    Call once before generating plots so that *every* plot – including
    those without explicit ``color=`` arguments – uses the
    colorblind-friendly palette automatically.
    """
    import matplotlib.pyplot as plt
    from cycler import cycler

    plt.rcParams["axes.prop_cycle"] = cycler(color=CATEGORY_CYCLE)


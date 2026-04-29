"""Nord-inspired design tokens for terminal rendering."""
# DX sprint test

# ─── Palette (Nord-inspired) ────────────────────────────────────────
# Not exported. Only used to define tokens below.

_POLAR_NIGHT = "#4c566a"
_SNOW_DIM = "#d8dee9"
_SNOW = "#e5e9f0"
_FROST_A = "#88c0d0"
_FROST_B = "#81a1c1"
_RED = "#bf616a"
_ORANGE = "#d08770"
_YELLOW = "#ebcb8b"
_GREEN = "#a3be8c"
_PURPLE = "#b48ead"

# ─── Text tokens ────────────────────────────────────────────────────

TEXT = _SNOW  # primary text (labels, names)
TEXT_MUTED = _POLAR_NIGHT  # secondary info, separators, timestamps
TEXT_DIM = _SNOW_DIM  # table cell values, descriptions

# ─── Semantic status ────────────────────────────────────────────────

SUCCESS = _GREEN
ERROR = _RED
WARNING = _ORANGE
INFO = _FROST_A

# ─── Build-specific ─────────────────────────────────────────────────

COST = _YELLOW  # dollar amounts
CACHE_GOOD = _GREEN  # cache ≥ threshold
CACHE_LOW = _YELLOW  # cache < threshold
ACCENT = _FROST_A  # interactive / highlighted values
ACCENT_ALT = _FROST_B  # secondary accent (links, hover)
SEPARATOR = _POLAR_NIGHT  # · dividers, borders, rules
COMMIT_SHA = f"{_FROST_A} dim"  # git sha display
INSERTION = f"{_GREEN} dim"
DELETION = f"{_RED} dim"

# ─── Model tiers ────────────────────────────────────────────────────

MODEL_OPUS = f"{_PURPLE} bold"
MODEL_SONNET = f"{_FROST_A} bold"
MODEL_HAIKU = f"{_GREEN} bold"

MODEL_STYLES: dict[str, str] = {
    "opus": MODEL_OPUS,
    "sonnet": MODEL_SONNET,
    "haiku": MODEL_HAIKU,
}

# ─── Phase status ───────────────────────────────────────────────────

PHASE_DONE = _GREEN
PHASE_FAILED = _RED
PHASE_ACTIVE = _YELLOW
PHASE_PENDING = _POLAR_NIGHT
PHASE_SKIPPED = _POLAR_NIGHT

# ─── Feature status (for tables) ────────────────────────────────────

STATUS_STYLES: dict[str, str] = {
    "pending": TEXT_MUTED,
    "planning": ACCENT,
    "plan_review": ACCENT,
    "in_progress": _YELLOW,
    "implementing": _YELLOW,
    "reviewing": _FROST_B,
    "fixing": _PURPLE,
    "gate": _FROST_B,
    "done": _GREEN,
    "blocked": _RED,
    "failed": f"{_RED} bold",
    "skipped": TEXT_MUTED,
}


def m(token: str, text: str) -> str:
    """Wrap *text* in Rich inline markup using a theme token."""
    return f"[{token}]{text}[/{token}]"

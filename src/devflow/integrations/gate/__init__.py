"""Quality gate package — public façade.

Exposes only the high-level operations callers need.  Implementation
details (parsers, secret patterns, stack-specific checks…) live in
submodules and must be imported from there directly when needed in tests.

``render_gate_report`` lives in ``devflow.ui.gate_panel`` — import it
from there to avoid circular imports.
"""

from __future__ import annotations

# Backwards-compat re-export — the test suite still imports STACK_CHECKS
# from this façade.  Internal modules should import from .checks directly.
from devflow.integrations.gate.checks import STACK_CHECKS  # noqa: F401
from devflow.integrations.gate.context import GateContext, build_context
from devflow.integrations.gate.report import CheckResult, GateReport
from devflow.integrations.gate.runner import run_gate, run_gate_phase

__all__ = [
    "CheckResult",
    "GateContext",
    "GateReport",
    "build_context",
    "run_gate",
    "run_gate_phase",
]

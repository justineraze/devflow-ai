"""Quality gate package — facade re-exporting public names.

Consumers can continue to import from ``devflow.integrations.gate`` without
any changes after the gate.py monolith was split into focused submodules.

``render_gate_report`` now lives in ``devflow.ui.gate_panel`` — import it
from there directly (not from this facade) to avoid circular imports.
"""

from devflow.integrations.gate.checks import STACK_CHECKS
from devflow.integrations.gate.report import CheckDef, CheckResult, GateReport, ParseOutput
from devflow.integrations.gate.runner import run_gate, run_gate_phase
from devflow.integrations.gate.secrets import (
    SECRET_PATTERNS,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    scan_secrets,
)

__all__ = [
    "CheckResult",
    "GateReport",
    "CheckDef",
    "ParseOutput",
    "STACK_CHECKS",
    "SECRET_PATTERNS",
    "SKIP_EXTENSIONS",
    "SKIP_DIRS",
    "scan_secrets",
    "run_gate",
    "run_gate_phase",
]

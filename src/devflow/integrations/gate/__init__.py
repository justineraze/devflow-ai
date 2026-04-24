"""Quality gate package — facade re-exporting public names.

Consumers can continue to import from ``devflow.integrations.gate`` without
any changes after the gate.py monolith was split into focused submodules.

``render_gate_report`` now lives in ``devflow.ui.gate_panel`` — import it
from there directly (not from this facade) to avoid circular imports.
"""

from devflow.integrations.gate.checks import STACK_CHECKS
from devflow.integrations.gate.complexity import check_complexity
from devflow.integrations.gate.config import load_gate_config
from devflow.integrations.gate.context import GateContext, build_context
from devflow.integrations.gate.module_size import check_module_size
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
    "GateContext",
    "GateReport",
    "build_context",
    "load_gate_config",
    "CheckDef",
    "ParseOutput",
    "STACK_CHECKS",
    "SECRET_PATTERNS",
    "SKIP_EXTENSIONS",
    "SKIP_DIRS",
    "check_complexity",
    "check_module_size",
    "scan_secrets",
    "run_gate",
    "run_gate_phase",
]

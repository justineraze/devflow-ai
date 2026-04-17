"""Quality gate package — facade re-exporting all public names.

Consumers can continue to import from ``devflow.integrations.gate`` without
any changes after the gate.py monolith was split into focused submodules.
"""

from devflow.integrations.gate.checks import (
    STACK_CHECKS,
    _checks_for_stack,
    _parse_pytest,
    _run_command_check,
)
from devflow.integrations.gate.report import CheckDef, CheckResult, GateReport, ParseOutput
from devflow.integrations.gate.runner import run_gate, run_gate_phase
from devflow.integrations.gate.secrets import (
    SECRET_PATTERNS,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    scan_secrets,
)

# render_gate_report lives in ui.gate_panel — re-exported here for backward compat.
from devflow.ui.gate_panel import render_gate_report

__all__ = [
    # report
    "CheckResult",
    "GateReport",
    "CheckDef",
    "ParseOutput",
    # checks
    "STACK_CHECKS",
    "_checks_for_stack",
    "_parse_pytest",
    "_run_command_check",
    # secrets
    "SECRET_PATTERNS",
    "SKIP_EXTENSIONS",
    "SKIP_DIRS",
    "scan_secrets",
    # runner
    "run_gate",
    "run_gate_phase",
    # ui (backward compat)
    "render_gate_report",
]

"""Re-exports from ``devflow.core.gate_report``.

The canonical definitions now live in ``core/gate_report`` to avoid
cross-layer import violations (ui/ and setup/ need these types but
must not import from integrations/).  This module re-exports them so
existing ``integrations.gate`` consumers keep working without changes.
"""

from __future__ import annotations

from devflow.core.gate_report import (  # noqa: F401
    CheckDef,
    CheckResult,
    GateReport,
    ParseOutput,
)

__all__ = [
    "CheckDef",
    "CheckResult",
    "GateReport",
    "ParseOutput",
]

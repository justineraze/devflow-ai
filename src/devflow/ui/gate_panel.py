"""Rich rendering for the quality gate report."""

from __future__ import annotations

from pathlib import Path

from rich.panel import Panel
from rich.text import Text

from devflow.core.artifacts import read_json_artifact
from devflow.core.console import console
from devflow.core.gate_report import CheckResult, GateReport


def render_gate_report(report: GateReport) -> None:
    """Render the quality gate as a Rich panel with per-check details.

    Three states per check:
    - passed → green ✓
    - skipped (tool missing, etc.) → yellow ⚠ (does not fail the gate)
    - failed → red ✗
    """
    body = Text()
    for idx, check in enumerate(report.checks):
        if check.skipped:
            icon, icon_style, name_style, msg_style = (
                "⚠", "yellow bold", "yellow", "yellow",
            )
        elif check.passed:
            icon, icon_style, name_style, msg_style = (
                "✓", "green bold", "white", "dim",
            )
        else:
            icon, icon_style, name_style, msg_style = (
                "✗", "red bold", "red", "red",
            )

        if idx:
            body.append("\n")
        body.append(f"  {icon}  ", style=icon_style)
        body.append(check.name.ljust(10), style=f"bold {name_style}")
        body.append(check.message, style=msg_style)

        if not check.passed and not check.skipped and check.details:
            for detail in check.details.split("\n")[:8]:
                if detail.strip():
                    body.append(f"\n       {detail[:200]}", style="dim red")

    if not report.passed:
        verdict, verdict_style, border = "FAILED", "reverse red bold", "red"
    elif report.has_skipped:
        verdict, verdict_style, border = (
            "PASSED (with skipped)", "reverse yellow bold", "yellow",
        )
    else:
        verdict, verdict_style, border = "PASSED", "reverse green bold", "green"

    subtitle = Text("custom (.devflow/gate.yaml)", style="dim") if report.custom else None
    console.print(Panel(
        body,
        title=Text(f" Gate — {verdict} ", style=verdict_style),
        subtitle=subtitle,
        border_style=border,
        padding=(1, 2),
    ))


def render_gate_panel(feature_id: str, base: Path | None = None) -> None:
    """Load gate.json from artifacts and render it as a Rich panel."""
    data = read_json_artifact(feature_id, "gate.json", base)
    if not data:
        return

    report = GateReport(
        checks=[
            CheckResult(
                name=c.get("name", "?"),
                passed=bool(c.get("passed", False)),
                skipped=bool(c.get("skipped", False)),
                message=c.get("message", ""),
                details=c.get("details", ""),
            )
            for c in data.get("checks", [])
        ],
        custom=bool(data.get("custom", False)),
    )
    render_gate_report(report)

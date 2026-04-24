"""Feature complexity scoring — score → workflow mapping.

The :class:`ComplexityScore` is computed at feature creation time
(see :mod:`devflow.integrations.complexity`) and persisted in
``feature.metadata.complexity``.  The workflow name is resolved once
at construction and stored as a plain field so it survives JSON
round-trips even if the thresholds change later.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

# Workflow selection thresholds for ComplexityScore.total (0–12).
_WORKFLOW_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (2, "quick"),
    (5, "light"),
    (8, "standard"),
    (12, "full"),
)


def _resolve_workflow(total: int) -> str:
    """Map a complexity total (0–12) to a workflow name."""
    for threshold, name in _WORKFLOW_THRESHOLDS:
        if total <= threshold:
            return name
    return "full"


class ComplexityScore(BaseModel):
    """Complexity score for a feature across four dimensions (each 0–3).

    ``workflow`` is resolved once at construction time and stored as a plain
    field so it survives JSON round-trips and never drifts if thresholds change.
    """

    files_touched: int = Field(default=0, ge=0, le=3)
    """Number of files expected to be modified (heuristic, 0–3)."""

    integrations: int = Field(default=0, ge=0, le=3)
    """External systems involved: API, DB, webhook, OAuth… (0–3)."""

    security: int = Field(default=0, ge=0, le=3)
    """Security-sensitive surface area: auth, tokens, crypto… (0–3)."""

    scope: int = Field(default=0, ge=0, le=3)
    """Breadth of the change: tweak vs. new module vs. rewrite (0–3)."""

    workflow: str = ""
    """Workflow resolved from total at construction time (never recomputed)."""

    method: str = ""
    """How the score was produced: ``"llm"`` or ``"heuristic"`` (empty = unknown)."""

    def model_post_init(self, _context: object) -> None:
        """Resolve workflow from total once, at construction time."""
        if not self.workflow:
            self.workflow = _resolve_workflow(self.total)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        """Sum of all four dimension scores (0–12)."""
        return self.files_touched + self.integrations + self.security + self.scope


__all__ = ["ComplexityScore"]

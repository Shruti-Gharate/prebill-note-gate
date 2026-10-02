"""Auditable pre-bill gate for synthetic visit notes."""

from .pipeline import gate_encounter, evaluate

__all__ = ["gate_encounter", "evaluate"]

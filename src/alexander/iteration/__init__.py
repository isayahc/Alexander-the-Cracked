"""iteration subpackage: the bounded build-evaluate-iterate loop.

`run_iteration_loop` drives a ProjectBuilder through budgeted rounds of
build → independent evaluation, snapshots the best-known passing result, and
persists a manifest of evaluations, costs, and stop reason next to the build.
"""

from alexander.iteration.evaluate import Evaluation, evaluate_project
from alexander.iteration.loop import IterationBudgets, run_iteration_loop
from alexander.iteration.models import (
    CheckRecord,
    CheckStatus,
    IterationManifest,
    IterationRecord,
    StopReason,
    best_known_dir_for,
    manifest_path_for,
)

__all__ = [
    "CheckRecord",
    "CheckStatus",
    "Evaluation",
    "IterationBudgets",
    "IterationManifest",
    "IterationRecord",
    "StopReason",
    "best_known_dir_for",
    "evaluate_project",
    "manifest_path_for",
    "run_iteration_loop",
]

"""What every screen step needs: the workbench, OCR for grids, and the run log."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from image_to_cash.drive.fakturama.workbench import Workbench
from image_to_cash.drive.report import Outcome, RunLog
from image_to_cash.ocr.base import OcrEngine


@dataclass(frozen=True)
class Context:
    wb: Workbench
    ocr: OcrEngine
    log: RunLog
    sleep: Callable[[float], None] = field(default=time.sleep)

    @property
    def ui(self):
        return self.wb.ui

    def record(self, step: str, outcome: Outcome, **details: str) -> None:
        self.log.record(step, outcome, **details)

"""CSV output with metadata header for experiment results."""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path


class ExperimentCSV:
    """Write experiment results to a CSV file with a metadata comment header."""

    def __init__(
        self,
        path: str | Path,
        columns: list[str],
        metadata: dict[str, str] | None = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._columns = columns
        self._file = open(self.path, "w", newline="")

        # Write metadata as comment lines
        self._file.write(f"# generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        for k, v in (metadata or {}).items():
            self._file.write(f"# {k}: {v}\n")

        self._writer = csv.DictWriter(self._file, fieldnames=columns)
        self._writer.writeheader()
        self._count = 0

    def write_row(self, **kwargs) -> None:
        self._writer.writerow(kwargs)
        self._count += 1
        # Flush periodically so partial results are visible
        if self._count % 20 == 0:
            self._file.flush()

    def close(self) -> None:
        self._file.flush()
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

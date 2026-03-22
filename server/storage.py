"""In-memory storage layer for datasets and sessions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .models import DatasetInfo, IndexStatus, Session


class Storage:
    def __init__(self, dataset_root: str = "dataset"):
        self.dataset_root = Path(dataset_root)
        self.datasets: dict[str, DatasetInfo] = {}
        self.sessions: dict[str, Session] = {}
        self._scan_datasets()

    def _scan_datasets(self) -> None:
        if not self.dataset_root.exists():
            return
        for d in sorted(self.dataset_root.iterdir()):
            if not d.is_dir():
                continue
            graph_file = d / f"{d.name}.graph"
            if not graph_file.exists():
                continue
            info = self._parse_dataset(d.name, graph_file)
            self.datasets[info.id] = info

    def _parse_dataset(self, name: str, graph_file: Path) -> DatasetInfo:
        num_v, num_e = 0, 0
        labels: set[int] = set()
        try:
            with open(graph_file, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    if parts[0] == "t":
                        num_v = int(parts[1])
                        num_e = int(parts[2])
                    elif parts[0] == "v" and len(parts) >= 3:
                        labels.add(int(parts[2]))
        except Exception:
            pass

        index_dir = self.dataset_root / name / "index"
        index_status = self._check_index_status(index_dir)

        return DatasetInfo(
            id=name,
            name=name,
            num_vertices=num_v,
            num_edges=num_e,
            labels=sorted(labels),
            index_status=index_status,
            index_artifact_path=str(index_dir) if index_dir.exists() else "",
        )

    def _check_index_status(self, index_dir: Path) -> IndexStatus:
        if not index_dir.exists():
            return IndexStatus.MISSING
        required = ["graph.bin", "triangles.bin", "four_cycles.bin"]
        for f in required:
            if not (index_dir / f).exists():
                return IndexStatus.MISSING
        return IndexStatus.READY

    def get_datasets(self) -> list[DatasetInfo]:
        return list(self.datasets.values())

    def get_dataset(self, dataset_id: str) -> DatasetInfo | None:
        return self.datasets.get(dataset_id)

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def create_session(self, session: Session) -> None:
        self.sessions[session.session_id] = session

    def update_session(self, session: Session) -> None:
        self.sessions[session.session_id] = session

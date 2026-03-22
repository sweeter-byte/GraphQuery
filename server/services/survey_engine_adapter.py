"""
Survey Engine Adapter.

Invokes the SubgraphMatchingSurvey binary as a subprocess to perform actual
subgraph matching enumeration. Parses stdout to extract embedding count,
timing, and other metrics.

This serves as the downstream execution engine, used after the FaSTest
cardinality estimator has ranked candidate expansion orders.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
exec_log = logging.getLogger("gq.execution")

# Default binary location under the vendored engine tree.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BINARY = str(
    _PROJECT_ROOT
    / "core"
    / "engines"
    / "SubgraphMatchingSurvey"
    / "vlabel"
    / "build"
    / "matching"
    / "SubgraphMatching.out"
)


class SurveyEngineAdapter:
    """
    Adapter for the SubgraphMatchingSurvey enumeration engine.

    Invokes the binary via ``subprocess.run()`` and parses structured
    output from stdout.
    """

    # Regex patterns for parsing stdout
    _RE_EMBEDDINGS = re.compile(r"#Embeddings:\s*(\d+)")
    _RE_TOTAL_TIME = re.compile(r"Total time \(seconds\):\s*([\d.]+)")
    _RE_ENUM_TIME = re.compile(r"Enumerate time \(seconds\):\s*([\d.]+)")
    _RE_FILTER_TIME = re.compile(r"Filter vertices time \(seconds\):\s*([\d.]+)")
    _RE_BUILD_TABLE_TIME = re.compile(r"Build table time \(seconds\):\s*([\d.]+)")
    _RE_PLAN_TIME = re.compile(r"Generate query plan time \(seconds\):\s*([\d.]+)")
    _RE_LOAD_TIME = re.compile(r"Load graphs time \(seconds\):\s*([\d.]+)")
    _RE_PREPROCESS_TIME = re.compile(r"Preprocessing time \(seconds\):\s*([\d.]+)")
    _RE_MEMORY = re.compile(r"Memory cost \(MB\):\s*([\d.]+)")
    _RE_CALL_COUNT = re.compile(r"Call Count:\s*(\d+)")

    def __init__(
        self,
        binary_path: str | None = None,
        default_filter: str = "CFL",
        default_order: str = "GQL",
        default_engine: str = "LFTJ",
    ) -> None:
        if binary_path is None:
            binary_path = os.path.normpath(_DEFAULT_BINARY)
        self.binary_path = binary_path
        self.default_filter = default_filter
        self.default_order = default_order
        self.default_engine = default_engine

        if not Path(self.binary_path).is_file():
            logger.warning(
                "Survey binary not found at %s. "
                "Build it with: cd core/engines/SubgraphMatchingSurvey/vlabel/build && cmake .. && make -j$(nproc)",
                self.binary_path,
            )

    @property
    def is_available(self) -> bool:
        """Check whether the binary is present and executable."""
        p = Path(self.binary_path)
        return p.is_file() and os.access(str(p), os.X_OK)

    def _build_subprocess_env(self) -> dict[str, str]:
        """Ensure relocated build artifacts can still resolve shared libraries."""
        env = os.environ.copy()

        binary_path = Path(self.binary_path).resolve()
        build_root = binary_path.parent.parent
        lib_dirs = [
            build_root / "graph",
            build_root / "utility",
            build_root / "utility" / "nucleus_decomposition",
            build_root / "utility" / "execution_tree",
        ]

        existing = env.get("LD_LIBRARY_PATH", "")
        entries = [str(path) for path in lib_dirs if path.is_dir()]
        if existing:
            entries.append(existing)
        if entries:
            env["LD_LIBRARY_PATH"] = ":".join(entries)

        return env

    def execute(
        self,
        data_graph_path: str,
        query_graph_path: str,
        *,
        max_embeddings: int = 100000,
        time_limit: int = 60,
        filter_type: str | None = None,
        order_type: str | None = None,
        engine_type: str | None = None,
        custom_order: list[int] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """
        Execute subgraph matching on the given data/query graph pair.

        Parameters
        ----------
        data_graph_path : str
            Path to the data graph file (`.graph` format).
        query_graph_path : str
            Path to the query graph file (`.graph` format).
        max_embeddings : int
            Maximum number of embeddings to enumerate.
        time_limit : int
            Time limit in seconds for the enumeration phase.
        filter_type : str or None
            Candidate filtering algorithm. Default: CFL.
            Options: LDF, NLF, GQL, TSO, CFL, DPiso, VEQ, CECI, RM, CaLiG
        order_type : str or None
            Matching order generation algorithm. Default: GQL.
            Options: QSI, GQL, TSO, CFL, DPiso, CECI, RI, VF2PP, VF3, RM
        engine_type : str or None
            Enumeration engine. Default: LFTJ.
            Options: EXPLORE, LFTJ, GQL, QSI, VF3, VEQ, DPiso, RM, KSS, CECI
        custom_order : list[int] or None
            Explicit query vertex order to execute. When provided, overrides
            ``order_type`` and is passed to Survey as ``-order CUSTOM`` plus
            a temporary ``-order_file``.
        timeout : int or None
            Subprocess timeout in seconds. Defaults to time_limit + 30.

        Returns
        -------
        dict
            Keys: embedding_count, total_time_seconds, enumeration_time_seconds,
            filter_time_seconds, build_table_time_seconds, plan_time_seconds,
            load_time_seconds, preprocessing_time_seconds, memory_mb,
            call_count, eps, stdout, returncode, timed_out
        """
        if not self.is_available:
            raise FileNotFoundError(
                f"Survey binary not found or not executable: {self.binary_path}"
            )

        ft = filter_type or self.default_filter
        ot = "CUSTOM" if custom_order is not None else (order_type or self.default_order)
        et = engine_type or self.default_engine

        order_file_path: str | None = None
        if custom_order is not None:
            fd, order_file_path = tempfile.mkstemp(prefix="survey_order_", suffix=".txt")
            os.close(fd)
            Path(order_file_path).write_text(" ".join(str(v) for v in custom_order) + "\n")

        cmd = [
            self.binary_path,
            "-d", str(data_graph_path),
            "-q", str(query_graph_path),
            "-filter", ft,
            "-order", ot,
            "-engine", et,
            "-num", str(max_embeddings),
            "-time_limit", str(time_limit),
        ]
        if order_file_path is not None:
            cmd.extend(["-order_file", order_file_path])

        if timeout is None:
            timeout = time_limit + 30

        try:
            exec_log.info(
                "SURVEY_EXEC_START | cmd=%s | timeout=%ds",
                " ".join(cmd), timeout,
            )
            timed_out = False
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=self._build_subprocess_env(),
                )
                stdout = proc.stdout
                returncode = proc.returncode
            except subprocess.TimeoutExpired as e:
                timed_out = True
                stdout = e.stdout or ""
                if isinstance(stdout, bytes):
                    stdout = stdout.decode("utf-8", errors="replace")
                returncode = -1
                exec_log.warning(
                    "SURVEY_EXEC_TIMEOUT | timeout=%ds | partial_stdout_len=%d",
                    timeout, len(stdout),
                )

            result = self._parse_output(stdout)
            result["returncode"] = returncode
            result["timed_out"] = timed_out
            result["stdout"] = stdout
            if custom_order is not None:
                result["custom_order"] = list(custom_order)

            total_t = result.get("total_time_seconds", 0.0)
            emb = result.get("embedding_count", 0)
            if total_t > 0:
                result["eps"] = emb / total_t
            else:
                result["eps"] = 0.0

            exec_log.info(
                "SURVEY_EXEC_DONE | embeddings=%s | total_time=%.4fs | "
                "enum_time=%.4fs | eps=%.2f | returncode=%d | timed_out=%s",
                result.get("embedding_count"), total_t,
                result.get("enumeration_time_seconds", 0.0),
                result.get("eps", 0.0),
                returncode, timed_out,
            )

            return result
        finally:
            if order_file_path and os.path.exists(order_file_path):
                os.remove(order_file_path)

    def _parse_output(self, stdout: str) -> dict[str, Any]:
        """Parse all metrics from the Survey binary stdout."""
        result: dict[str, Any] = {}

        def _extract_int(pattern: re.Pattern, text: str) -> int | None:
            m = pattern.search(text)
            return int(m.group(1)) if m else None

        def _extract_float(pattern: re.Pattern, text: str) -> float | None:
            m = pattern.search(text)
            return float(m.group(1)) if m else None

        result["embedding_count"] = _extract_int(self._RE_EMBEDDINGS, stdout) or 0
        result["total_time_seconds"] = _extract_float(self._RE_TOTAL_TIME, stdout) or 0.0
        result["enumeration_time_seconds"] = _extract_float(self._RE_ENUM_TIME, stdout) or 0.0
        result["filter_time_seconds"] = _extract_float(self._RE_FILTER_TIME, stdout) or 0.0
        result["build_table_time_seconds"] = _extract_float(self._RE_BUILD_TABLE_TIME, stdout) or 0.0
        result["plan_time_seconds"] = _extract_float(self._RE_PLAN_TIME, stdout) or 0.0
        result["load_time_seconds"] = _extract_float(self._RE_LOAD_TIME, stdout) or 0.0
        result["preprocessing_time_seconds"] = _extract_float(self._RE_PREPROCESS_TIME, stdout) or 0.0
        result["memory_mb"] = _extract_float(self._RE_MEMORY, stdout) or 0.0
        result["call_count"] = _extract_int(self._RE_CALL_COUNT, stdout) or 0

        return result


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_engine_instance: SurveyEngineAdapter | None = None


def get_survey_engine(binary_path: str | None = None) -> SurveyEngineAdapter:
    """Get (or create) the global SurveyEngineAdapter singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SurveyEngineAdapter(binary_path=binary_path)
    return _engine_instance

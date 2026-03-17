"""Pydantic data models for the Graph Query Planning System."""
from __future__ import annotations

import enum
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Configuration Models
# =============================================================================

class ScheduleConfig(BaseModel):
    mode: str = "auto"
    python_threads: int = 4
    omp_threads: int = 4

# =============================================================================
# Graph Models
# =============================================================================

class Vertex(BaseModel):
    id: int
    label: int = 0


class Edge(BaseModel):
    id: int | None = None
    source: int
    target: int
    label: int = 0


class QueryGraph(BaseModel):
    vertices: list[Vertex]
    edges: list[Edge]

    @field_validator("vertices")
    @classmethod
    def vertices_non_empty(cls, v: list[Vertex]) -> list[Vertex]:
        if not v:
            raise ValueError("vertices must not be empty")
        return v

    @field_validator("edges")
    @classmethod
    def edges_non_empty(cls, v: list[Edge]) -> list[Edge]:
        if not v:
            raise ValueError("edges must not be empty")
        return v


class NormalizedGraph(BaseModel):
    """Query graph after vertex-ID normalization to 0..n-1."""
    num_vertices: int
    num_edges: int
    vertices: list[Vertex]
    edges: list[Edge]
    vertex_id_mapping: dict[int, int] = Field(
        default_factory=dict,
        description="original_id -> normalized_id",
    )


# =============================================================================
# Prefix Subgraph Payload (passed to C++ via pybind11)
# =============================================================================

class PrefixPayload(BaseModel):
    num_vertices: int
    num_edges: int
    vertices: list[Vertex]
    edges: list[Edge]

    def to_dict(self) -> dict:
        return {
            "num_vertices": self.num_vertices,
            "num_edges": self.num_edges,
            "vertices": [{"id": v.id, "label": v.label} for v in self.vertices],
            "edges": [{"source": e.source, "target": e.target, "label": e.label} for e in self.edges],
        }


# =============================================================================
# Dataset Models
# =============================================================================

class IndexStatus(str, enum.Enum):
    READY = "ready"
    MISSING = "missing"
    STALE = "stale"
    UNKNOWN = "unknown"


class DatasetInfo(BaseModel):
    id: str
    name: str
    num_vertices: int = 0
    num_edges: int = 0
    labels: list[int] = Field(default_factory=list)
    index_status: IndexStatus = IndexStatus.UNKNOWN
    index_artifact_path: str = ""
    index_version: str = ""
    index_built_at: str = ""


# =============================================================================
# Session Models
# =============================================================================

class SessionStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OrderState(BaseModel):
    order_id: int
    order: list[int]
    prefix_index: int = 0
    score: float = 0.0
    prefix_estimates: list[float] = Field(default_factory=list)
    status: str = "pending"  # pending | evaluating | done


class SessionCreateRequest(BaseModel):
    dataset_id: str
    query_graph: QueryGraph
    beam_width: int | None = None  # None = exact mode
    order_strategy: str = "baseline"  # "baseline" | "pruned"
    schedule_config: Optional[ScheduleConfig] = None
    run_execution: bool = False  # Run downstream matching engine after scoring
    execution_config: Optional[dict] = None  # filter/order/engine/time_limit overrides


class SessionCreateResponse(BaseModel):
    session_id: str
    status: SessionStatus
    stream_url: str


class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    dataset_id: str = ""
    query_graph: QueryGraph | None = None
    normalized_graph: NormalizedGraph | None = None
    status: SessionStatus = SessionStatus.QUEUED
    beam_width: int | None = None
    order_strategy: str = "baseline"  # "baseline" | "pruned"
    orders: list[OrderState] = Field(default_factory=list)
    best_order_id: int | None = None
    best_score: float | None = None
    schedule_config: Optional[ScheduleConfig] = None
    run_execution: bool = False  # Whether to run downstream matching engine
    execution_config: Optional[dict] = None  # Execution engine overrides
    execution_result: Optional[dict] = None  # Downstream engine results
    error: dict[str, Any] | None = None
    created_at: float = Field(default_factory=time.time)
    completed_at: float | None = None


# =============================================================================
# SSE Event Models
# =============================================================================

class SSEEvent(BaseModel):
    event: str
    data: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Error Response
# =============================================================================

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])

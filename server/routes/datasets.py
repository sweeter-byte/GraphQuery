"""Dataset API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import DatasetInfo
from ..storage import Storage

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

# Injected at app startup
_storage: Storage | None = None


def init_router(storage: Storage) -> None:
    global _storage
    _storage = storage


def _get_storage() -> Storage:
    if _storage is None:
        raise HTTPException(status_code=500, detail="Storage not initialized")
    return _storage


@router.get("", response_model=list[DatasetInfo])
async def list_datasets():
    """Return all registered datasets with index status."""
    return _get_storage().get_datasets()


@router.get("/{dataset_id}", response_model=DatasetInfo)
async def get_dataset(dataset_id: str):
    """Return details for a single dataset."""
    ds = _get_storage().get_dataset(dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return ds


@router.post("/load", status_code=202)
async def load_dataset(dataset_id: str):
    """Pre-load dataset index into memory."""
    from ..services.estimator_adapter import get_estimator_adapter
    
    ds = _get_storage().get_dataset(dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    
    adapter = get_estimator_adapter()
    # load_dataset is idempotent
    adapter.load_dataset(dataset_id)
    
    return {"status": "loading", "dataset_id": dataset_id}

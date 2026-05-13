"""Execution endpoints — trigger approved remediations."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from services.execution_engine import execute_approved

router = APIRouter(prefix="/execute", tags=["execution"])


class ExecuteRequest(BaseModel):
    approval_id: str


@router.post("")
async def execute(body: ExecuteRequest, db: AsyncSession = Depends(get_db)):
    """Execute an approved remediation."""
    result = await execute_approved(db, body.approval_id)
    if "error" in result and "not found" in result["error"].lower():
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{approval_id}")
async def execute_by_id(approval_id: str, db: AsyncSession = Depends(get_db)):
    """Execute an approved remediation by approval ID."""
    result = await execute_approved(db, approval_id)
    if "error" in result and "not found" in result["error"].lower():
        raise HTTPException(status_code=404, detail=result["error"])
    return result

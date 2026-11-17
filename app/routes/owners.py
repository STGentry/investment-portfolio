"""Owner endpoints."""

from fastapi import APIRouter, HTTPException

from database import db
from models import OwnerRead

router = APIRouter()


def _serialize_owner(row) -> OwnerRead:
    return OwnerRead(
        owner_id=row["owner_id"],
        name=row["name"],
        created_at=row["created_at"],
    )


@router.get("/owners", response_model=list[OwnerRead])
def list_owners() -> list[OwnerRead]:
    """List all owners."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM owners ORDER BY owner_id").fetchall()
    return [_serialize_owner(row) for row in rows]


@router.get("/owners/{owner_id}", response_model=OwnerRead)
def get_owner(owner_id: int) -> OwnerRead:
    """Get owner details by id."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM owners WHERE owner_id = ?", (owner_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Owner {owner_id} not found")
    return _serialize_owner(row)
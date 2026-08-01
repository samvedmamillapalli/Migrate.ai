from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import Prediction
from app.repositories.base import BaseRepository


class PredictionRepository(BaseRepository[Prediction]):
    model = Prediction

    async def get_by_migration_run_id(
        self,
        migration_run_id: uuid.UUID,
    ) -> Prediction | None:
        result = await self._session.execute(
            select(Prediction).where(Prediction.migration_run_id == migration_run_id)
        )
        return result.scalar_one_or_none()

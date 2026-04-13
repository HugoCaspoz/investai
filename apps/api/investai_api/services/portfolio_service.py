from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.investai_api.models import Position, PositionStatus, UserProfile
from apps.api.investai_api.schemas import PositionCreate


class PortfolioService:
    def register_position(self, session: Session, profile: UserProfile, payload: PositionCreate) -> Position:
        position = Position(
            profile_id=profile.id,
            symbol=payload.symbol.upper(),
            asset_type=payload.asset_type.value,
            entry_price=payload.entry_price,
            quantity=payload.quantity,
            thesis=payload.thesis,
            target_price=payload.target_price,
            stop_price=payload.stop_price,
            theme=payload.theme or self._pick_primary_theme(profile.theme_weights),
            status=PositionStatus.OPEN.value,
        )
        session.add(position)
        session.commit()
        session.refresh(position)
        return position

    def list_open_positions(self, session: Session, profile_id: int) -> list[Position]:
        statement = (
            select(Position)
            .where(Position.profile_id == profile_id)
            .where(Position.status == PositionStatus.OPEN.value)
            .order_by(Position.opened_at.desc())
        )
        return list(session.scalars(statement))

    def get_open_position_by_symbol(self, session: Session, profile_id: int, symbol: str) -> Position | None:
        statement = (
            select(Position)
            .where(Position.profile_id == profile_id)
            .where(Position.status == PositionStatus.OPEN.value)
            .where(Position.symbol == symbol.upper())
            .order_by(Position.opened_at.desc())
        )
        return session.scalar(statement)

    @staticmethod
    def render_positions(positions: list[Position]) -> str:
        if not positions:
            return "No hay posiciones abiertas."
        lines = ["Posiciones abiertas:"]
        for position in positions[:10]:
            qty_text = f", qty={position.quantity:g}" if position.quantity is not None else ""
            thesis_text = f" | tesis: {position.thesis}" if position.thesis else ""
            lines.append(f"- {position.symbol} a {position.entry_price:g}{qty_text}{thesis_text}")
        return "\n".join(lines)

    @staticmethod
    def _pick_primary_theme(theme_weights: dict[str, float]) -> str | None:
        if not theme_weights:
            return None
        return max(theme_weights.items(), key=lambda item: item[1])[0]

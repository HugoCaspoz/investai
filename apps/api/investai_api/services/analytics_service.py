from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.investai_api.models import (
    AssetType,
    PaperTrade,
    PaperTradeStatus,
    PositionCloseEvent,
    SignalOutcome,
    SignalOutcomeStatus,
    SignalType,
    UserProfile,
)
from apps.api.investai_api.schemas import AnalyticsBucketRead, PaperTradeRead, SignalAnalyticsRead, SignalOutcomeRead
from apps.api.investai_api.services.market_data_service import MarketDataService


class AnalyticsService:
    DEFAULT_HORIZON_HOURS = 24

    def __init__(self) -> None:
        self.market_data_service = MarketDataService()

    def register_buy_signal_outcome(
        self,
        session: Session,
        profile: UserProfile | None,
        signal_id: int | None,
        signal_type: SignalType,
        symbol: str,
        asset_type: AssetType,
        source: str,
        bucket: str | None,
        entry_price: float | None,
    ) -> SignalOutcome | None:
        if signal_id is None or entry_price is None or signal_type != SignalType.BUY:
            return None
        existing = session.scalar(select(SignalOutcome).where(SignalOutcome.signal_snapshot_id == signal_id))
        if existing:
            return existing
        outcome = SignalOutcome(
            signal_snapshot_id=signal_id,
            profile_id=profile.id if profile else None,
            symbol=symbol.upper(),
            asset_type=asset_type.value,
            source=source,
            bucket=bucket,
            signal_type=signal_type.value,
            entry_price=entry_price,
            evaluation_horizon_hours=self.DEFAULT_HORIZON_HOURS,
            status=SignalOutcomeStatus.PENDING.value,
        )
        session.add(outcome)
        session.commit()
        session.refresh(outcome)
        return outcome

    def open_paper_trade(
        self,
        session: Session,
        profile: UserProfile,
        signal_id: int | None,
        symbol: str,
        asset_type: AssetType,
        source: str,
        bucket: str | None,
        entry_price: float | None,
    ) -> PaperTrade | None:
        if signal_id is None or entry_price is None:
            return None
        existing = session.scalar(
            select(PaperTrade)
            .where(PaperTrade.profile_id == profile.id)
            .where(PaperTrade.symbol == symbol.upper())
            .where(PaperTrade.status == PaperTradeStatus.OPEN.value)
        )
        if existing:
            return existing
        trade = PaperTrade(
            profile_id=profile.id,
            open_signal_snapshot_id=signal_id,
            symbol=symbol.upper(),
            asset_type=asset_type.value,
            source=source,
            bucket=bucket,
            status=PaperTradeStatus.OPEN.value,
            entry_price=entry_price,
        )
        session.add(trade)
        session.commit()
        session.refresh(trade)
        return trade

    def list_open_paper_trades(self, session: Session, profile_id: int) -> list[PaperTrade]:
        return list(
            session.scalars(
                select(PaperTrade)
                .where(PaperTrade.profile_id == profile_id)
                .where(PaperTrade.status == PaperTradeStatus.OPEN.value)
                .order_by(PaperTrade.opened_at.asc())
            )
        )

    def close_paper_trade(
        self,
        session: Session,
        trade: PaperTrade,
        close_signal_snapshot_id: int | None,
        exit_price: float | None,
    ) -> PaperTrade | None:
        if exit_price is None:
            return None
        trade.close_signal_snapshot_id = close_signal_snapshot_id
        trade.exit_price = exit_price
        trade.return_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100 if trade.entry_price else None
        trade.status = PaperTradeStatus.CLOSED.value
        trade.closed_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(trade)
        return trade

    async def resolve_due_outcomes(self, session: Session) -> int:
        resolved = 0
        pending = list(
            session.scalars(
                select(SignalOutcome)
                .where(SignalOutcome.status == SignalOutcomeStatus.PENDING.value)
            )
        )
        now = datetime.now(timezone.utc)
        for outcome in pending:
            created_at = outcome.created_at
            if created_at is None:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at + timedelta(hours=outcome.evaluation_horizon_hours) > now:
                continue
            profile = session.get(UserProfile, outcome.profile_id) if outcome.profile_id else None
            if not profile:
                continue
            candidate = await self.market_data_service.fetch_live_candidate_for_symbol(
                profile,
                outcome.symbol,
                AssetType(outcome.asset_type),
            )
            if not candidate or candidate.current_price is None:
                continue
            return_pct = ((candidate.current_price - outcome.entry_price) / outcome.entry_price) * 100
            outcome.outcome_price = candidate.current_price
            outcome.return_pct = return_pct
            outcome.outcome_label = self._outcome_label(return_pct)
            outcome.status = SignalOutcomeStatus.RESOLVED.value
            outcome.evaluated_at = now
            resolved += 1
        if resolved:
            session.commit()
        return resolved

    def build_signal_analytics(self, session: Session, profile_id: int) -> SignalAnalyticsRead:
        outcomes = list(
            session.scalars(
                select(SignalOutcome)
                .where(SignalOutcome.profile_id == profile_id)
                .order_by(SignalOutcome.created_at.desc())
            )
        )
        closed_positions = list(
            session.scalars(
                select(PositionCloseEvent)
                .where(PositionCloseEvent.profile_id == profile_id)
                .order_by(PositionCloseEvent.closed_at.desc())
            )
        )
        paper_trades = list(
            session.scalars(
                select(PaperTrade)
                .where(PaperTrade.profile_id == profile_id)
                .order_by(PaperTrade.opened_at.desc())
            )
        )
        resolved = [item for item in outcomes if item.status == SignalOutcomeStatus.RESOLVED.value and item.return_pct is not None]
        pending_count = len([item for item in outcomes if item.status == SignalOutcomeStatus.PENDING.value])
        returns = [item.return_pct for item in resolved if item.return_pct is not None]
        closed_paper_trades = [item for item in paper_trades if item.status == PaperTradeStatus.CLOSED.value and item.return_pct is not None]
        open_paper_trades = [item for item in paper_trades if item.status == PaperTradeStatus.OPEN.value]
        bucket_map: dict[str, list[float]] = defaultdict(list)
        for item in resolved:
            bucket_map[item.bucket or "sin_bucket"].append(float(item.return_pct))

        by_bucket = {
            bucket: AnalyticsBucketRead(
                resolved_count=len(values),
                win_rate=round(sum(1 for value in values if value > 0) / len(values), 3) if values else None,
                avg_return_pct=round(sum(values) / len(values), 3) if values else None,
            )
            for bucket, values in bucket_map.items()
        }

        closed_returns = [item.return_pct for item in closed_positions]
        return SignalAnalyticsRead(
            resolved_count=len(resolved),
            pending_count=pending_count,
            win_rate=round(sum(1 for value in returns if value > 0) / len(returns), 3) if returns else None,
            avg_return_pct=round(sum(returns) / len(returns), 3) if returns else None,
            best_return_pct=round(max(returns), 3) if returns else None,
            worst_return_pct=round(min(returns), 3) if returns else None,
            by_bucket=by_bucket,
            closed_positions_count=len(closed_positions),
            closed_positions_avg_return_pct=round(sum(closed_returns) / len(closed_returns), 3) if closed_returns else None,
            paper_trades_closed_count=len(closed_paper_trades),
            paper_trades_open_count=len(open_paper_trades),
            paper_trades_win_rate=(
                round(sum(1 for item in closed_paper_trades if (item.return_pct or 0.0) > 0) / len(closed_paper_trades), 3)
                if closed_paper_trades
                else None
            ),
            paper_trades_avg_return_pct=(
                round(sum((item.return_pct or 0.0) for item in closed_paper_trades) / len(closed_paper_trades), 3)
                if closed_paper_trades
                else None
            ),
            recent_paper_trades=[PaperTradeRead.model_validate(item) for item in paper_trades[:10]],
            recent_outcomes=[SignalOutcomeRead.model_validate(item) for item in outcomes[:10]],
        )

    def render_stats_summary(self, analytics: SignalAnalyticsRead) -> str:
        lines = ["📊 Resumen real del sistema:"]
        lines.append(f"• alertas medidas: {analytics.resolved_count} resueltas | {analytics.pending_count} pendientes")
        if analytics.win_rate is not None and analytics.avg_return_pct is not None:
            lines.append(
                f"• buy alerts: win rate {analytics.win_rate * 100:.1f}% | retorno medio {analytics.avg_return_pct:+.2f}%"
            )
        else:
            lines.append("• buy alerts: todavía no hay suficiente histórico resuelto")
        if analytics.closed_positions_count:
            avg_closed = analytics.closed_positions_avg_return_pct or 0.0
            lines.append(f"• cierres manuales registrados: {analytics.closed_positions_count} | retorno medio {avg_closed:+.2f}%")
        if analytics.paper_trades_closed_count or analytics.paper_trades_open_count:
            closed_avg = analytics.paper_trades_avg_return_pct or 0.0
            if analytics.paper_trades_closed_count and analytics.paper_trades_win_rate is not None:
                lines.append(
                    f"• paper trades del bot: {analytics.paper_trades_closed_count} cerrados | {analytics.paper_trades_open_count} abiertos | win rate {analytics.paper_trades_win_rate * 100:.1f}% | retorno medio {closed_avg:+.2f}%"
                )
            else:
                lines.append(f"• paper trades del bot: {analytics.paper_trades_open_count} abiertos | todavía sin suficientes cierres")
        if analytics.recent_outcomes:
            lines.append("")
            lines.append("Últimos resultados medidos:")
            for item in analytics.recent_outcomes[:5]:
                if item.return_pct is None:
                    lines.append(f"• {item.symbol} · pendiente de medir")
                else:
                    lines.append(f"• {item.symbol} · {item.return_pct:+.2f}% a {item.evaluation_horizon_hours}h")
        if analytics.recent_paper_trades:
            lines.append("")
            lines.append("Paper trades recientes:")
            for item in analytics.recent_paper_trades[:5]:
                if item.return_pct is None:
                    lines.append(f"• {item.symbol} · abierta desde {item.entry_price:,.2f}")
                else:
                    lines.append(f"• {item.symbol} · cerrada con {item.return_pct:+.2f}%")
        return "\n".join(lines)

    @staticmethod
    def _outcome_label(return_pct: float) -> str:
        if return_pct > 1.0:
            return "win"
        if return_pct < -1.0:
            return "loss"
        return "flat"

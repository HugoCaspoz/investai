from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.investai_api.models import AssetType, Position, SignalSnapshot, SignalType, UserProfile
from apps.api.investai_api.services.discovery_service import DiscoveryService
from apps.api.investai_api.services.market_data_service import MarketDataService
from apps.api.investai_api.services.portfolio_service import PortfolioService
from apps.api.investai_api.services.signal_engine import SignalEngine
from apps.api.investai_api.services.telegram_service import TelegramService


class JobService:
    ALERT_COOLDOWN_HOURS = 6

    def __init__(self) -> None:
        self.discovery_service = DiscoveryService()
        self.market_data_service = MarketDataService()
        self.portfolio_service = PortfolioService()
        self.signal_engine = SignalEngine()
        self.telegram_service = TelegramService()

    async def run_scan(self, session: Session) -> dict[str, int]:
        profiles = list(session.scalars(select(UserProfile)))
        buy_alerts_sent = 0
        sell_alerts_sent = 0
        alerts_sent = 0
        profiles_with_live_data = 0
        for profile in profiles:
            profile_alerts_sent = 0
            positions = self.portfolio_service.list_open_positions(session, profile.id)

            for position in positions:
                if profile_alerts_sent >= profile.max_alerts_per_day:
                    break
                delivered = await self._maybe_send_position_review(session, profile, position)
                if delivered:
                    alerts_sent += 1
                    sell_alerts_sent += 1
                    profile_alerts_sent += 1

            if profile_alerts_sent >= profile.max_alerts_per_day:
                continue

            live_candidates = await self.market_data_service.fetch_live_candidates(profile)
            if not live_candidates:
                continue
            profiles_with_live_data += 1
            candidate_map = {candidate.symbol: candidate for candidate in live_candidates}
            ranked = self.discovery_service.rank_candidates(profile, live_candidates)
            for candidate in ranked:
                if profile_alerts_sent >= profile.max_alerts_per_day:
                    break
                source_candidate = candidate_map[candidate.symbol]
                signal = self.signal_engine.evaluate(
                    session,
                    profile,
                    self.market_data_service.build_signal_request(source_candidate, profile.telegram_chat_id),
                )
                if signal.signal_type != SignalType.BUY:
                    continue
                if not self._should_send_alert(session, profile.id, source_candidate.symbol, signal.signal_type):
                    continue
                if profile.telegram_chat_id:
                    delivered = await self.telegram_service.send_message(
                        profile.telegram_chat_id,
                        self._format_buy_alert_message(signal, source_candidate),
                    )
                    if delivered:
                        alerts_sent += 1
                        buy_alerts_sent += 1
                        profile_alerts_sent += 1
        return {
            "profiles_processed": len(profiles),
            "profiles_with_live_data": profiles_with_live_data,
            "buy_alerts_sent": buy_alerts_sent,
            "sell_alerts_sent": sell_alerts_sent,
            "alerts_sent": alerts_sent,
        }

    async def _maybe_send_position_review(self, session: Session, profile: UserProfile, position: Position) -> bool:
        candidate = await self.market_data_service.fetch_live_candidate_for_symbol(
            profile,
            position.symbol,
            AssetType(position.asset_type),
        )
        if not candidate:
            return False
        signal = self.signal_engine.evaluate(
            session,
            profile,
            self.market_data_service.build_position_review_request(
                position,
                candidate,
                profile.telegram_chat_id,
            ),
        )
        if signal.signal_type not in {SignalType.SELL, SignalType.CRITICAL_NEWS}:
            return False
        if not self._should_send_alert(session, profile.id, position.symbol, signal.signal_type):
            return False
        if not profile.telegram_chat_id:
            return False
        delivered = await self.telegram_service.send_message(
            profile.telegram_chat_id,
            self._format_position_review_message(signal, candidate, position, self.market_data_service.extract_pnl_pct(position, candidate)),
        )
        return delivered

    def _should_send_alert(
        self,
        session: Session,
        profile_id: int,
        symbol: str,
        signal_type: SignalType,
    ) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.ALERT_COOLDOWN_HOURS)
        snapshots = list(
            session.scalars(
                select(SignalSnapshot)
                .where(SignalSnapshot.profile_id == profile_id)
                .where(SignalSnapshot.symbol == symbol.upper())
                .where(SignalSnapshot.signal_type == signal_type.value)
                .order_by(SignalSnapshot.created_at.desc())
                .limit(2)
            )
        )
        if not snapshots:
            return True
        latest = snapshots[0]
        comparison_snapshot = latest
        now = datetime.now(timezone.utc)
        latest_created_at = latest.created_at
        if latest_created_at and latest_created_at.tzinfo is None:
            latest_created_at = latest_created_at.replace(tzinfo=timezone.utc)
        if len(snapshots) == 1:
            if latest_created_at and abs((now - latest_created_at).total_seconds()) < 120:
                return True
            return not latest_created_at or latest_created_at < cutoff
        if latest_created_at and abs((now - latest_created_at).total_seconds()) < 120 and len(snapshots) > 1:
            comparison_snapshot = snapshots[1]

        if not comparison_snapshot or not comparison_snapshot.created_at:
            return True
        comparison_created_at = comparison_snapshot.created_at
        if comparison_created_at.tzinfo is None:
            comparison_created_at = comparison_created_at.replace(tzinfo=timezone.utc)
        return comparison_created_at < cutoff

    @staticmethod
    def _format_buy_alert_message(signal, candidate) -> str:
        lines = [
            f"[{signal.alert_priority.value.upper()}] {candidate.symbol}",
            f"Recomendacion manual: {signal.manual_recommendation}",
            f"Modo: {signal.execution_mode}",
            f"Fuente: {candidate.source}",
            f"Tipo: {signal.signal_type.value}",
            f"Bucket: {signal.bucket}",
            f"Riesgo: {signal.risk_level}",
            f"Score: {signal.score:.2f} | Confianza: {signal.confidence:.2f}",
        ]
        if candidate.current_price is not None:
            lines.append(f"Precio: ${candidate.current_price:,.4f}")
        if candidate.price_change_percentage_24h is not None or candidate.price_change_percentage_7d is not None:
            change_24h = (
                f"{candidate.price_change_percentage_24h:+.2f}%"
                if candidate.price_change_percentage_24h is not None
                else "n/d"
            )
            change_7d = (
                f"{candidate.price_change_percentage_7d:+.2f}%"
                if candidate.price_change_percentage_7d is not None
                else "n/d"
            )
            lines.append(f"Momentum: 24h {change_24h} | 7d {change_7d}")
        lines.append("")
        lines.append(f"Resumen: {signal.summary}")
        lines.append(f"A favor: {', '.join(signal.reasons_for[:3])}.")
        if signal.reasons_against:
            lines.append(f"En contra: {', '.join(signal.reasons_against[:2])}.")
        lines.append(f"Siguiente paso sugerido: {signal.action_hint}.")
        return "\n".join(lines)

    @staticmethod
    def _format_position_review_message(signal, candidate, position, pnl_pct: float | None) -> str:
        lines = [
            f"[{signal.alert_priority.value.upper()}] {position.symbol}",
            f"Recomendacion manual: {signal.manual_recommendation}",
            f"Modo: {signal.execution_mode}",
            f"Fuente: {candidate.source}",
            f"Tipo: {signal.signal_type.value}",
            f"Bucket: {signal.bucket}",
            f"Riesgo: {signal.risk_level}",
            f"Entrada: ${position.entry_price:,.4f}",
        ]
        if candidate.current_price is not None:
            lines.append(f"Precio actual: ${candidate.current_price:,.4f}")
        if pnl_pct is not None:
            lines.append(f"Rendimiento desde entrada: {pnl_pct:+.2f}%")
        if position.target_price is not None:
            lines.append(f"Objetivo: ${position.target_price:,.4f}")
        if position.stop_price is not None:
            lines.append(f"Stop: ${position.stop_price:,.4f}")
        lines.append("")
        lines.append(f"Resumen: {signal.summary}")
        lines.append(f"A favor de revisar/vender: {', '.join(signal.reasons_for[:3])}.")
        if signal.reasons_against:
            lines.append(f"Puntos para no precipitarse: {', '.join(signal.reasons_against[:2])}.")
        lines.append(f"Siguiente paso sugerido: {signal.action_hint}.")
        return "\n".join(lines)

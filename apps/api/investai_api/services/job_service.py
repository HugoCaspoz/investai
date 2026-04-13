from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.investai_api.models import AlertDelivery, AssetType, Position, SignalSnapshot, SignalType, UserProfile
from apps.api.investai_api.services.analytics_service import AnalyticsService
from apps.api.investai_api.services.discovery_service import DiscoveryService
from apps.api.investai_api.services.market_data_service import MarketDataService
from apps.api.investai_api.services.message_formatter import MessageFormatter
from apps.api.investai_api.services.portfolio_service import PortfolioService
from apps.api.investai_api.services.signal_engine import SignalEngine
from apps.api.investai_api.services.telegram_service import TelegramService


class JobService:
    ALERT_COOLDOWN_HOURS = 6

    def __init__(self) -> None:
        self.analytics_service = AnalyticsService()
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
        outcomes_resolved = await self.analytics_service.resolve_due_outcomes(session)
        for profile in profiles:
            alerts_sent_today = self._alerts_sent_last_24h(session, profile.id)
            remaining_daily_alerts = max(0, profile.max_alerts_per_day - alerts_sent_today)
            profile_alerts_sent = 0
            if remaining_daily_alerts == 0:
                continue
            positions = self.portfolio_service.list_open_positions(session, profile.id)
            open_symbols = {position.symbol for position in positions}
            paper_trades = self.analytics_service.list_open_paper_trades(session, profile.id)
            open_symbols.update({trade.symbol for trade in paper_trades})

            for position in positions:
                if profile_alerts_sent >= remaining_daily_alerts:
                    break
                delivered = await self._maybe_send_position_review(session, profile, position)
                if delivered:
                    alerts_sent += 1
                    sell_alerts_sent += 1
                    profile_alerts_sent += 1

            for trade in paper_trades:
                if profile_alerts_sent >= remaining_daily_alerts:
                    break
                delivered = await self._maybe_send_paper_trade_exit(session, profile, trade)
                if delivered:
                    alerts_sent += 1
                    sell_alerts_sent += 1
                    profile_alerts_sent += 1

            if profile_alerts_sent >= remaining_daily_alerts:
                continue

            live_candidates = await self.market_data_service.fetch_live_candidates(profile)
            if not live_candidates:
                continue
            profiles_with_live_data += 1
            candidate_map = {candidate.symbol: candidate for candidate in live_candidates}
            ranked = self.discovery_service.rank_candidates(profile, live_candidates)
            for candidate in ranked:
                if profile_alerts_sent >= remaining_daily_alerts:
                    break
                if candidate.symbol in open_symbols:
                    continue
                source_candidate = candidate_map[candidate.symbol]
                signal = self.signal_engine.evaluate(
                    session,
                    profile,
                    self.market_data_service.build_signal_request(source_candidate, profile.telegram_chat_id),
                )
                if signal.signal_type != SignalType.BUY:
                    continue
                if signal.subscores.get("profile_fit", 0.0) < 0.40:
                    continue
                if not self._should_send_alert(session, profile.id, source_candidate.symbol, signal.signal_type):
                    continue
                if profile.telegram_chat_id:
                    delivered = await self.telegram_service.send_message(
                        profile.telegram_chat_id,
                        MessageFormatter.format_buy_alert(signal, source_candidate),
                    )
                    if delivered:
                        self._record_delivery(session, signal.id, profile.telegram_chat_id)
                        self.analytics_service.register_buy_signal_outcome(
                            session,
                            profile,
                            signal.id,
                            signal.signal_type,
                            signal.symbol,
                            signal.asset_type,
                            signal.source,
                            signal.bucket,
                            source_candidate.current_price,
                        )
                        self.analytics_service.open_paper_trade(
                            session,
                            profile,
                            signal.id,
                            signal.symbol,
                            signal.asset_type,
                            signal.source,
                            signal.bucket,
                            source_candidate.current_price,
                        )
                        alerts_sent += 1
                        buy_alerts_sent += 1
                        profile_alerts_sent += 1
        return {
            "profiles_processed": len(profiles),
            "profiles_with_live_data": profiles_with_live_data,
            "buy_alerts_sent": buy_alerts_sent,
            "sell_alerts_sent": sell_alerts_sent,
            "alerts_sent": alerts_sent,
            "outcomes_resolved": outcomes_resolved,
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
            MessageFormatter.format_position_review(
                signal,
                candidate,
                position,
                self.market_data_service.extract_pnl_pct(position, candidate),
            ),
        )
        if delivered:
            self._record_delivery(session, signal.id, profile.telegram_chat_id)
        return delivered

    async def _maybe_send_paper_trade_exit(self, session: Session, profile: UserProfile, trade) -> bool:
        candidate = await self.market_data_service.fetch_live_candidate_for_symbol(
            profile,
            trade.symbol,
            AssetType(trade.asset_type),
        )
        if not candidate:
            return False
        paper_position = Position(
            profile_id=profile.id,
            symbol=trade.symbol,
            asset_type=trade.asset_type,
            entry_price=trade.entry_price,
            quantity=None,
            thesis="paper_trade",
            target_price=None,
            stop_price=None,
            theme=trade.bucket,
        )
        signal = self.signal_engine.evaluate(
            session,
            profile,
            self.market_data_service.build_position_review_request(
                paper_position,
                candidate,
                profile.telegram_chat_id,
            ),
        )
        if signal.signal_type not in {SignalType.SELL, SignalType.CRITICAL_NEWS}:
            return False
        if not self._should_send_alert(session, profile.id, trade.symbol, signal.signal_type):
            return False
        if not profile.telegram_chat_id:
            return False
        pnl_pct = self.market_data_service.extract_pnl_pct(paper_position, candidate)
        delivered = await self.telegram_service.send_message(
            profile.telegram_chat_id,
            MessageFormatter.format_position_review(signal, candidate, paper_position, pnl_pct),
        )
        if delivered:
            self._record_delivery(session, signal.id, profile.telegram_chat_id)
            self.analytics_service.close_paper_trade(session, trade, signal.id, candidate.current_price)
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
    def _record_delivery(session: Session, signal_snapshot_id: int | None, chat_id: str | None) -> None:
        if signal_snapshot_id is None:
            return
        delivery = AlertDelivery(
            signal_snapshot_id=signal_snapshot_id,
            channel="telegram",
            chat_id=chat_id,
            status="delivered",
            delivered_at=datetime.now(timezone.utc),
        )
        session.add(delivery)
        session.commit()

    @staticmethod
    def _alerts_sent_last_24h(session: Session, profile_id: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        deliveries = list(
            session.scalars(
                select(AlertDelivery)
                .join(SignalSnapshot, SignalSnapshot.id == AlertDelivery.signal_snapshot_id)
                .where(SignalSnapshot.profile_id == profile_id)
                .where(AlertDelivery.delivered_at >= cutoff)
            )
        )
        return len(deliveries)

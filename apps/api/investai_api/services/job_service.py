from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.investai_api.models import UserProfile
from apps.api.investai_api.schemas import SignalEvaluationRequest
from apps.api.investai_api.services.discovery_service import DiscoveryService
from apps.api.investai_api.services.signal_engine import SignalEngine
from apps.api.investai_api.services.telegram_service import TelegramService


class JobService:
    def __init__(self) -> None:
        self.discovery_service = DiscoveryService()
        self.signal_engine = SignalEngine()
        self.telegram_service = TelegramService()

    async def run_demo_scan(self, session: Session) -> dict[str, int]:
        profiles = list(session.scalars(select(UserProfile)))
        alerts_sent = 0
        for profile in profiles:
            demo_candidates = self.discovery_service.demo_candidates()
            candidate_map = {candidate.symbol: candidate for candidate in demo_candidates}
            ranked = self.discovery_service.rank_candidates(profile, demo_candidates)
            for candidate in ranked[: profile.max_alerts_per_day]:
                source_candidate = candidate_map[candidate.symbol]
                signal = self.signal_engine.evaluate(
                    session,
                    profile,
                    SignalEvaluationRequest(
                        telegram_chat_id=profile.telegram_chat_id,
                        symbol=candidate.symbol,
                        asset_type=candidate.asset_type,
                        bucket=candidate.bucket,
                        themes=source_candidate.themes,
                        technical_setup=min(1.0, candidate.score + 0.05),
                        relative_strength=min(1.0, candidate.score + 0.03),
                        pullback_quality=min(1.0, candidate.profile_fit + 0.10),
                        volume_confirmation=0.70,
                        catalyst_score=source_candidate.catalyst_strength,
                        narrative_strength=source_candidate.narrative_strength,
                        liquidity_quality=source_candidate.liquidity_score,
                        regime_alignment=0.60,
                        volatility_score=source_candidate.volatility_score,
                        context_notes=["demo scheduled scan"],
                    ),
                )
                if profile.telegram_chat_id:
                    delivered = await self.telegram_service.send_message(profile.telegram_chat_id, signal.summary)
                    if delivered:
                        alerts_sent += 1
        return {"profiles_processed": len(profiles), "alerts_sent": alerts_sent}

from __future__ import annotations

from apps.api.investai_api.catalog import bucket_for_themes
from apps.api.investai_api.models import UserProfile
from apps.api.investai_api.schemas import CandidateInput, RankedCandidateResponse


class DiscoveryService:
    def rank_candidates(
        self,
        profile: UserProfile,
        candidates: list[CandidateInput],
    ) -> list[RankedCandidateResponse]:
        results: list[RankedCandidateResponse] = []
        for candidate in candidates:
            profile_fit = self.profile_fit(profile.theme_weights, candidate.themes)
            volatility_fit = self.volatility_fit(profile.risk_tolerance, candidate.volatility_score)
            score = self._clamp(
                0.35 * profile_fit
                + 0.25 * candidate.catalyst_strength
                + 0.20 * candidate.narrative_strength
                + 0.10 * candidate.liquidity_score
                + 0.10 * volatility_fit
            )
            results.append(
                RankedCandidateResponse(
                    symbol=candidate.symbol,
                    name=candidate.name,
                    asset_type=candidate.asset_type,
                    bucket=bucket_for_themes(candidate.themes),
                    score=round(score, 3),
                    profile_fit=round(profile_fit, 3),
                    risk_level=self._risk_level(candidate.volatility_score, candidate.liquidity_score),
                    reasons=self._reasons(candidate, profile_fit, volatility_fit),
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)

    def profile_fit(self, theme_weights: dict[str, float], candidate_themes: list[str]) -> float:
        if not theme_weights:
            return 0.5
        total = sum(theme_weights.get(theme, 0.0) for theme in candidate_themes)
        return self._clamp(total * 1.75)

    @staticmethod
    def demo_candidates() -> list[CandidateInput]:
        from apps.api.investai_api.catalog import DEMO_CANDIDATES

        return [CandidateInput.model_validate(candidate) for candidate in DEMO_CANDIDATES]

    def volatility_fit(self, risk_tolerance: str, volatility_score: float) -> float:
        target = 0.8 if risk_tolerance == "aggressive" else 0.55 if risk_tolerance == "balanced" else 0.35
        return self._clamp(1 - abs(volatility_score - target))

    def _reasons(self, candidate: CandidateInput, profile_fit: float, volatility_fit: float) -> list[str]:
        reasons: list[str] = []
        if profile_fit >= 0.60:
            reasons.append("encaja bien con los temas dominantes de tu perfil")
        if candidate.catalyst_strength >= 0.65:
            reasons.append("presenta catalizador reciente o narrativa activa")
        if candidate.narrative_strength >= 0.70:
            reasons.append("mantiene narrativa fuerte dentro de su bucket")
        if candidate.liquidity_score >= 0.75:
            reasons.append("liquidez suficiente para un scanner agresivo pero serio")
        if volatility_fit >= 0.70:
            reasons.append("la volatilidad esta alineada con un perfil growth/agresivo")
        return reasons or ["sin razones claras todavia; merece observacion, no accion inmediata"]

    @staticmethod
    def _risk_level(volatility_score: float, liquidity_score: float) -> str:
        risk_score = 0.65 * volatility_score + 0.35 * (1 - liquidity_score)
        if risk_score >= 0.70:
            return "alto"
        if risk_score >= 0.45:
            return "medio"
        return "bajo"

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

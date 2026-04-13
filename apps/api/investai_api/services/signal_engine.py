from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.investai_api.catalog import bucket_for_themes
from apps.api.investai_api.models import AlertPriority, AssetType, SignalSnapshot, SignalType, UserProfile
from apps.api.investai_api.schemas import SignalEvaluationRequest, SignalRead
from apps.api.investai_api.services.discovery_service import DiscoveryService


class SignalEngine:
    def __init__(self) -> None:
        self.discovery_service = DiscoveryService()

    def evaluate(
        self,
        session: Session,
        profile: UserProfile | None,
        payload: SignalEvaluationRequest,
    ) -> SignalRead:
        theme_weights = profile.theme_weights if profile else {}
        technical_setup = payload.technical_setup or self._average(
            payload.relative_strength,
            payload.pullback_quality,
            payload.volume_confirmation,
        )
        profile_fit = self.discovery_service.profile_fit(theme_weights, payload.themes)
        buy_score = self._clamp(
            0.30 * technical_setup
            + 0.25 * payload.catalyst_score
            + 0.15 * payload.narrative_strength
            + 0.15 * payload.liquidity_quality
            + 0.10 * profile_fit
            + 0.05 * payload.regime_alignment
        )
        sell_score = self._clamp(
            0.30 * payload.technical_deterioration
            + 0.25 * payload.thesis_break_risk
            + 0.20 * payload.target_or_extension_score
            + 0.15 * payload.event_risk
            + 0.10 * payload.portfolio_concentration_risk
        )

        if payload.event_risk >= 0.85 and payload.thesis_break_risk >= 0.70:
            signal_type = SignalType.CRITICAL_NEWS
            score = max(sell_score, payload.event_risk)
        elif sell_score >= 0.62 and sell_score > buy_score + 0.08:
            signal_type = SignalType.SELL
            score = sell_score
        elif buy_score >= 0.66:
            signal_type = SignalType.BUY
            score = buy_score
        else:
            signal_type = SignalType.WATCH
            score = max(buy_score, sell_score)

        confidence = self._clamp(
            0.35
            + 0.35 * max(buy_score, sell_score)
            + 0.15 * abs(buy_score - sell_score)
            + 0.15 * (1 - abs(payload.relative_strength - payload.volume_confirmation))
        )
        risk_level = self._risk_level(payload.volatility_score, payload.liquidity_quality, payload.event_risk)
        alert_priority = self._priority(signal_type, score, risk_level)
        reasons_for, reasons_against = self._reasons(payload, technical_setup, profile_fit)
        bucket = payload.bucket or bucket_for_themes(payload.themes)
        subscores = {
            "technical_setup": round(technical_setup, 3),
            "profile_fit": round(profile_fit, 3),
            "buy_score": round(buy_score, 3),
            "sell_score": round(sell_score, 3),
        }
        summary = self._summary(signal_type, payload.symbol.upper(), score, bucket, reasons_for)

        snapshot = SignalSnapshot(
            profile_id=profile.id if profile else None,
            symbol=payload.symbol.upper(),
            asset_type=payload.asset_type.value,
            signal_type=signal_type.value,
            alert_priority=alert_priority.value,
            bucket=bucket,
            score=round(score, 3),
            confidence=round(confidence, 3),
            risk_level=risk_level,
            summary=summary,
            rationale={
                "reasons_for": reasons_for,
                "reasons_against": reasons_against,
                "subscores": subscores,
                "context_notes": payload.context_notes,
            },
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        return SignalRead(
            id=snapshot.id,
            symbol=snapshot.symbol,
            asset_type=AssetType(snapshot.asset_type),
            signal_type=SignalType(snapshot.signal_type),
            alert_priority=AlertPriority(snapshot.alert_priority),
            bucket=bucket,
            score=round(score, 3),
            confidence=round(confidence, 3),
            risk_level=risk_level,
            summary=summary,
            reasons_for=reasons_for,
            reasons_against=reasons_against,
            subscores=subscores,
        )

    def _reasons(
        self,
        payload: SignalEvaluationRequest,
        technical_setup: float,
        profile_fit: float,
    ) -> tuple[list[str], list[str]]:
        reasons_for: list[str] = []
        reasons_against: list[str] = []
        if technical_setup >= 0.65:
            reasons_for.append("estructura tecnica favorable o correccion controlada")
        if payload.relative_strength >= 0.65:
            reasons_for.append("relative strength por encima de la media del bucket")
        if payload.catalyst_score >= 0.65:
            reasons_for.append("catalizador reciente con impacto potencial relevante")
        if payload.narrative_strength >= 0.65:
            reasons_for.append("narrativa sectorial todavia fuerte")
        if profile_fit >= 0.55:
            reasons_for.append("encaja con tu perfil inferido a partir de las semillas")
        if payload.liquidity_quality <= 0.45:
            reasons_against.append("liquidez justa para una entrada disciplinada")
        if payload.volatility_score >= 0.80:
            reasons_against.append("volatilidad alta; conviene tamano prudente")
        if payload.event_risk >= 0.70:
            reasons_against.append("riesgo de evento cercano que puede distorsionar la lectura")
        if payload.technical_deterioration >= 0.60:
            reasons_against.append("debilitamiento tecnico visible en la estructura")
        if payload.thesis_break_risk >= 0.60:
            reasons_against.append("la tesis podria estar perdiendo calidad")
        if not reasons_for:
            reasons_for.append("no hay confirmaciones suficientes; de momento solo vigilancia")
        return reasons_for, reasons_against

    def _summary(
        self,
        signal_type: SignalType,
        symbol: str,
        score: float,
        bucket: str,
        reasons_for: list[str],
    ) -> str:
        confidence_label = self._confidence_label(score)
        main_reason = reasons_for[0]
        if signal_type == SignalType.BUY:
            return f"{symbol} entra en zona interesante. Senal de compra {confidence_label}. Bucket: {bucket}. Motivo principal: {main_reason}."
        if signal_type == SignalType.SELL:
            return f"{symbol} merece revision de venta o reduccion. Senal {confidence_label}. Motivo principal: {main_reason}."
        if signal_type == SignalType.CRITICAL_NEWS:
            return f"{symbol} activa alerta critica. Hay razones para revisar la tesis cuanto antes. Motivo principal: {main_reason}."
        return f"{symbol} queda en vigilancia. Senal {confidence_label}. Motivo principal: {main_reason}."

    @staticmethod
    def _priority(signal_type: SignalType, score: float, risk_level: str) -> AlertPriority:
        if signal_type in {SignalType.SELL, SignalType.CRITICAL_NEWS} and score >= 0.65:
            return AlertPriority.ACTION
        if signal_type == SignalType.BUY and score >= 0.68:
            return AlertPriority.ATTENTION
        if risk_level == "alto" and score >= 0.60:
            return AlertPriority.ATTENTION
        return AlertPriority.INFO

    @staticmethod
    def _risk_level(volatility_score: float, liquidity_quality: float, event_risk: float) -> str:
        risk_score = 0.50 * volatility_score + 0.30 * (1 - liquidity_quality) + 0.20 * event_risk
        if risk_score >= 0.70:
            return "alto"
        if risk_score >= 0.45:
            return "medio"
        return "bajo"

    @staticmethod
    def _confidence_label(score: float) -> str:
        if score >= 0.80:
            return "alta"
        if score >= 0.65:
            return "media-alta"
        if score >= 0.50:
            return "media"
        return "baja"

    @staticmethod
    def _average(*values: float) -> float:
        return sum(values) / len(values)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

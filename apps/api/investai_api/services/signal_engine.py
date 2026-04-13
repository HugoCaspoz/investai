from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.investai_api.catalog import bucket_for_themes
from apps.api.investai_api.models import AlertPriority, AssetType, SignalSnapshot, SignalType, UserProfile
from apps.api.investai_api.schemas import SignalEvaluationRequest, SignalRead
from apps.api.investai_api.services.discovery_service import DiscoveryService


class SignalEngine:
    def __init__(self) -> None:
        self.discovery_service = DiscoveryService()

    def preview(
        self,
        profile: UserProfile | None,
        payload: SignalEvaluationRequest,
    ) -> SignalRead:
        return self._evaluate(profile, payload)

    def evaluate(
        self,
        session: Session,
        profile: UserProfile | None,
        payload: SignalEvaluationRequest,
    ) -> SignalRead:
        signal = self._evaluate(profile, payload)
        snapshot = SignalSnapshot(
            profile_id=profile.id if profile else None,
            symbol=signal.symbol,
            asset_type=signal.asset_type.value,
            signal_type=signal.signal_type.value,
            alert_priority=signal.alert_priority.value,
            bucket=signal.bucket,
            score=signal.score,
            confidence=signal.confidence,
            risk_level=signal.risk_level,
            summary=signal.summary,
            rationale={
                "manual_recommendation": signal.manual_recommendation,
                "execution_mode": signal.execution_mode,
                "action_hint": signal.action_hint,
                "reasons_for": signal.reasons_for,
                "reasons_against": signal.reasons_against,
                "subscores": signal.subscores,
                "context_notes": payload.context_notes,
            },
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        signal.id = snapshot.id
        return signal

    def _evaluate(
        self,
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
        buy_reasons, sell_reasons = self._reason_buckets(payload, technical_setup, profile_fit)
        if signal_type in {SignalType.SELL, SignalType.CRITICAL_NEWS}:
            reasons_for = sell_reasons or ["hay senales suficientes para revisar la posicion"]
            reasons_against = buy_reasons[:3]
        else:
            reasons_for = buy_reasons or ["no hay confirmaciones suficientes; de momento solo vigilancia"]
            reasons_against = sell_reasons[:3]
        bucket = payload.bucket or bucket_for_themes(payload.themes)
        subscores = {
            "technical_setup": round(technical_setup, 3),
            "profile_fit": round(profile_fit, 3),
            "buy_score": round(buy_score, 3),
            "sell_score": round(sell_score, 3),
        }
        manual_recommendation = self._manual_recommendation(signal_type)
        action_hint = self._action_hint(signal_type)
        summary = self._summary(signal_type, payload.symbol.upper(), score, bucket, reasons_for)

        return SignalRead(
            symbol=payload.symbol.upper(),
            asset_type=payload.asset_type,
            source=payload.source,
            signal_type=signal_type,
            alert_priority=alert_priority,
            bucket=bucket,
            score=round(score, 3),
            confidence=round(confidence, 3),
            risk_level=risk_level,
            summary=summary,
            manual_recommendation=manual_recommendation,
            execution_mode="manual_only",
            action_hint=action_hint,
            reasons_for=reasons_for,
            reasons_against=reasons_against,
            subscores=subscores,
        )

    def _reason_buckets(
        self,
        payload: SignalEvaluationRequest,
        technical_setup: float,
        profile_fit: float,
    ) -> tuple[list[str], list[str]]:
        buy_reasons: list[str] = []
        sell_reasons: list[str] = []
        if payload.price_change_percentage_24h is not None and -3.5 <= payload.price_change_percentage_24h <= 1.5:
            buy_reasons.append("pullback suave sin perder el tono")
        elif technical_setup >= 0.65:
            buy_reasons.append("estructura tecnica razonable para vigilar entrada")
        if payload.relative_strength >= 0.65:
            buy_reasons.append("relative strength por encima de la media del bucket")
        if payload.catalyst_score >= 0.65:
            buy_reasons.append("catalizador reciente con impacto potencial relevante")
        if payload.narrative_strength >= 0.65:
            buy_reasons.append("narrativa sectorial todavia fuerte")
        if payload.price_change_percentage_24h is not None and 2 <= payload.price_change_percentage_24h <= 8:
            buy_reasons.append(f"impulso reciente todavia ordenado: {payload.price_change_percentage_24h:.1f}% en 24h")
        if payload.price_change_percentage_7d is not None and 5 <= payload.price_change_percentage_7d <= 20:
            buy_reasons.append(f"continuidad de momentum razonable: {payload.price_change_percentage_7d:.1f}% en 7d")
        if payload.dollar_volume is not None and payload.dollar_volume >= 100_000_000:
            buy_reasons.append("volumen negociado alto para una alerta seria")
        if profile_fit >= 0.55:
            buy_reasons.append("encaja con tu perfil inferido a partir de las semillas")
        if payload.liquidity_quality <= 0.45:
            sell_reasons.append("liquidez justa para una entrada disciplinada")
        if payload.volatility_score >= 0.80:
            sell_reasons.append("volatilidad alta; conviene tamano prudente")
        if payload.price_change_percentage_24h is not None and payload.price_change_percentage_24h >= 15:
            sell_reasons.append(f"movimiento demasiado vertical: {payload.price_change_percentage_24h:.1f}% en 24h")
        if payload.price_change_percentage_7d is not None and payload.price_change_percentage_7d >= 35:
            sell_reasons.append(f"sobreextension fuerte: {payload.price_change_percentage_7d:.1f}% en 7d")
        if payload.price_change_percentage_24h is not None and payload.price_change_percentage_24h <= -5:
            sell_reasons.append(f"caida agresiva de {payload.price_change_percentage_24h:.1f}% en 24h")
        if payload.price_change_percentage_7d is not None and payload.price_change_percentage_7d <= -12:
            sell_reasons.append(f"debilidad semanal todavia importante: {payload.price_change_percentage_7d:.1f}% en 7d")
        if payload.event_risk >= 0.70:
            sell_reasons.append("riesgo de evento cercano que puede distorsionar la lectura")
        if payload.technical_deterioration >= 0.60:
            sell_reasons.append("debilitamiento tecnico visible en la estructura")
        if payload.thesis_break_risk >= 0.60:
            sell_reasons.append("la tesis podria estar perdiendo calidad")
        if payload.target_or_extension_score >= 0.60:
            sell_reasons.append("sobreextension suficiente para no perseguir la entrada")
        return buy_reasons, sell_reasons

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
            return f"{symbol} entra en zona interesante. Recomendacion: compra potencial {confidence_label}. Bucket: {bucket}. Motivo principal: {main_reason}."
        if signal_type == SignalType.SELL:
            return f"{symbol} merece revision manual de venta o reduccion. Senal {confidence_label}. Motivo principal: {main_reason}."
        if signal_type == SignalType.CRITICAL_NEWS:
            return f"{symbol} activa alerta critica. Recomendacion: revisar manualmente la tesis cuanto antes. Motivo principal: {main_reason}."
        return f"{symbol} queda en vigilancia. Sin compra clara por ahora. Motivo principal: {main_reason}."

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
    def _manual_recommendation(signal_type: SignalType) -> str:
        if signal_type == SignalType.BUY:
            return "compra potencial manual"
        if signal_type == SignalType.SELL:
            return "revisar venta o reducir manualmente"
        if signal_type == SignalType.CRITICAL_NEWS:
            return "revision urgente manual"
        return "vigilar; sin accion inmediata"

    @staticmethod
    def _action_hint(signal_type: SignalType) -> str:
        if signal_type == SignalType.BUY:
            return "si encaja con tu tesis, valida niveles, tamano y riesgo antes de lanzar la orden manualmente"
        if signal_type == SignalType.SELL:
            return "revisa objetivo, stop y decide manualmente si reducir, proteger beneficios o salir"
        if signal_type == SignalType.CRITICAL_NEWS:
            return "revisa la noticia o el deterioro de tesis antes de mantener la posicion sin cambios"
        return "espera confirmacion adicional antes de actuar"

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

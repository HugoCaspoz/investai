from __future__ import annotations

from apps.api.investai_api.models import Position, SignalType
from apps.api.investai_api.schemas import CandidateInput, SignalRead


class MessageFormatter:
    SIGNAL_EMOJI = {
        SignalType.BUY: "🟢",
        SignalType.SELL: "🟠",
        SignalType.CRITICAL_NEWS: "🔴",
        SignalType.WATCH: "🟡",
    }
    RISK_EMOJI = {"bajo": "🟢", "medio": "🟠", "alto": "🔴"}
    BUCKET_EMOJI = {
        "crypto": "₿",
        "crypto infra": "🏗️",
        "AI / growth": "🤖",
        "nuclear / uranium": "⚛️",
        "EV": "⚡",
        "growth": "🚀",
    }

    @classmethod
    def format_buy_alert(cls, signal: SignalRead, candidate: CandidateInput) -> str:
        lines = [
            f"{cls._signal_emoji(signal.signal_type)} {candidate.symbol} | {cls._short_recommendation(signal)}",
            f"{cls._bucket_emoji(signal.bucket)} {signal.bucket} · encaje contigo: {cls._fit_label(signal.subscores.get('profile_fit'))}",
            cls._market_line(candidate, signal),
            "",
            f"💡 Lectura rápida: {cls._quick_take(signal, candidate)}",
            f"✅ A favor: {cls._join_reasons(signal.reasons_for, fallback='no veo argumentos fuertes todavía')}",
        ]
        if signal.reasons_against:
            lines.append(f"⚠️ Ojo: {cls._join_reasons(signal.reasons_against, limit=2)}")
        lines.append(f"👉 Qué haría yo: {signal.action_hint}.")
        lines.append("🤝 Solo te aviso; la decisión y la ejecución siguen siendo tuyas.")
        return "\n".join(lines)

    @classmethod
    def format_position_review(
        cls,
        signal: SignalRead,
        candidate: CandidateInput,
        position: Position,
        pnl_pct: float | None,
    ) -> str:
        is_paper_trade = position.thesis == "paper_trade"
        lines = [
            f"{cls._signal_emoji(signal.signal_type)} {position.symbol} | {cls._short_recommendation(signal)}",
            f"{cls._bucket_emoji(signal.bucket)} {signal.bucket} · riesgo {cls._risk_emoji(signal.risk_level)} {signal.risk_level}",
            cls._position_line(candidate, position, pnl_pct, is_paper_trade),
            "",
            f"💡 Lectura rápida: {cls._position_take(signal, candidate, pnl_pct, is_paper_trade)}",
            f"✅ Motivos para revisar: {cls._join_reasons(signal.reasons_for, fallback='hay señales suficientes para revisar la posición')}",
        ]
        if signal.reasons_against:
            lines.append(f"⚖️ Lo que todavía sostiene la tesis: {cls._join_reasons(signal.reasons_against, limit=2)}")
        lines.append(f"👉 Qué haría yo: {signal.action_hint}.")
        if is_paper_trade:
            lines.append("🧪 Esto cuenta como salida del paper trade del bot, para medir si sus señales habrían sido rentables.")
        else:
            lines.append("🤝 Solo te aviso; no ejecuto ninguna orden por ti.")
        return "\n".join(lines)

    @classmethod
    def format_symbol_analysis(
        cls,
        signal: SignalRead,
        candidate: CandidateInput,
        pnl_pct: float | None = None,
        position: Position | None = None,
    ) -> str:
        if position:
            return cls.format_position_review(signal, candidate, position, pnl_pct)
        return cls.format_buy_alert(signal, candidate)

    @classmethod
    def format_scan_item(cls, signal: SignalRead, candidate: CandidateInput) -> str:
        change_24h = cls._format_pct(candidate.price_change_percentage_24h)
        return (
            f"{cls._signal_emoji(signal.signal_type)} {candidate.symbol} · {cls._short_recommendation(signal)}\n"
            f"{cls._bucket_emoji(signal.bucket)} {signal.bucket} · {cls._format_price(candidate.current_price)} · 24h {change_24h} · encaje {cls._fit_label(signal.subscores.get('profile_fit'))}"
        )

    @classmethod
    def format_alert_list_item(cls, symbol: str, recommendation: str, score: float, summary: str) -> str:
        return f"• {symbol} · {recommendation} · score {score:.2f}\n  {summary}"

    @classmethod
    def _short_recommendation(cls, signal: SignalRead) -> str:
        if signal.signal_type == SignalType.BUY:
            return "compra potencial"
        if signal.signal_type == SignalType.SELL:
            return "revisar / reducir"
        if signal.signal_type == SignalType.CRITICAL_NEWS:
            return "revisión urgente"
        return "vigilar"

    @classmethod
    def _quick_take(cls, signal: SignalRead, candidate: CandidateInput) -> str:
        change_24h = candidate.price_change_percentage_24h
        change_7d = candidate.price_change_percentage_7d
        if signal.signal_type == SignalType.BUY:
            if cls._is_overextended(change_24h, change_7d):
                return "Hay fuerza, pero el movimiento es demasiado vertical; más para vigilar una pausa que para perseguirlo."
            if change_24h is not None and -3.5 <= change_24h <= 1.5:
                return "Me gusta más como pullback ordenado que como ruptura tardía; encaja bien para vigilar entrada."
            if change_24h is not None and 1.5 < change_24h <= 7.0:
                return "Mantiene buen tono sin verse desbocado; tiene pinta de oportunidad razonable, no de chase."
            if change_7d is not None and change_7d < -10:
                return "Hay rebote, pero la debilidad de la última semana todavía pesa; lo trataría con más cautela."
            return "Veo varias señales a favor, pero prefiero validarlo con disciplina antes de entrar."
        if signal.signal_type == SignalType.WATCH:
            return "Lo veo más para radar que para actuar ya; le falta una confirmación clara."
        return signal.summary

    @classmethod
    def _position_take(cls, signal: SignalRead, candidate: CandidateInput, pnl_pct: float | None, is_paper_trade: bool) -> str:
        change_24h = candidate.price_change_percentage_24h
        if signal.signal_type == SignalType.CRITICAL_NEWS:
            return "Aquí sí haría una revisión rápida de la tesis porque el riesgo ya no parece normal."
        if pnl_pct is not None and pnl_pct >= 15 and change_24h is not None and change_24h < -2.5:
            prefix = "Si hubieras seguido la compra del bot," if is_paper_trade else "Lleva buen beneficio y"
            return f"{prefix} empieza a tener sentido proteger ganancias o recoger parte del movimiento."
        if pnl_pct is not None and pnl_pct >= 10:
            return "Ya tiene recorrido desde la entrada; yo revisaría stop, objetivo o una salida ordenada."
        if is_paper_trade:
            return "La entrada hipotética del bot ya no se ve igual de limpia; lo tomaría como punto razonable para medir salida."
        return "La lectura se está deteriorando y merece una revisión manual antes de dejarla correr sin mirar."

    @classmethod
    def _market_line(cls, candidate: CandidateInput, signal: SignalRead) -> str:
        parts = [
            f"💵 {cls._format_price(candidate.current_price)}",
            f"24h {cls._format_pct(candidate.price_change_percentage_24h)}",
            f"7d {cls._format_pct(candidate.price_change_percentage_7d)}",
            f"riesgo {cls._risk_emoji(signal.risk_level)} {signal.risk_level}",
        ]
        return " · ".join(parts)

    @classmethod
    def _position_line(cls, candidate: CandidateInput, position: Position, pnl_pct: float | None, is_paper_trade: bool) -> str:
        parts = [
            f"{'🧪 entrada bot' if is_paper_trade else '💼 entrada'} {cls._format_price(position.entry_price)}",
            f"ahora {cls._format_price(candidate.current_price)}",
        ]
        if pnl_pct is not None:
            parts.append(f"resultado {pnl_pct:+.2f}%")
        return " · ".join(parts)

    @staticmethod
    def _join_reasons(reasons: list[str], fallback: str = "sin objeciones claras", limit: int = 3) -> str:
        if not reasons:
            return fallback
        return "; ".join(reasons[:limit])

    @classmethod
    def _fit_label(cls, profile_fit: float | None) -> str:
        value = profile_fit or 0.0
        if value >= 0.70:
            return "alto"
        if value >= 0.45:
            return "medio"
        return "bajo"

    @classmethod
    def _signal_emoji(cls, signal_type: SignalType) -> str:
        return cls.SIGNAL_EMOJI.get(signal_type, "🟡")

    @classmethod
    def _risk_emoji(cls, risk_level: str) -> str:
        return cls.RISK_EMOJI.get(risk_level, "🟡")

    @classmethod
    def _bucket_emoji(cls, bucket: str) -> str:
        return cls.BUCKET_EMOJI.get(bucket, "📈")

    @staticmethod
    def _format_price(price: float | None) -> str:
        if price is None:
            return "n/d"
        return f"${price:,.2f}"

    @staticmethod
    def _format_pct(value: float | None) -> str:
        if value is None:
            return "n/d"
        return f"{value:+.2f}%"

    @staticmethod
    def _is_overextended(change_24h: float | None, change_7d: float | None) -> bool:
        return (change_24h is not None and change_24h >= 15.0) or (change_7d is not None and change_7d >= 35.0)

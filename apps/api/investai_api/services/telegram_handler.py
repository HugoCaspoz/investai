from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.api.investai_api.models import SignalSnapshot, UserProfile
from apps.api.investai_api.schemas import CandidateInput, PositionCreate, ProfileBootstrapRequest, SignalEvaluationRequest
from apps.api.investai_api.services.command_parser import CommandParser
from apps.api.investai_api.services.discovery_service import DiscoveryService
from apps.api.investai_api.services.portfolio_service import PortfolioService
from apps.api.investai_api.services.profile_service import ProfileService
from apps.api.investai_api.services.signal_engine import SignalEngine
from apps.api.investai_api.services.telegram_service import TelegramService


class TelegramHandler:
    def __init__(self) -> None:
        self.parser = CommandParser()
        self.profile_service = ProfileService()
        self.portfolio_service = PortfolioService()
        self.discovery_service = DiscoveryService()
        self.signal_engine = SignalEngine()
        self.telegram_service = TelegramService()

    async def handle_update(self, session: Session, payload: dict) -> dict[str, object]:
        message = payload.get("message") or payload.get("edited_message")
        if not message or "text" not in message:
            return {
                "handled": False,
                "reply_text": "Update ignorado: solo se soportan mensajes de texto en este MVP.",
                "delivered": False,
            }

        text = message["text"]
        chat_id = str(message["chat"]["id"])
        display_name = message.get("from", {}).get("first_name")
        profile = self.profile_service.ensure_profile(session, chat_id, display_name)
        parsed = self.parser.parse(text)

        if parsed.action in {"start", "help"}:
            reply = self._help_text()
        elif parsed.action == "profile":
            reply = self.profile_service.render_profile_summary(profile, session)
        elif parsed.action == "seed":
            updated = self.profile_service.bootstrap_profile(
                session,
                ProfileBootstrapRequest(
                    telegram_chat_id=chat_id,
                    display_name=display_name,
                    seeds=parsed.payload.get("seeds", []),
                    risk_tolerance=profile.risk_tolerance,
                    horizon=profile.horizon,
                    max_alerts_per_day=profile.max_alerts_per_day,
                    notes=profile.notes,
                ),
            )
            reply = "Semillas actualizadas.\n" + self.profile_service.render_profile_summary(updated, session)
        elif parsed.action == "register_position":
            position = self.portfolio_service.register_position(
                session,
                profile,
                PositionCreate(
                    telegram_chat_id=chat_id,
                    symbol=parsed.payload["symbol"],
                    entry_price=parsed.payload["entry_price"],
                    quantity=parsed.payload.get("quantity"),
                    thesis=parsed.payload.get("thesis"),
                    target_price=parsed.payload.get("target_price"),
                    stop_price=parsed.payload.get("stop_price"),
                    asset_type=self.profile_service.infer_asset_type(parsed.payload["symbol"]),
                ),
            )
            reply = f"Posicion registrada: {position.symbol} a {position.entry_price:g}."
        elif parsed.action == "portfolio":
            reply = self.portfolio_service.render_positions(self.portfolio_service.list_open_positions(session, profile.id))
        elif parsed.action == "scan":
            ranked = self.discovery_service.rank_candidates(profile, self.discovery_service.demo_candidates())
            lines = ["Top candidatos del scanner demo:"]
            for item in ranked[:3]:
                lines.append(f"- {item.symbol} | {item.bucket} | score={item.score:.2f} | riesgo={item.risk_level}")
            reply = "\n".join(lines)
        elif parsed.action == "alerts":
            reply = self._format_latest_alerts(session, profile.id)
        elif parsed.action == "why":
            reply = self._explain_symbol(session, profile, parsed.payload["symbol"])
        else:
            reply = "No he entendido el mensaje. Usa /help, /scan, /profile, /portfolio, o escribe 'he comprado PLTR a 21.5'."

        delivered = await self.telegram_service.send_message(chat_id, reply)
        return {"handled": True, "reply_text": reply, "delivered": delivered}

    def _explain_symbol(self, session: Session, profile: UserProfile, symbol: str) -> str:
        latest = session.scalar(
            select(SignalSnapshot)
            .where(SignalSnapshot.profile_id == profile.id)
            .where(SignalSnapshot.symbol == symbol.upper())
            .order_by(desc(SignalSnapshot.created_at))
        )
        if latest:
            rationale = latest.rationale or {}
            reasons_for = rationale.get("reasons_for", [])
            reasons_against = rationale.get("reasons_against", [])
            return (
                f"{latest.summary}\n"
                f"A favor: {', '.join(reasons_for) or 'sin datos'}.\n"
                f"En contra: {', '.join(reasons_against) or 'sin objeciones claras'}."
            )

        candidates = {candidate.symbol: candidate for candidate in self.discovery_service.demo_candidates()}
        candidate = candidates.get(symbol.upper())
        if not candidate:
            return f"No tengo contexto suficiente sobre {symbol.upper()} en este MVP."

        signal = self.signal_engine.evaluate(
            session,
            profile,
            self._candidate_to_signal_request(candidate, profile.telegram_chat_id),
        )
        return (
            f"{signal.summary}\n"
            f"A favor: {', '.join(signal.reasons_for)}.\n"
            f"En contra: {', '.join(signal.reasons_against) or 'sin objeciones claras'}."
        )

    @staticmethod
    def _candidate_to_signal_request(candidate: CandidateInput, telegram_chat_id: str | None) -> SignalEvaluationRequest:
        technical_setup = (candidate.narrative_strength + candidate.catalyst_strength + candidate.liquidity_score) / 3
        return SignalEvaluationRequest(
            telegram_chat_id=telegram_chat_id,
            symbol=candidate.symbol,
            asset_type=candidate.asset_type,
            themes=candidate.themes,
            narrative_strength=candidate.narrative_strength,
            catalyst_score=candidate.catalyst_strength,
            liquidity_quality=candidate.liquidity_score,
            volatility_score=candidate.volatility_score,
            relative_strength=min(1.0, candidate.narrative_strength + 0.04),
            pullback_quality=technical_setup,
            volume_confirmation=candidate.liquidity_score,
            regime_alignment=0.65,
            context_notes=[f"Demo candidate {candidate.name}"],
        )

    def _format_latest_alerts(self, session: Session, profile_id: int) -> str:
        alerts = list(
            session.scalars(
                select(SignalSnapshot)
                .where(SignalSnapshot.profile_id == profile_id)
                .order_by(desc(SignalSnapshot.created_at))
                .limit(5)
            )
        )
        if not alerts:
            return "Todavia no hay alertas generadas. Usa /scan o /why SYMBOL para crear contexto."
        lines = ["Ultimas alertas:"]
        for alert in alerts:
            lines.append(f"- {alert.symbol} | {alert.signal_type} | score={alert.score:.2f} | {alert.summary}")
        return "\n".join(lines)

    @staticmethod
    def _help_text() -> str:
        return (
            "Comandos disponibles:\n"
            "/profile - ver perfil inferido\n"
            "/seed BTC ETH PLTR OKLO - actualizar semillas\n"
            "/buy PLTR 21.5 qty=20 thesis=\"AI gov software\" - registrar compra\n"
            "/portfolio - ver posiciones abiertas\n"
            "/scan - ranking demo de oportunidades\n"
            "/why MSTR - explicar una candidata\n"
            "/alerts - ver ultimas alertas\n"
            "Tambien puedes escribir: he comprado PLTR a 21.5"
        )

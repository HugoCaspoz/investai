from __future__ import annotations

from apps.api.investai_api.models import AssetType, Position
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.api.investai_api.models import SignalSnapshot, UserProfile
from apps.api.investai_api.schemas import PositionCreate, ProfileBootstrapRequest
from apps.api.investai_api.services.command_parser import CommandParser
from apps.api.investai_api.services.discovery_service import DiscoveryService
from apps.api.investai_api.services.market_data_service import MarketDataService
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
        self.market_data_service = MarketDataService()
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
            live_candidates = await self.market_data_service.fetch_live_candidates(profile)
            if not live_candidates:
                reply = "Ahora mismo no tengo candidatos live disponibles. Configura proveedores reales o espera al siguiente barrido."
            else:
                ranked = self.discovery_service.rank_candidates(profile, live_candidates)
                candidate_map = {candidate.symbol: candidate for candidate in live_candidates}
                lines = ["Top candidatos del scanner live con recomendacion manual:"]
                for item in ranked[:5]:
                    candidate = candidate_map[item.symbol]
                    signal = self.signal_engine.preview(
                        profile,
                        self.market_data_service.build_signal_request(candidate, profile.telegram_chat_id),
                    )
                    price_text = f" | precio=${item.current_price:,.4f}" if item.current_price is not None else ""
                    day_text = (
                        f" | 24h={item.price_change_percentage_24h:+.2f}%"
                        if item.price_change_percentage_24h is not None
                        else ""
                    )
                    lines.append(
                        f"- {item.symbol} | {signal.manual_recommendation} | {item.bucket} | fuente={item.source} | score={signal.score:.2f} | riesgo={signal.risk_level}{price_text}{day_text}"
                    )
                reply = "\n".join(lines)
        elif parsed.action == "alerts":
            reply = self._format_latest_alerts(session, profile.id)
        elif parsed.action == "analyze_symbol":
            reply = await self._explain_symbol(session, profile, parsed.payload["symbol"])
        else:
            reply = "No he entendido el mensaje. Usa /help, /scan, /analyze PLTR, /profile, /portfolio, o escribe 'he comprado PLTR a 21.5'."

        delivered = await self.telegram_service.send_message(chat_id, reply)
        return {"handled": True, "reply_text": reply, "delivered": delivered}

    async def _explain_symbol(self, session: Session, profile: UserProfile, symbol: str) -> str:
        position = self.portfolio_service.get_open_position_by_symbol(session, profile.id, symbol)
        asset_type = AssetType(position.asset_type) if position else self.profile_service.infer_asset_type(symbol)
        candidate = await self.market_data_service.fetch_live_candidate_for_symbol(profile, symbol, asset_type)
        if not candidate:
            return f"No tengo contexto live suficiente sobre {symbol.upper()} ahora mismo."

        if position:
            signal = self.signal_engine.preview(
                profile,
                self.market_data_service.build_position_review_request(position, candidate, profile.telegram_chat_id),
            )
            pnl_pct = self.market_data_service.extract_pnl_pct(position, candidate)
            return self._render_live_analysis(signal, candidate.symbol, candidate.source, candidate.current_price, pnl_pct, position)

        signal = self.signal_engine.preview(
            profile,
            self.market_data_service.build_signal_request(candidate, profile.telegram_chat_id),
        )
        return self._render_live_analysis(signal, candidate.symbol, candidate.source, candidate.current_price, None, None)

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
            return "Todavia no hay alertas generadas. Usa /scan o /analyze SYMBOL para crear contexto."
        lines = ["Ultimas alertas:"]
        for alert in alerts:
            rationale = alert.rationale or {}
            manual_recommendation = rationale.get("manual_recommendation", alert.signal_type)
            lines.append(f"- {alert.symbol} | {manual_recommendation} | score={alert.score:.2f} | {alert.summary}")
        return "\n".join(lines)

    @staticmethod
    def _render_live_analysis(signal, symbol: str, source: str, current_price: float | None, pnl_pct: float | None, position: Position | None) -> str:
        lines = [
            f"{symbol} | recomendacion manual: {signal.manual_recommendation}",
            f"Modo: {signal.execution_mode}",
            f"Fuente: {source}",
            f"Bucket: {signal.bucket}",
            f"Riesgo: {signal.risk_level}",
            f"Score: {signal.score:.2f} | Confianza: {signal.confidence:.2f}",
        ]
        if current_price is not None:
            lines.append(f"Precio actual: ${current_price:,.4f}")
        if position:
            lines.append(f"Entrada registrada: ${position.entry_price:,.4f}")
            if pnl_pct is not None:
                lines.append(f"Rendimiento desde entrada: {pnl_pct:+.2f}%")
        lines.append("")
        lines.append(f"Resumen: {signal.summary}")
        lines.append(f"A favor: {', '.join(signal.reasons_for[:4])}.")
        if signal.reasons_against:
            lines.append(f"En contra: {', '.join(signal.reasons_against[:3])}.")
        lines.append(f"Siguiente paso sugerido: {signal.action_hint}.")
        return "\n".join(lines)

    @staticmethod
    def _help_text() -> str:
        return (
            "Comandos disponibles:\n"
            "/profile - ver perfil inferido\n"
            "/seed BTC ETH PLTR OKLO - actualizar semillas\n"
            "/buy PLTR 21.5 qty=20 thesis=\"AI gov software\" - registrar compra\n"
            "/portfolio - ver posiciones abiertas\n"
            "/scan - ranking live de oportunidades\n"
            "/analyze BTC - analizar un simbolo con recomendacion manual\n"
            "/alerts - ver ultimas alertas\n"
            "Tambien puedes escribir: he comprado PLTR a 21.5 o analiza PLTR"
        )

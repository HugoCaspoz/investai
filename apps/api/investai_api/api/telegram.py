from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from apps.api.investai_api.config import get_settings
from apps.api.investai_api.db import get_session
from apps.api.investai_api.schemas import TelegramWebhookResponse
from apps.api.investai_api.services.telegram_handler import TelegramHandler

router = APIRouter(tags=["telegram"])

telegram_handler = TelegramHandler()
settings = get_settings()


@router.post("/webhooks/telegram", response_model=TelegramWebhookResponse)
async def telegram_webhook(
    payload: dict,
    session: Session = Depends(get_session),
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
) -> TelegramWebhookResponse:
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")
    result = await telegram_handler.handle_update(session, payload)
    return TelegramWebhookResponse(**result)

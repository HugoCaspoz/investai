from __future__ import annotations

import httpx

from apps.api.investai_api.config import get_settings


class TelegramService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def send_message(self, chat_id: str, text: str) -> bool:
        if not self.settings.telegram_bot_token:
            return False
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return True

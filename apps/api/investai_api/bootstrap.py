import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.investai_api.api.routes import router as api_router
from apps.api.investai_api.api.telegram import router as telegram_router
from apps.api.investai_api.config import get_settings
from apps.api.investai_api.db import Base, engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        logger.exception("Database initialization failed during startup")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        description=(
            "Telegram-first investment alert assistant focused on discovery, "
            "portfolio monitoring and explainable signals."
        ),
    )
    app.include_router(api_router)
    app.include_router(telegram_router)
    return app

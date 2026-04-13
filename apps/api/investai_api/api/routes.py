from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from apps.api.investai_api.config import get_settings
from apps.api.investai_api.catalog import DEMO_CANDIDATES
from apps.api.investai_api.db import get_session
from apps.api.investai_api.schemas import (
    CandidateInput,
    DiscoveryRequest,
    PositionCloseRead,
    PositionCloseRequest,
    PositionCreate,
    PositionRead,
    ProfileBootstrapRequest,
    ProfileRead,
    RankedCandidateResponse,
    SignalAnalyticsRead,
    SignalEvaluationRequest,
    SignalRead,
)
from apps.api.investai_api.services.analytics_service import AnalyticsService
from apps.api.investai_api.services.discovery_service import DiscoveryService
from apps.api.investai_api.services.job_service import JobService
from apps.api.investai_api.services.market_data_service import MarketDataService
from apps.api.investai_api.services.portfolio_service import PortfolioService
from apps.api.investai_api.services.profile_service import ProfileService
from apps.api.investai_api.services.signal_engine import SignalEngine

router = APIRouter(prefix="/api", tags=["api"])

profile_service = ProfileService()
portfolio_service = PortfolioService()
discovery_service = DiscoveryService()
signal_engine = SignalEngine()
job_service = JobService()
market_data_service = MarketDataService()
analytics_service = AnalyticsService()
settings = get_settings()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "investai-api",
        "message_template_version": "telegram-v3",
        "analytics_mode": "paper-trades-enabled",
    }


@router.post("/profile/bootstrap", response_model=ProfileRead)
def bootstrap_profile(payload: ProfileBootstrapRequest, session: Session = Depends(get_session)) -> ProfileRead:
    profile = profile_service.bootstrap_profile(session, payload)
    return profile_service.to_schema(profile, session)


@router.get("/profile/by-chat/{telegram_chat_id}", response_model=ProfileRead)
def get_profile_by_chat(telegram_chat_id: str, session: Session = Depends(get_session)) -> ProfileRead:
    profile = profile_service.get_by_chat_id(session, telegram_chat_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile_service.to_schema(profile, session)


@router.post("/positions", response_model=PositionRead)
def create_position(payload: PositionCreate, session: Session = Depends(get_session)) -> PositionRead:
    profile = profile_service.resolve_profile_or_create(
        session,
        profile_id=payload.profile_id,
        telegram_chat_id=payload.telegram_chat_id,
    )
    if not profile:
        raise HTTPException(status_code=400, detail="Profile context is required")
    return portfolio_service.register_position(session, profile, payload)


@router.get("/positions", response_model=list[PositionRead])
def list_positions(
    telegram_chat_id: str | None = None,
    profile_id: int | None = None,
    session: Session = Depends(get_session),
) -> list[PositionRead]:
    profile = profile_service.resolve_profile(session, profile_id=profile_id, telegram_chat_id=telegram_chat_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return portfolio_service.list_open_positions(session, profile.id)


@router.post("/positions/close", response_model=PositionCloseRead)
def close_position(payload: PositionCloseRequest, session: Session = Depends(get_session)) -> PositionCloseRead:
    profile = profile_service.resolve_profile_or_create(
        session,
        profile_id=payload.profile_id,
        telegram_chat_id=payload.telegram_chat_id,
    )
    if not profile:
        raise HTTPException(status_code=400, detail="Profile context is required")
    try:
        return portfolio_service.close_position(session, profile, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/catalog/demo-candidates", response_model=list[CandidateInput])
def demo_candidates() -> list[CandidateInput]:
    return [CandidateInput.model_validate(candidate) for candidate in DEMO_CANDIDATES]


@router.post("/discovery/rank", response_model=list[RankedCandidateResponse])
def rank_candidates(payload: DiscoveryRequest, session: Session = Depends(get_session)) -> list[RankedCandidateResponse]:
    profile = profile_service.resolve_profile_or_create(
        session,
        profile_id=payload.profile_id,
        telegram_chat_id=payload.telegram_chat_id,
    )
    if not profile:
        raise HTTPException(status_code=400, detail="Profile context is required")
    return discovery_service.rank_candidates(profile, payload.candidates)


@router.post("/signals/evaluate", response_model=SignalRead)
def evaluate_signal(payload: SignalEvaluationRequest, session: Session = Depends(get_session)) -> SignalRead:
    profile = profile_service.resolve_profile_or_create(
        session,
        profile_id=payload.profile_id,
        telegram_chat_id=payload.telegram_chat_id,
    )
    return signal_engine.evaluate(session, profile, payload)


@router.get("/diagnostics/live")
async def live_diagnostics(
    telegram_chat_id: str | None = None,
    profile_id: int | None = None,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    profile = profile_service.resolve_profile(session, profile_id=profile_id, telegram_chat_id=telegram_chat_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    diagnostics = await market_data_service.diagnose_live_sources(profile)
    return {
        "status": "ok",
        "profile_id": profile.id,
        "telegram_chat_id": profile.telegram_chat_id,
        **diagnostics,
    }


@router.get("/analytics/signals", response_model=SignalAnalyticsRead)
def signal_analytics(
    telegram_chat_id: str | None = None,
    profile_id: int | None = None,
    session: Session = Depends(get_session),
) -> SignalAnalyticsRead:
    profile = profile_service.resolve_profile(session, profile_id=profile_id, telegram_chat_id=telegram_chat_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return analytics_service.build_signal_analytics(session, profile.id)


async def _run_scan_job(
    session: Session = Depends(get_session),
    x_internal_job_token: str | None = Header(default=None, alias="X-Internal-Job-Token"),
) -> dict[str, int | str]:
    if settings.internal_job_token and x_internal_job_token != settings.internal_job_token:
        raise HTTPException(status_code=403, detail="Invalid job token")
    result = await job_service.run_scan(session)
    return {"status": "ok", **result}


@router.post("/jobs/scan")
async def run_scan(
    session: Session = Depends(get_session),
    x_internal_job_token: str | None = Header(default=None, alias="X-Internal-Job-Token"),
) -> dict[str, int | str]:
    return await _run_scan_job(session, x_internal_job_token)


@router.post("/jobs/scan-demo")
async def run_demo_scan_compat(
    session: Session = Depends(get_session),
    x_internal_job_token: str | None = Header(default=None, alias="X-Internal-Job-Token"),
) -> dict[str, int | str]:
    return await _run_scan_job(session, x_internal_job_token)

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from apps.api.investai_api.models import AlertPriority, AssetType, PaperTradeStatus, SignalOutcomeStatus, SignalType


class ProfileBootstrapRequest(BaseModel):
    telegram_chat_id: str | None = None
    display_name: str | None = None
    seeds: list[str] = Field(default_factory=list)
    risk_tolerance: str = "aggressive"
    horizon: str = "swing"
    max_alerts_per_day: int = 3
    notes: str | None = None


class ProfileSeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    asset_type: str
    inferred_themes: list[str]


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_chat_id: str | None
    display_name: str | None
    risk_tolerance: str
    horizon: str
    max_alerts_per_day: int
    theme_weights: dict[str, float]
    preferred_assets: list[str]
    notes: str | None
    created_at: datetime
    updated_at: datetime | None
    seeds: list[ProfileSeedRead] = Field(default_factory=list)


class PositionCreate(BaseModel):
    telegram_chat_id: str | None = None
    profile_id: int | None = None
    symbol: str
    asset_type: AssetType = AssetType.EQUITY
    entry_price: float
    quantity: float | None = None
    thesis: str | None = None
    target_price: float | None = None
    stop_price: float | None = None
    theme: str | None = None


class PositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    symbol: str
    asset_type: str
    entry_price: float
    quantity: float | None
    thesis: str | None
    target_price: float | None
    stop_price: float | None
    theme: str | None
    status: str
    opened_at: datetime


class PositionCloseRequest(BaseModel):
    telegram_chat_id: str | None = None
    profile_id: int | None = None
    symbol: str
    exit_price: float
    note: str | None = None


class PositionCloseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    position_id: int
    symbol: str
    asset_type: str
    entry_price: float
    exit_price: float
    quantity: float | None
    return_pct: float
    note: str | None
    closed_at: datetime


class CandidateInput(BaseModel):
    symbol: str
    name: str
    asset_type: AssetType
    themes: list[str]
    source: str = "demo"
    narrative_strength: float = 0.5
    catalyst_strength: float = 0.5
    liquidity_score: float = 0.5
    volatility_score: float = 0.5
    current_price: float | None = None
    price_change_percentage_24h: float | None = None
    price_change_percentage_7d: float | None = None
    market_cap: float | None = None
    market_cap_rank: int | None = None
    dollar_volume: float | None = None


class DiscoveryRequest(BaseModel):
    telegram_chat_id: str | None = None
    profile_id: int | None = None
    candidates: list[CandidateInput]


class RankedCandidateResponse(BaseModel):
    symbol: str
    name: str
    asset_type: AssetType
    source: str
    bucket: str
    score: float
    profile_fit: float
    risk_level: str
    reasons: list[str]
    current_price: float | None = None
    price_change_percentage_24h: float | None = None
    price_change_percentage_7d: float | None = None


class SignalEvaluationRequest(BaseModel):
    telegram_chat_id: str | None = None
    profile_id: int | None = None
    symbol: str
    asset_type: AssetType
    source: str = "unknown"
    bucket: str | None = None
    themes: list[str] = Field(default_factory=list)
    name: str | None = None
    price: float | None = None
    price_change_percentage_24h: float | None = None
    price_change_percentage_7d: float | None = None
    market_cap: float | None = None
    dollar_volume: float | None = None
    technical_setup: float | None = None
    relative_strength: float = 0.5
    pullback_quality: float = 0.5
    volume_confirmation: float = 0.5
    catalyst_score: float = 0.5
    narrative_strength: float = 0.5
    liquidity_quality: float = 0.5
    regime_alignment: float = 0.5
    technical_deterioration: float = 0.0
    thesis_break_risk: float = 0.0
    target_or_extension_score: float = 0.0
    event_risk: float = 0.0
    portfolio_concentration_risk: float = 0.0
    volatility_score: float = 0.5
    context_notes: list[str] = Field(default_factory=list)


class SignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    symbol: str
    asset_type: AssetType
    source: str = "unknown"
    signal_type: SignalType
    alert_priority: AlertPriority
    bucket: str
    score: float
    confidence: float
    risk_level: str
    summary: str
    manual_recommendation: str
    execution_mode: str
    action_hint: str
    reasons_for: list[str]
    reasons_against: list[str]
    subscores: dict[str, float]


class SignalOutcomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_snapshot_id: int
    symbol: str
    asset_type: str
    source: str
    bucket: str | None
    signal_type: str
    entry_price: float
    evaluation_horizon_hours: int
    status: SignalOutcomeStatus
    outcome_price: float | None
    return_pct: float | None
    outcome_label: str | None
    created_at: datetime
    evaluated_at: datetime | None


class PaperTradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    open_signal_snapshot_id: int
    close_signal_snapshot_id: int | None
    symbol: str
    asset_type: str
    source: str
    bucket: str | None
    status: PaperTradeStatus
    entry_price: float
    exit_price: float | None
    return_pct: float | None
    opened_at: datetime
    closed_at: datetime | None


class AnalyticsBucketRead(BaseModel):
    resolved_count: int
    win_rate: float | None
    avg_return_pct: float | None


class SignalAnalyticsRead(BaseModel):
    resolved_count: int
    pending_count: int
    win_rate: float | None
    avg_return_pct: float | None
    best_return_pct: float | None
    worst_return_pct: float | None
    by_bucket: dict[str, AnalyticsBucketRead]
    closed_positions_count: int
    closed_positions_avg_return_pct: float | None
    paper_trades_closed_count: int
    paper_trades_open_count: int
    paper_trades_win_rate: float | None
    paper_trades_avg_return_pct: float | None
    recent_paper_trades: list[PaperTradeRead] = Field(default_factory=list)
    recent_outcomes: list[SignalOutcomeRead] = Field(default_factory=list)


class TelegramWebhookResponse(BaseModel):
    ok: bool = True
    handled: bool
    reply_text: str
    delivered: bool

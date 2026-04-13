from __future__ import annotations

from collections import Counter
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.investai_api.catalog import CRYPTO_SYMBOLS, DEFAULT_PROFILE_SEEDS, KEYWORD_THEME_MAP, SEED_THEME_MAP
from apps.api.investai_api.models import AssetType, ProfileSeed, UserProfile
from apps.api.investai_api.schemas import ProfileBootstrapRequest, ProfileRead, ProfileSeedRead


class ProfileService:
    def bootstrap_profile(self, session: Session, payload: ProfileBootstrapRequest) -> UserProfile:
        profile = self.resolve_profile(session, telegram_chat_id=payload.telegram_chat_id)
        if not profile:
            profile = UserProfile(telegram_chat_id=payload.telegram_chat_id)
            session.add(profile)
            session.flush()

        seeds = payload.seeds or self.current_seed_symbols(session, profile.id) or DEFAULT_PROFILE_SEEDS
        profile.display_name = payload.display_name or profile.display_name
        profile.risk_tolerance = payload.risk_tolerance
        profile.horizon = payload.horizon
        profile.max_alerts_per_day = payload.max_alerts_per_day
        profile.notes = payload.notes or profile.notes
        profile.preferred_assets = sorted({self.infer_asset_type(seed).value for seed in seeds})
        profile.theme_weights = self.infer_theme_weights(seeds)

        session.execute(delete(ProfileSeed).where(ProfileSeed.profile_id == profile.id))
        for seed in seeds:
            session.add(
                ProfileSeed(
                    profile_id=profile.id,
                    symbol=seed.upper(),
                    asset_type=self.infer_asset_type(seed).value,
                    inferred_themes=self.themes_for_seed(seed),
                )
            )
        session.commit()
        session.refresh(profile)
        return profile

    def ensure_profile(
        self,
        session: Session,
        telegram_chat_id: str,
        display_name: str | None = None,
    ) -> UserProfile:
        profile = self.get_by_chat_id(session, telegram_chat_id)
        if profile:
            if display_name and profile.display_name != display_name:
                profile.display_name = display_name
                session.commit()
                session.refresh(profile)
            return profile
        return self.bootstrap_profile(
            session,
            ProfileBootstrapRequest(
                telegram_chat_id=telegram_chat_id,
                display_name=display_name,
                seeds=DEFAULT_PROFILE_SEEDS,
            ),
        )

    def resolve_profile(
        self,
        session: Session,
        profile_id: int | None = None,
        telegram_chat_id: str | None = None,
    ) -> UserProfile | None:
        if profile_id is not None:
            return session.get(UserProfile, profile_id)
        if telegram_chat_id:
            return self.get_by_chat_id(session, telegram_chat_id)
        return None

    def resolve_profile_or_create(
        self,
        session: Session,
        profile_id: int | None = None,
        telegram_chat_id: str | None = None,
    ) -> UserProfile | None:
        profile = self.resolve_profile(session, profile_id=profile_id, telegram_chat_id=telegram_chat_id)
        if profile:
            return profile
        if telegram_chat_id:
            return self.ensure_profile(session, telegram_chat_id)
        return None

    def get_by_chat_id(self, session: Session, telegram_chat_id: str) -> UserProfile | None:
        return session.scalar(select(UserProfile).where(UserProfile.telegram_chat_id == telegram_chat_id))

    def current_seed_symbols(self, session: Session, profile_id: int) -> list[str]:
        return list(session.scalars(select(ProfileSeed.symbol).where(ProfileSeed.profile_id == profile_id)))

    def load_seeds(self, session: Session, profile_id: int) -> list[ProfileSeed]:
        statement = select(ProfileSeed).where(ProfileSeed.profile_id == profile_id).order_by(ProfileSeed.symbol.asc())
        return list(session.scalars(statement))

    def to_schema(self, profile: UserProfile, session: Session) -> ProfileRead:
        seeds = [ProfileSeedRead.model_validate(seed) for seed in self.load_seeds(session, profile.id)]
        return ProfileRead(
            id=profile.id,
            telegram_chat_id=profile.telegram_chat_id,
            display_name=profile.display_name,
            risk_tolerance=profile.risk_tolerance,
            horizon=profile.horizon,
            max_alerts_per_day=profile.max_alerts_per_day,
            theme_weights=profile.theme_weights,
            preferred_assets=profile.preferred_assets,
            notes=profile.notes,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            seeds=seeds,
        )

    def render_profile_summary(self, profile: UserProfile, session: Session) -> str:
        seeds = ", ".join(self.current_seed_symbols(session, profile.id)) or "sin semillas"
        top_themes = ", ".join(
            f"{theme}:{weight:.2f}" for theme, weight in sorted(profile.theme_weights.items(), key=lambda item: item[1], reverse=True)[:5]
        )
        return (
            f"Perfil activo\n"
            f"- riesgo: {profile.risk_tolerance}\n"
            f"- horizonte: {profile.horizon}\n"
            f"- max alertas/dia: {profile.max_alerts_per_day}\n"
            f"- semillas: {seeds}\n"
            f"- temas: {top_themes or 'sin inferencia'}"
        )

    def infer_theme_weights(self, seeds: Sequence[str]) -> dict[str, float]:
        counts: Counter[str] = Counter()
        for seed in seeds:
            for theme in self.themes_for_seed(seed):
                counts[theme] += 1
        total = sum(counts.values()) or 1
        return {theme: round(count / total, 3) for theme, count in counts.items()}

    def themes_for_seed(self, seed: str) -> list[str]:
        normalized = seed.strip().upper()
        if normalized in SEED_THEME_MAP:
            return SEED_THEME_MAP[normalized]
        inferred: list[str] = []
        for keyword, themes in KEYWORD_THEME_MAP.items():
            if keyword in normalized:
                inferred.extend(themes)
        return inferred or ["growth"]

    def infer_asset_type(self, symbol: str) -> AssetType:
        return AssetType.CRYPTO if symbol.strip().upper() in CRYPTO_SYMBOLS else AssetType.EQUITY

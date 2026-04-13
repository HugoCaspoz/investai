from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx

from apps.api.investai_api.catalog import SEED_THEME_MAP, THEMATIC_EQUITY_UNIVERSE
from apps.api.investai_api.config import get_settings
from apps.api.investai_api.models import AssetType, Position, UserProfile
from apps.api.investai_api.schemas import CandidateInput, SignalEvaluationRequest


class MarketDataService:
    COINGECKO_PUBLIC_BASE_URL = "https://api.coingecko.com/api/v3"
    COINGECKO_PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"
    POLYGON_BASE_URL = "https://api.polygon.io"
    TWELVEDATA_BASE_URL = "https://api.twelvedata.com"
    STABLECOIN_SYMBOLS = {"USDT", "USDC", "DAI", "FDUSD", "PYUSD", "USDE", "USDS"}

    def __init__(self) -> None:
        self.settings = get_settings()

    async def fetch_live_candidates(self, profile: UserProfile) -> list[CandidateInput]:
        candidates_by_symbol: dict[str, CandidateInput] = {}
        try:
            for candidate in await self._fetch_coingecko_candidates(profile):
                candidates_by_symbol[candidate.symbol] = candidate
        except Exception:
            pass
        try:
            for candidate in await self._fetch_twelvedata_candidates(profile):
                candidates_by_symbol.setdefault(candidate.symbol, candidate)
        except Exception:
            pass
        try:
            for candidate in await self._fetch_polygon_candidates(profile):
                candidates_by_symbol.setdefault(candidate.symbol, candidate)
        except Exception:
            pass
        return list(candidates_by_symbol.values())

    async def diagnose_live_sources(self, profile: UserProfile) -> dict[str, object]:
        coingecko_status = await self._diagnose_coingecko(profile)
        twelvedata_status = await self._diagnose_twelvedata(profile)
        polygon_status = await self._diagnose_polygon(profile)
        total_candidates = (
            int(coingecko_status["candidates"])
            + int(twelvedata_status["candidates"])
            + int(polygon_status["candidates"])
        )
        return {
            "ok": total_candidates > 0,
            "total_candidates": total_candidates,
            "coingecko": coingecko_status,
            "twelvedata": twelvedata_status,
            "polygon": polygon_status,
        }

    async def fetch_live_candidate_for_symbol(
        self,
        profile: UserProfile,
        symbol: str,
        asset_type: AssetType,
    ) -> CandidateInput | None:
        normalized = symbol.upper()
        if asset_type == AssetType.CRYPTO:
            candidates = await self._fetch_crypto_candidates_for_symbols([normalized], profile)
            return candidates[0] if candidates else None
        candidates = await self._fetch_twelvedata_quotes([normalized], profile)
        if candidates:
            return candidates[0]
        candidates = await self._fetch_polygon_snapshots([normalized], profile)
        return candidates[0] if candidates else None

    async def _fetch_coingecko_candidates(self, profile: UserProfile) -> list[CandidateInput]:
        base_url, headers = self._coingecko_client_config()
        trending_ids = await self._fetch_trending_ids(base_url, headers)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base_url}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "volume_desc",
                    "per_page": 100,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d",
                },
                headers=headers,
            )
            response.raise_for_status()
            rows = response.json()
        return self._coingecko_rows_to_candidates(rows, trending_ids)

    async def _fetch_crypto_candidates_for_symbols(
        self,
        symbols: list[str],
        profile: UserProfile,
    ) -> list[CandidateInput]:
        base_url, headers = self._coingecko_client_config()
        ids = await self._resolve_coingecko_ids(symbols, base_url, headers)
        if not ids:
            return []
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base_url}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": ",".join(ids),
                    "order": "market_cap_desc",
                    "per_page": max(len(ids), 1),
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d",
                },
                headers=headers,
            )
            response.raise_for_status()
            rows = response.json()
        return self._coingecko_rows_to_candidates(rows, trending_ids=set(), include_looser_filters=True)

    async def _fetch_polygon_candidates(self, profile: UserProfile) -> list[CandidateInput]:
        thematic_universe = self._equity_universe_for_profile(profile)
        symbols = [item["symbol"] for item in thematic_universe]
        return await self._fetch_polygon_snapshots(symbols, profile)

    async def _fetch_twelvedata_candidates(self, profile: UserProfile) -> list[CandidateInput]:
        thematic_universe = self._equity_universe_for_profile(profile)
        symbols = self._twelvedata_symbol_slice([item["symbol"] for item in thematic_universe])
        return await self._fetch_twelvedata_quotes(symbols, profile)

    async def _fetch_twelvedata_quotes(
        self,
        symbols: list[str],
        profile: UserProfile,
    ) -> list[CandidateInput]:
        if not self.settings.twelvedata_api_key or not symbols:
            return []
        metadata = {item["symbol"]: item for item in THEMATIC_EQUITY_UNIVERSE}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.TWELVEDATA_BASE_URL}/quote",
                params={
                    "symbol": ",".join(symbols),
                    "apikey": self.settings.twelvedata_api_key,
                    "interval": "1day",
                },
            )
            response.raise_for_status()
            payload = response.json()

        rows = self._normalize_twelvedata_batch_payload(payload)
        candidates: list[CandidateInput] = []
        for symbol, row in rows.items():
            meta = metadata.get(symbol, {"name": symbol, "themes": SEED_THEME_MAP.get(symbol, ["growth"])})
            price = self._to_float(row.get("close")) or self._to_float(row.get("price"))
            prev_close = self._to_float(row.get("previous_close"))
            if price is None or price <= 0:
                continue
            change_24h = self._to_float(row.get("percent_change"))
            if change_24h is None and prev_close and prev_close > 0:
                change_24h = ((price - prev_close) / prev_close) * 100
            volume = self._to_float(row.get("volume"))
            dollar_volume = volume * price if volume is not None else None
            if dollar_volume is not None and dollar_volume < 5_000_000:
                continue
            themes = list(meta["themes"])
            momentum_score = self._clamp(((change_24h or 0.0) + 4.0) / 10.0)
            liquidity_score = self._liquidity_score(dollar_volume)
            narrative_strength = self._clamp(0.30 + 0.26 * momentum_score + 0.18 * min(1.0, 0.16 * len(themes)) + 0.14 * liquidity_score)
            catalyst_strength = self._clamp(0.28 + 0.34 * momentum_score + 0.18 * liquidity_score)
            candidates.append(
                CandidateInput(
                    symbol=symbol,
                    name=str(meta["name"]),
                    asset_type=AssetType.EQUITY,
                    source="twelvedata",
                    themes=themes,
                    narrative_strength=narrative_strength,
                    catalyst_strength=catalyst_strength,
                    liquidity_score=liquidity_score,
                    volatility_score=self._clamp(abs(change_24h or 0.0) / 10.0),
                    current_price=price,
                    price_change_percentage_24h=change_24h,
                    price_change_percentage_7d=None,
                    market_cap=None,
                    market_cap_rank=None,
                    dollar_volume=dollar_volume,
                )
            )
        return candidates

    async def _diagnose_coingecko(self, profile: UserProfile) -> dict[str, object]:
        plan = (self.settings.coingecko_api_plan or "demo").strip().lower()
        try:
            candidates = await self._fetch_coingecko_candidates(profile)
            return {
                "configured": bool(self.settings.coingecko_api_key),
                "plan": plan,
                "ok": len(candidates) > 0,
                "candidates": len(candidates),
                "error": None,
            }
        except Exception as exc:
            return {
                "configured": bool(self.settings.coingecko_api_key),
                "plan": plan,
                "ok": False,
                "candidates": 0,
                "error": str(exc),
            }

    async def _diagnose_twelvedata(self, profile: UserProfile) -> dict[str, object]:
        symbols = self._twelvedata_symbol_slice([item["symbol"] for item in self._equity_universe_for_profile(profile)])
        try:
            candidates = await self._fetch_twelvedata_quotes(symbols, profile)
            return {
                "configured": bool(self.settings.twelvedata_api_key),
                "ok": len(candidates) > 0,
                "candidates": len(candidates),
                "symbols_checked": symbols,
                "scan_limit": self.settings.twelvedata_scan_limit,
                "error": None,
            }
        except Exception as exc:
            return {
                "configured": bool(self.settings.twelvedata_api_key),
                "ok": False,
                "candidates": 0,
                "symbols_checked": symbols,
                "scan_limit": self.settings.twelvedata_scan_limit,
                "error": str(exc),
            }

    async def _diagnose_polygon(self, profile: UserProfile) -> dict[str, object]:
        try:
            candidates = await self._fetch_polygon_candidates(profile)
            return {
                "configured": bool(self.settings.polygon_api_key),
                "ok": len(candidates) > 0,
                "candidates": len(candidates),
                "error": None,
            }
        except Exception as exc:
            return {
                "configured": bool(self.settings.polygon_api_key),
                "ok": False,
                "candidates": 0,
                "error": str(exc),
            }

    async def _fetch_polygon_snapshots(
        self,
        symbols: list[str],
        profile: UserProfile,
    ) -> list[CandidateInput]:
        if not self.settings.polygon_api_key or not symbols:
            return []
        metadata = {item["symbol"]: item for item in THEMATIC_EQUITY_UNIVERSE}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.POLYGON_BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers",
                params={
                    "tickers": ",".join(symbols),
                    "apiKey": self.settings.polygon_api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("tickers", [])
        candidates: list[CandidateInput] = []
        for row in rows:
            symbol = str(row.get("ticker", "")).upper()
            if not symbol:
                continue
            meta = metadata.get(symbol, {"name": symbol, "themes": SEED_THEME_MAP.get(symbol, ["growth"])})
            price = self._extract_polygon_price(row)
            prev_close = self._to_float(self._dig(row, "prevDay", "c"))
            volume = self._to_float(self._dig(row, "day", "v"))
            volume_weighted_price = self._to_float(self._dig(row, "day", "vw")) or price
            if price is None or prev_close is None or prev_close <= 0:
                continue
            dollar_volume = volume * volume_weighted_price if volume is not None and volume_weighted_price is not None else None
            if dollar_volume is not None and dollar_volume < 10_000_000:
                continue
            market_cap = None
            change_24h = ((price - prev_close) / prev_close) * 100
            change_7d = None
            themes = list(meta["themes"])
            momentum_score = self._clamp((change_24h + 4.0) / 10.0)
            week_score = self._clamp((change_24h + 4.0) / 12.0)
            volume_score = self._liquidity_score(dollar_volume)
            theme_bonus = min(1.0, 0.16 * len(themes))
            candidates.append(
                CandidateInput(
                    symbol=symbol,
                    name=str(meta["name"]),
                    asset_type=AssetType.EQUITY,
                    source="polygon",
                    themes=themes,
                    narrative_strength=self._clamp(0.32 + 0.22 * week_score + 0.18 * theme_bonus + 0.15 * volume_score),
                    catalyst_strength=self._clamp(0.28 + 0.30 * momentum_score + 0.22 * volume_score + 0.10 * week_score),
                    liquidity_score=volume_score,
                    volatility_score=self._clamp(abs(change_24h) / 10.0),
                    current_price=price,
                    price_change_percentage_24h=change_24h,
                    price_change_percentage_7d=change_7d,
                    market_cap=market_cap,
                    market_cap_rank=None,
                    dollar_volume=dollar_volume,
                )
            )
        return candidates

    def build_signal_request(self, candidate: CandidateInput, telegram_chat_id: str | None) -> SignalEvaluationRequest:
        change_24h = candidate.price_change_percentage_24h or 0.0
        change_7d = candidate.price_change_percentage_7d or 0.0
        has_weekly_data = candidate.price_change_percentage_7d is not None
        trend_score = self._clamp(((change_7d if has_weekly_data else change_24h) + 6.0) / (18.0 if has_weekly_data else 12.0))
        pullback_score = self._pullback_score(change_24h, change_7d if has_weekly_data else None)
        overextension_score = max(
            self._clamp((change_24h - 12.0) / 20.0),
            self._clamp((change_7d - 25.0) / 45.0) if has_weekly_data else 0.0,
        )
        sharp_drop_score = max(
            self._clamp((-change_24h - 5.0) / 10.0),
            self._clamp((-change_7d - 12.0) / 18.0) if has_weekly_data else 0.0,
        )
        technical_setup = self._clamp(
            0.20
            + 0.28 * trend_score
            + 0.24 * pullback_score
            + 0.16 * candidate.liquidity_score
            + 0.12 * candidate.narrative_strength
            - 0.20 * overextension_score
            - 0.12 * sharp_drop_score
        )
        relative_strength = self._clamp(0.55 * trend_score + 0.45 * self._clamp((change_24h + 4.0) / 10.0))
        pullback_quality = self._clamp(0.25 + 0.55 * pullback_score + 0.10 * candidate.narrative_strength - 0.20 * overextension_score)
        volume_confirmation = candidate.liquidity_score
        regime_alignment = 0.65 if "crypto" in candidate.themes else 0.58
        context_notes = [f"source={candidate.source}"]
        if candidate.market_cap is not None:
            context_notes.append(f"market_cap={candidate.market_cap:.0f}")
        if candidate.dollar_volume is not None:
            context_notes.append(f"dollar_volume={candidate.dollar_volume:.0f}")
        if overextension_score > 0:
            context_notes.append(f"overextension_score={overextension_score:.2f}")
        if sharp_drop_score > 0:
            context_notes.append(f"sharp_drop_score={sharp_drop_score:.2f}")

        return SignalEvaluationRequest(
            telegram_chat_id=telegram_chat_id,
            symbol=candidate.symbol,
            asset_type=candidate.asset_type,
            source=candidate.source,
            name=candidate.name,
            themes=candidate.themes,
            price=candidate.current_price,
            price_change_percentage_24h=candidate.price_change_percentage_24h,
            price_change_percentage_7d=candidate.price_change_percentage_7d,
            market_cap=candidate.market_cap,
            dollar_volume=candidate.dollar_volume,
            technical_setup=technical_setup,
            relative_strength=relative_strength,
            pullback_quality=pullback_quality,
            volume_confirmation=volume_confirmation,
            catalyst_score=candidate.catalyst_strength,
            narrative_strength=candidate.narrative_strength,
            liquidity_quality=candidate.liquidity_score,
            regime_alignment=regime_alignment,
            technical_deterioration=sharp_drop_score,
            target_or_extension_score=overextension_score,
            event_risk=self._clamp(0.10 + 0.25 * candidate.volatility_score + 0.30 * overextension_score),
            volatility_score=candidate.volatility_score,
            context_notes=context_notes,
        )

    def build_position_review_request(
        self,
        position: Position,
        candidate: CandidateInput,
        telegram_chat_id: str | None,
    ) -> SignalEvaluationRequest:
        price = candidate.current_price or position.entry_price
        pnl_pct = ((price - position.entry_price) / position.entry_price) * 100 if position.entry_price else 0.0
        change_24h = candidate.price_change_percentage_24h or 0.0
        change_7d = candidate.price_change_percentage_7d or 0.0
        stop_distance_score = 0.0
        if position.stop_price:
            stop_distance_score = self._clamp((position.stop_price - price) / position.stop_price * -1.5)
        target_hit_score = 0.0
        if position.target_price and position.target_price > 0:
            target_hit_score = self._clamp((price / position.target_price) - 0.95)
        extension_score = max(target_hit_score, self._clamp((pnl_pct - 12.0) / 18.0))
        technical_deterioration = max(
            self._clamp((-change_24h - 2.5) / 7.0),
            self._clamp((-change_7d - 4.0) / 12.0),
        )
        thesis_break_risk = max(
            technical_deterioration,
            stop_distance_score if position.stop_price and price <= position.stop_price else 0.0,
        )
        event_risk = 0.20 + 0.35 * candidate.volatility_score
        if pnl_pct > 0 and change_24h < -3:
            event_risk = min(1.0, event_risk + 0.10)

        context_notes = [
            f"source={candidate.source}",
            f"entry_price={position.entry_price:.4f}",
            f"pnl_pct={pnl_pct:.2f}",
        ]
        if position.target_price:
            context_notes.append(f"target_price={position.target_price:.4f}")
        if position.stop_price:
            context_notes.append(f"stop_price={position.stop_price:.4f}")
        if position.thesis:
            context_notes.append(f"thesis={position.thesis}")

        return SignalEvaluationRequest(
            telegram_chat_id=telegram_chat_id,
            symbol=position.symbol,
            asset_type=AssetType(position.asset_type),
            source=candidate.source,
            name=candidate.name,
            themes=candidate.themes,
            price=price,
            price_change_percentage_24h=candidate.price_change_percentage_24h,
            price_change_percentage_7d=candidate.price_change_percentage_7d,
            market_cap=candidate.market_cap,
            dollar_volume=candidate.dollar_volume,
            technical_setup=self._clamp(0.45 + 0.25 * candidate.narrative_strength),
            relative_strength=self._clamp(((change_7d + 5.0) / 18.0)),
            pullback_quality=self._clamp(0.50 + 0.15 * candidate.narrative_strength - 0.20 * technical_deterioration),
            volume_confirmation=candidate.liquidity_score,
            catalyst_score=candidate.catalyst_strength,
            narrative_strength=candidate.narrative_strength,
            liquidity_quality=candidate.liquidity_score,
            regime_alignment=0.55,
            technical_deterioration=technical_deterioration,
            thesis_break_risk=thesis_break_risk,
            target_or_extension_score=max(extension_score, self._clamp((pnl_pct - 8.0) / 20.0)),
            event_risk=event_risk,
            portfolio_concentration_risk=0.0,
            volatility_score=candidate.volatility_score,
            context_notes=context_notes,
        )

    def extract_pnl_pct(self, position: Position, candidate: CandidateInput | None) -> float | None:
        if not candidate or candidate.current_price is None or not position.entry_price:
            return None
        return ((candidate.current_price - position.entry_price) / position.entry_price) * 100

    async def _fetch_trending_ids(self, base_url: str, headers: dict[str, str]) -> set[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/search/trending", headers=headers)
                response.raise_for_status()
                payload = response.json()
            return {
                str(item.get("item", {}).get("id", "")).lower()
                for item in payload.get("coins", [])
                if item.get("item", {}).get("id")
            }
        except Exception:
            return set()

    async def _resolve_coingecko_ids(
        self,
        symbols: list[str],
        base_url: str,
        headers: dict[str, str],
    ) -> list[str]:
        resolved: list[str] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for symbol in symbols:
                response = await client.get(
                    f"{base_url}/search",
                    params={"query": symbol},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                candidates = payload.get("coins", [])
                exact = next(
                    (coin for coin in candidates if str(coin.get("symbol", "")).upper() == symbol.upper()),
                    None,
                )
                if exact and exact.get("id"):
                    resolved.append(str(exact["id"]))
        return resolved

    def _coingecko_rows_to_candidates(
        self,
        rows: list[dict[str, object]],
        trending_ids: set[str],
        include_looser_filters: bool = False,
    ) -> list[CandidateInput]:
        candidates: list[CandidateInput] = []
        for row in rows:
            symbol = str(row.get("symbol", "")).upper()
            coin_id = str(row.get("id", "")).lower()
            current_price = self._to_float(row.get("current_price"))
            market_cap = self._to_float(row.get("market_cap"))
            total_volume = self._to_float(row.get("total_volume"))
            if not symbol or symbol in self.STABLECOIN_SYMBOLS:
                continue
            if current_price is None or current_price <= 0:
                continue
            if not include_looser_filters and (market_cap is None or market_cap < 500_000_000):
                continue
            if not include_looser_filters and (total_volume is None or total_volume < 20_000_000):
                continue

            change_24h = self._to_float(row.get("price_change_percentage_24h_in_currency"))
            change_7d = self._to_float(row.get("price_change_percentage_7d_in_currency"))
            themes = self._infer_crypto_themes(coin_id, symbol, str(row.get("name", "")))
            trending_boost = 1.0 if coin_id in trending_ids else 0.0
            momentum_score = self._clamp(((change_24h or 0.0) + 3.0) / 12.0)
            week_score = self._clamp(((change_7d or 0.0) + 5.0) / 18.0)
            volume_score = self._liquidity_score(total_volume)
            rank_score = self._market_cap_rank_score(row.get("market_cap_rank"))
            theme_bonus = min(1.0, 0.18 * len(themes))

            candidates.append(
                CandidateInput(
                    symbol=symbol,
                    name=str(row.get("name", symbol)),
                    asset_type=AssetType.CRYPTO,
                    source="coingecko",
                    themes=themes,
                    narrative_strength=self._clamp(
                        0.30 + 0.22 * trending_boost + 0.20 * rank_score + 0.18 * week_score + 0.10 * theme_bonus
                    ),
                    catalyst_strength=self._clamp(
                        0.28 + 0.30 * momentum_score + 0.22 * trending_boost + 0.20 * volume_score
                    ),
                    liquidity_score=volume_score,
                    volatility_score=self._clamp(abs(change_24h or 0.0) / 15.0),
                    current_price=current_price,
                    price_change_percentage_24h=change_24h,
                    price_change_percentage_7d=change_7d,
                    market_cap=market_cap,
                    market_cap_rank=self._to_int(row.get("market_cap_rank")),
                    dollar_volume=total_volume,
                )
            )
        return candidates

    def _coingecko_client_config(self) -> tuple[str, dict[str, str]]:
        plan = (self.settings.coingecko_api_plan or "demo").strip().lower()
        headers = {"accept": "application/json"}
        if plan == "pro":
            base_url = self.COINGECKO_PRO_BASE_URL
            if self.settings.coingecko_api_key:
                headers["x-cg-pro-api-key"] = self.settings.coingecko_api_key
            return base_url, headers

        base_url = self.COINGECKO_PUBLIC_BASE_URL
        if self.settings.coingecko_api_key:
            headers["x-cg-demo-api-key"] = self.settings.coingecko_api_key
        return base_url, headers

    def _twelvedata_symbol_slice(self, symbols: list[str]) -> list[str]:
        limit = max(1, self.settings.twelvedata_scan_limit)
        if len(symbols) <= limit:
            return symbols
        total_windows = math.ceil(len(symbols) / limit)
        window_index = int(datetime.now(timezone.utc).timestamp() // 900) % total_windows
        start = window_index * limit
        end = start + limit
        return symbols[start:end]

    def _equity_universe_for_profile(self, profile: UserProfile) -> list[dict[str, object]]:
        preferred_themes = {theme for theme, weight in profile.theme_weights.items() if weight >= 0.05}
        selected = [
            item for item in THEMATIC_EQUITY_UNIVERSE if preferred_themes.intersection(item["themes"])
        ]
        return selected or THEMATIC_EQUITY_UNIVERSE

    @staticmethod
    def _pullback_score(change_24h: float, change_7d: float | None) -> float:
        if -3.5 <= change_24h <= 1.5 and (change_7d is None or change_7d >= -6.0):
            return 1.0
        if 1.5 < change_24h <= 7.0:
            return 0.72
        if -6.0 <= change_24h < -3.5 and (change_7d is None or change_7d >= 0.0):
            return 0.55
        if change_24h > 12.0:
            return 0.10
        return 0.35

    @staticmethod
    def _infer_crypto_themes(coin_id: str, symbol: str, name: str) -> list[str]:
        fingerprint = f"{coin_id} {symbol} {name}".upper()
        themes = ["crypto"]
        if any(token in fingerprint for token in {"BTC", "BITCOIN"}):
            themes.append("strong_narrative")
        if any(token in fingerprint for token in {"ETH", "ETHEREUM", "LINK", "AAVE", "MKR", "ONDO", "ENA", "LDO"}):
            themes.append("crypto_infra")
        if any(token in fingerprint for token in {"SOL", "SUI", "SEI", "APT", "TAO", "INJ", "FET", "RENDER", "RNDR", "AIOZ"}):
            themes.extend(["growth", "strong_narrative"])
        if any(token in fingerprint for token in {"TAO", "FET", "RENDER", "RNDR", "AIOZ", "ARKM"}):
            themes.append("ai_software")
        if any(token in fingerprint for token in {"ARB", "OP", "TIA", "SUI", "SEI", "APT", "NEAR"}):
            themes.append("growth")
        if "growth" not in themes and any(token in fingerprint for token in {"SOL", "ETH", "BTC"}):
            themes.append("growth")
        return sorted(set(themes))

    @staticmethod
    def _extract_polygon_price(row: dict[str, object]) -> float | None:
        return (
            MarketDataService._to_float(MarketDataService._dig(row, "lastTrade", "p"))
            or MarketDataService._to_float(MarketDataService._dig(row, "min", "c"))
            or MarketDataService._to_float(MarketDataService._dig(row, "day", "c"))
        )

    @staticmethod
    def _normalize_twelvedata_batch_payload(payload: object) -> dict[str, dict[str, object]]:
        if isinstance(payload, list):
            rows: dict[str, dict[str, object]] = {}
            for item in payload:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol", "")).upper()
                if symbol:
                    rows[symbol] = item
            return rows

        if not isinstance(payload, dict):
            return {}

        if payload.get("status") == "error":
            message = str(payload.get("message", "unknown Twelve Data error"))
            raise ValueError(message)

        symbol = str(payload.get("symbol", "")).upper()
        if symbol:
            return {symbol: payload}

        rows: dict[str, dict[str, object]] = {}
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            nested_symbol = str(value.get("symbol", key)).upper()
            status = str(value.get("status", "")).lower()
            if status == "error":
                continue
            if nested_symbol:
                rows[nested_symbol] = value
        return rows

    @staticmethod
    def _dig(data: dict[str, object], *keys: str) -> object:
        current: object = data
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _liquidity_score(dollar_volume: float | None) -> float:
        if dollar_volume is None or dollar_volume <= 0:
            return 0.0
        return MarketDataService._clamp((math.log10(dollar_volume) - 6.5) / 2.5)

    @staticmethod
    def _market_cap_rank_score(rank: object) -> float:
        rank_int = MarketDataService._to_int(rank)
        if rank_int is None:
            return 0.35
        return MarketDataService._clamp(1 - ((rank_int - 1) / 100.0))

    @staticmethod
    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

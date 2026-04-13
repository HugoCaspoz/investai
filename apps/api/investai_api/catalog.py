from __future__ import annotations

from apps.api.investai_api.models import AssetType

DEFAULT_PROFILE_SEEDS = ["BTC", "ETH", "SOL", "TSLA", "PLTR", "COIN", "OKLO"]
CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "RNDR", "INJ", "TAO"}

SEED_THEME_MAP: dict[str, list[str]] = {
    "BTC": ["crypto", "strong_narrative"],
    "ETH": ["crypto", "crypto_infra"],
    "SOL": ["crypto", "growth"],
    "TSLA": ["ev", "growth", "strong_narrative"],
    "PLTR": ["ai_software", "growth", "strong_catalyst"],
    "COIN": ["crypto_infra", "growth", "strong_catalyst"],
    "CRCL": ["crypto_infra", "growth", "strong_catalyst"],
    "OKLO": ["nuclear", "small_mid_growth", "strong_catalyst"],
    "LCID": ["ev", "small_mid_growth", "strong_narrative"],
    "CCJ": ["nuclear", "strong_catalyst"],
    "SMR": ["nuclear", "growth", "strong_catalyst"],
    "MSTR": ["crypto_infra", "growth", "strong_narrative"],
}

KEYWORD_THEME_MAP: dict[str, list[str]] = {
    "BITCOIN": ["crypto"],
    "ETHEREUM": ["crypto", "crypto_infra"],
    "CRYPTO": ["crypto", "crypto_infra"],
    "NUCLEAR": ["nuclear"],
    "URANIUM": ["nuclear"],
    "IA": ["ai_software"],
    "AI": ["ai_software"],
    "EV": ["ev"],
    "GROWTH": ["growth"],
    "SMALL": ["small_mid_growth"],
    "MID": ["small_mid_growth"],
}

DEMO_CANDIDATES: list[dict[str, object]] = [
    {
        "symbol": "MSTR",
        "name": "MicroStrategy",
        "asset_type": AssetType.EQUITY,
        "themes": ["crypto", "crypto_infra", "growth", "strong_narrative"],
        "narrative_strength": 0.90,
        "catalyst_strength": 0.76,
        "liquidity_score": 0.95,
        "volatility_score": 0.90,
        "market_cap": 34_000_000_000,
        "dollar_volume": 3_500_000_000,
    },
    {
        "symbol": "RNDR",
        "name": "Render",
        "asset_type": AssetType.CRYPTO,
        "themes": ["crypto", "ai_software", "growth", "small_mid_growth"],
        "narrative_strength": 0.84,
        "catalyst_strength": 0.68,
        "liquidity_score": 0.78,
        "volatility_score": 0.86,
        "market_cap": 4_200_000_000,
        "dollar_volume": 280_000_000,
    },
    {
        "symbol": "SMR",
        "name": "NuScale Power",
        "asset_type": AssetType.EQUITY,
        "themes": ["nuclear", "growth", "strong_catalyst"],
        "narrative_strength": 0.82,
        "catalyst_strength": 0.73,
        "liquidity_score": 0.74,
        "volatility_score": 0.84,
        "market_cap": 2_900_000_000,
        "dollar_volume": 120_000_000,
    },
    {
        "symbol": "IREN",
        "name": "Iris Energy",
        "asset_type": AssetType.EQUITY,
        "themes": ["crypto_infra", "growth", "small_mid_growth", "strong_catalyst"],
        "narrative_strength": 0.79,
        "catalyst_strength": 0.71,
        "liquidity_score": 0.80,
        "volatility_score": 0.88,
        "market_cap": 1_900_000_000,
        "dollar_volume": 165_000_000,
    },
    {
        "symbol": "RKLB",
        "name": "Rocket Lab",
        "asset_type": AssetType.EQUITY,
        "themes": ["growth", "strong_catalyst", "strong_narrative"],
        "narrative_strength": 0.86,
        "catalyst_strength": 0.72,
        "liquidity_score": 0.82,
        "volatility_score": 0.73,
        "market_cap": 4_700_000_000,
        "dollar_volume": 190_000_000,
    },
    {
        "symbol": "CCJ",
        "name": "Cameco",
        "asset_type": AssetType.EQUITY,
        "themes": ["nuclear", "strong_catalyst"],
        "narrative_strength": 0.74,
        "catalyst_strength": 0.69,
        "liquidity_score": 0.88,
        "volatility_score": 0.55,
        "market_cap": 24_000_000_000,
        "dollar_volume": 310_000_000,
    },
]


def bucket_for_themes(themes: list[str]) -> str:
    if "crypto_infra" in themes:
        return "crypto infra"
    if "crypto" in themes:
        return "crypto"
    if "ai_software" in themes:
        return "AI / growth"
    if "nuclear" in themes:
        return "nuclear / uranium"
    if "ev" in themes:
        return "EV"
    return "growth"

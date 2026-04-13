from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedCommand:
    action: str
    payload: dict[str, Any] = field(default_factory=dict)


class CommandParser:
    buy_pattern = re.compile(
        r"he comprado\s+(?P<symbol>[a-zA-Z0-9._-]+)\s+a\s+(?P<price>\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    add_position_pattern = re.compile(
        r"anade\s+(?P<symbol>[a-zA-Z0-9._-]+)\s+a\s+cartera\s+a\s+(?P<price>\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def parse(self, text: str) -> ParsedCommand:
        normalized = text.strip()
        if not normalized:
            return ParsedCommand(action="empty")
        if normalized.startswith("/"):
            return self._parse_slash_command(normalized)
        return self._parse_natural_language(normalized)

    def _parse_slash_command(self, text: str) -> ParsedCommand:
        parts = shlex.split(text)
        command = parts[0].lower()
        if command == "/start":
            return ParsedCommand(action="start")
        if command == "/help":
            return ParsedCommand(action="help")
        if command in {"/profile", "/prefs"}:
            return ParsedCommand(action="profile")
        if command == "/portfolio":
            return ParsedCommand(action="portfolio")
        if command == "/alerts":
            return ParsedCommand(action="alerts")
        if command == "/scan":
            return ParsedCommand(action="scan")
        if command == "/seed":
            seeds = [token.replace(",", "").upper() for token in parts[1:]]
            return ParsedCommand(action="seed", payload={"seeds": [seed for seed in seeds if seed]})
        if command == "/why" and len(parts) >= 2:
            return ParsedCommand(action="why", payload={"symbol": parts[1].upper()})
        if command == "/buy" and len(parts) >= 3:
            return ParsedCommand(action="register_position", payload=self._parse_position_tokens(parts[1:]))
        return ParsedCommand(action="unknown")

    def _parse_natural_language(self, text: str) -> ParsedCommand:
        for pattern in (self.buy_pattern, self.add_position_pattern):
            match = pattern.search(text)
            if match:
                return ParsedCommand(
                    action="register_position",
                    payload={
                        "symbol": match.group("symbol").upper(),
                        "entry_price": float(match.group("price")),
                    },
                )
        return ParsedCommand(action="unknown")

    @staticmethod
    def _parse_position_tokens(tokens: list[str]) -> dict[str, Any]:
        symbol = tokens[0].upper()
        entry_price = float(tokens[1])
        payload: dict[str, Any] = {"symbol": symbol, "entry_price": entry_price}
        for token in tokens[2:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if key == "qty":
                payload["quantity"] = float(value)
            elif key == "thesis":
                payload["thesis"] = value
            elif key == "target":
                payload["target_price"] = float(value)
            elif key == "stop":
                payload["stop_price"] = float(value)
        return payload

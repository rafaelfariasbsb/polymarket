#!/usr/bin/env python3
"""
Market configuration for multi-asset/multi-window support.
Reads MARKET_ASSET and MARKET_WINDOW from .env and derives all dependent values.

Supported assets: btc, eth, sol, xrp
Supported windows: 5, 15 (minutes)
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Mapping of asset ticker to Binance symbol suffix
SUPPORTED_ASSETS = {'btc', 'eth', 'sol', 'xrp'}
SUPPORTED_WINDOWS = {5, 15}


class MarketConfig:
    """Centralized market configuration derived from MARKET_ASSET and MARKET_WINDOW."""

    def __init__(self, asset=None, window_min=None):
        self.asset = (asset or os.getenv('MARKET_ASSET', 'btc')).lower()
        self.window_min = int(window_min or os.getenv('MARKET_WINDOW', '15'))

        if self.asset not in SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset '{self.asset}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_ASSETS))}"
            )
        if self.window_min not in SUPPORTED_WINDOWS:
            raise ValueError(
                f"Unsupported window '{self.window_min}m'. "
                f"Supported: {', '.join(str(w) for w in sorted(SUPPORTED_WINDOWS))}"
            )

    @property
    def slug_prefix(self):
        """Polymarket event slug prefix, e.g. 'btc-updown-15m'."""
        return f"{self.asset}-updown-{self.window_min}m"

    @property
    def binance_symbol(self):
        """Binance trading pair symbol, e.g. 'BTCUSDT'."""
        return f"{self.asset.upper()}USDT"

    @property
    def ws_symbol(self):
        """Binance WebSocket symbol (lowercase), e.g. 'btcusdt'."""
        return f"{self.asset}usdt"

    @property
    def window_seconds(self):
        """Window duration in seconds, e.g. 900 for 15m."""
        return self.window_min * 60

    @property
    def display_name(self):
        """Display name for the asset, e.g. 'BTC'."""
        return self.asset.upper()

    def __repr__(self):
        return f"MarketConfig(asset='{self.asset}', window={self.window_min}m)"

#!/usr/bin/env python3
"""
Shared functions for Polymarket connection and operations
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    AssetType,
    BalanceAllowanceParams,
    OpenOrderParams,
)
from py_clob_client.constants import POLYGON

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# Persistent HTTP session (reuses TCP connections via keep-alive)
_session = requests.Session()

# Polymarket Proxy Wallet Factory (Polygon)
PROXY_FACTORY = "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
PROXY_INIT_CODE_HASH = bytes.fromhex(
    "d21df8dc65880a8606f09fe0ce3df9b8869287ab0b058be05aa9e8af6330a00b"
)

UTC = timezone.utc
ET = timezone(timedelta(hours=-5))
BRASILIA = timezone(timedelta(hours=-3))


def load_config():
    """Loads .env and returns configuration"""
    load_dotenv()
    private_key = os.getenv("POLYMARKET_API_KEY")
    limit = float(os.getenv("POSITION_LIMIT", "0"))
    if not private_key:
        raise ValueError("POLYMARKET_API_KEY not configured in .env")
    if limit <= 0:
        raise ValueError("POSITION_LIMIT not configured or invalid in .env")
    return private_key, limit


def derive_proxy_address(eoa_address):
    """Derives proxy wallet address via CREATE2 (Polymarket factory)"""
    eoa_bytes = bytes.fromhex(eoa_address.lower().replace("0x", ""))
    salt = Web3.keccak(eoa_bytes)
    proxy = Web3.keccak(
        b"\xff"
        + bytes.fromhex(PROXY_FACTORY.lower().replace("0x", ""))
        + salt
        + PROXY_INIT_CODE_HASH
    )[12:]
    return Web3.to_checksum_address(proxy)


def create_client():
    """Creates and authenticates ClobClient (Level 2) with proxy wallet"""
    private_key, limit = load_config()
    key = private_key.replace("0x", "") if private_key.startswith("0x") else private_key

    # Derive EOA and proxy addresses
    eoa_address = Account.from_key(key).address
    proxy_address = derive_proxy_address(eoa_address)

    client = ClobClient(
        CLOB,
        key=key,
        chain_id=POLYGON,
        signature_type=1,  # POLY_PROXY (wallet exported from Polymarket)
        funder=proxy_address,  # Proxy contract address holding the funds
    )

    creds = client.create_or_derive_api_creds()
    if not creds:
        raise ConnectionError("Could not derive API credentials")
    client.set_api_creds(creds)

    return client, limit


def get_balance(client):
    """Returns available USDC balance (deducting open buy orders)"""
    resp = client.get_balance_allowance(
        params=BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=1,
        )
    )
    total_balance = float(resp.get("balance", 0)) / 1e6

    # Deduct value locked in open buy orders
    try:
        orders = client.get_orders(params=OpenOrderParams())
        order_list = orders if isinstance(orders, list) else orders.get("data", [])
        locked = 0.0
        for order in order_list:
            if order.get("side", "").upper() == "BUY":
                price = float(order.get("price", 0))
                size = float(order.get("original_size", 0))
                size_matched = float(order.get("size_matched", 0))
                remaining = size - size_matched
                if remaining > 0 and price > 0:
                    locked += remaining * price
        total_balance -= locked
    except Exception:
        pass

    return max(total_balance, 0.0)


def parse_iso(s):
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(UTC)


def coerce_list(maybe_list):
    if isinstance(maybe_list, list):
        return maybe_list
    if isinstance(maybe_list, str):
        try:
            v = json.loads(maybe_list)
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return []


def find_current_market(config=None):
    """
    Finds the active updown market for the configured asset and window.
    Args:
        config: MarketConfig instance (if None, uses default btc/15m)
    Returns (event, market, token_up, token_down, time_to_close_min)
    """
    if config is None:
        from market_config import MarketConfig
        config = MarketConfig()

    window_min = config.window_min
    window_sec = config.window_seconds
    slug_prefix = config.slug_prefix

    now_local = datetime.now()
    now_brasilia = now_local.replace(tzinfo=BRASILIA)
    now_et = now_brasilia.astimezone(ET)

    minute = now_et.minute
    window_start_minute = (minute // window_min) * window_min

    window_start = now_et.replace(minute=window_start_minute, second=0, microsecond=0)
    window_start_utc = window_start.astimezone(UTC)
    target_timestamp = int(window_start_utc.timestamp())
    rounded = round(target_timestamp / window_sec) * window_sec

    possible_timestamps = [rounded, target_timestamp, rounded - window_sec, rounded + window_sec]

    event = None
    for ts in possible_timestamps:
        slug = f"{slug_prefix}-{ts}"
        try:
            r = _session.get(f"{GAMMA}/events", params={"slug": slug}, timeout=10)
            if r.status_code == 200 and r.json():
                ev = r.json()[0]
                markets = ev.get("markets") or []
                if markets:
                    m = markets[0]
                    est = parse_iso(m.get("eventStartTime"))
                    diff = abs((est - window_start_utc).total_seconds())
                    if diff < 120:
                        event = ev
                        break
        except Exception:
            continue

    if not event:
        raise RuntimeError(f"{config.display_name} {window_min}m market not found for current window")

    markets = event.get("markets", [])
    market = markets[0]

    clob_ids = coerce_list(market.get("clobTokenIds"))
    outcomes = coerce_list(market.get("outcomes"))

    if len(clob_ids) < 2:
        raise RuntimeError("UP/DOWN tokens not found in market")

    if outcomes and "Up" in outcomes and "Down" in outcomes:
        idx_up = outcomes.index("Up")
        idx_down = outcomes.index("Down")
    else:
        idx_up, idx_down = 0, 1

    token_up = clob_ids[idx_up]
    token_down = clob_ids[idx_down]

    end_date = parse_iso(market.get("endDate"))
    now_utc = datetime.now(UTC)
    time_remaining = (end_date - now_utc).total_seconds() / 60

    return event, market, token_up, token_down, time_remaining


def get_token_position(client, token_id):
    """Returns share quantity of a conditional token"""
    try:
        resp = client.get_balance_allowance(
            params=BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=token_id,
                signature_type=1,
            )
        )
        return float(resp.get("balance", 0)) / 1e6
    except Exception:
        return 0.0


def get_open_orders_value(client, token_id):
    """Returns total USD value of open orders for a token"""
    total = 0.0
    try:
        resp = client.get_orders(params=OpenOrderParams(asset_id=token_id))
        orders = resp if isinstance(resp, list) else resp.get("data", [])
        for order in orders:
            price = float(order.get("price", 0))
            size = float(order.get("original_size", 0))
            size_matched = float(order.get("size_matched", 0))
            remaining = size - size_matched
            if remaining > 0 and price > 0:
                total += remaining * price
    except Exception:
        pass
    return total


def check_limit(client, token_up, token_down, new_order_value):
    """
    Checks if the new order exceeds POSITION_LIMIT.
    Returns (can_trade, current_exposure, limit)
    """
    _, limit = load_config()

    # Value of open positions (shares * current price)
    up_shares = get_token_position(client, token_up)
    down_shares = get_token_position(client, token_down)

    # Current prices to calculate USD value
    try:
        up_price = float(
            _session.get(
                f"{CLOB}/price",
                params={"token_id": token_up, "side": "SELL"},
                timeout=10,
            ).json()["price"]
        )
    except Exception:
        up_price = 0.0

    try:
        down_price = float(
            _session.get(
                f"{CLOB}/price",
                params={"token_id": token_down, "side": "SELL"},
                timeout=10,
            ).json()["price"]
        )
    except Exception:
        down_price = 0.0

    position_value = (up_shares * up_price) + (down_shares * down_price)

    # Pending order value
    orders_value = get_open_orders_value(client, token_up) + get_open_orders_value(client, token_down)

    current_exposure = position_value + orders_value
    total_exposure = current_exposure + new_order_value

    can_trade = total_exposure <= limit
    return can_trade, current_exposure, limit


def monitor_order(client, order_id, interval=3, timeout_sec=300, cancel_fn=None, quiet=False):
    """
    Monitors an order until filled, cancelled, or timeout.
    cancel_fn: callable that returns True to cancel the order (e.g. ESC pressed)
    quiet: if True, suppress all print output
    Returns (final_status, order_details)
    """
    start = time.time()
    last_status = None

    while True:
        # Check external cancellation
        if cancel_fn and cancel_fn():
            if not quiet:
                print(f"\n   Cancelling order (ESC)...")
            try:
                client.cancel(order_id)
            except Exception:
                pass
            return "CANCELLED", None

        elapsed = time.time() - start
        if elapsed > timeout_sec:
            if not quiet:
                print(f"\n   Timeout ({timeout_sec}s) reached. Cancelling order...")
            try:
                client.cancel(order_id)
            except Exception:
                pass
            return "TIMEOUT", None

        try:
            order = client.get_order(order_id)
        except Exception as e:
            if not quiet:
                print(f"\n   Error querying order: {e}")
            time.sleep(interval)
            continue

        status = order.get("status", "UNKNOWN") if isinstance(order, dict) else "UNKNOWN"
        size_matched = float(order.get("size_matched", 0)) if isinstance(order, dict) else 0
        original_size = float(order.get("original_size", 0)) if isinstance(order, dict) else 0

        if status != last_status:
            last_status = status

        # Show progress
        if not quiet:
            if original_size > 0:
                pct = (size_matched / original_size) * 100
                print(f"\r   Status: {status} | Filled: {pct:.1f}% ({size_matched:.2f}/{original_size:.2f}) | {elapsed:.0f}s", end="", flush=True)
            else:
                print(f"\r   Status: {status} | {elapsed:.0f}s", end="", flush=True)

        if status == "MATCHED":
            # Re-query if size_matched == 0 (API race condition)
            if size_matched == 0 and original_size > 0:
                time.sleep(2)
                try:
                    order = client.get_order(order_id)
                    size_matched = float(order.get("size_matched", 0)) if isinstance(order, dict) else 0
                except Exception:
                    pass
            if not quiet:
                print()
            return "FILLED", order

        if status in ("CANCELED", "CANCELLED"):
            if not quiet:
                print()
            return "CANCELLED", order

        time.sleep(interval)

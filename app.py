"""
Aggressive micro-trading Streamlit app skeleton for Capital.com
- Reads credentials from st.secrets (or environment variables)
- Demonstration "aggressive micro" strategy that can run either in LIVE mode (calls Capital.com API)
  or SIMULATION mode (no real trades).
- Uses up to 80% of available funds per user request.
- WARNING: This is example code. Test on a demo account only.
"""

import streamlit as st
import requests
import time
import threading
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(layout="wide", page_title="MicroTrader (demo)")

# ---------- Config ----------
MODE = st.sidebar.selectbox("Mode", ["SIMULATION", "LIVE"])
USE_SIMULATION = (MODE == "SIMULATION")
MAX_RISK_FRACTION = st.sidebar.slider("Max capital usage fraction", 0.1, 0.95, 0.8, 0.05)  # default 0.8
INSTRUMENT = st.sidebar.text_input("Instrument (symbol)", "BTCUSD")
TICK_INTERVAL = st.sidebar.number_input("Poll interval (seconds)", 1.0, 60.0, 2.0, 1.0)

# Read secrets (recommended: set these via Streamlit Secrets or environment variables)
def get_secret(section, key, fallback=None):
    # Try streamlit secrets
    try:
        return st.secrets[section][key]
    except Exception:
        # try env var
        return os.getenv(f"{section.upper()}_{key.upper()}", fallback)

# Capital.com secrets expected to live in st.secrets["capital_com"]
CAP_API_KEY = get_secret("capital_com", "api_key")
CAP_EMAIL = get_secret("capital_com", "email")
CAP_PASSWORD = get_secret("capital_com", "password")

# Safety check: do not run live if no credentials
if MODE == "LIVE" and not (CAP_API_KEY and CAP_EMAIL and CAP_PASSWORD):
    st.error("LIVE mode requires Capital.com credentials in st.secrets or environment variables.")
    st.stop()

# ---------- Simple API helper for Capital.com ----------
class CapitalClient:
    BASE = "https://api-capital.backend-capital.com"  # placeholder base; adjust if your region differs
    def __init__(self, api_key, email=None, password=None):
        self.api_key = api_key
        self.email = email
        self.password = password
        self.headers = {"X-CAP-API-KEY": self.api_key, "Content-Type": "application/json"}
        self.cst = None
        self.xsecurity = None

    def login(self):
        """
        Login to Capital.com to obtain CST and X-SECURITY-TOKEN headers.
        The official flow uses POST /session (and possible encryption step). See docs.
        """
        url = f"{self.BASE}/session"
        payload = {
            "identifier": self.email,
            "password": self.password,
            "encryptedPassword": False
        }
        r = requests.post(url, json=payload, headers=self.headers)
        if r.status_code in (200, 201):
            # Capital.com returns CST and X-SECURITY-TOKEN in response headers
            self.cst = r.headers.get("CST")
            self.xsecurity = r.headers.get("X-SECURITY-TOKEN")
            if self.cst and self.xsecurity:
                self.headers["CST"] = self.cst
                self.headers["X-SECURITY-TOKEN"] = self.xsecurity
                return True, r.json()
            else:
                return False, {"error": "Login succeeded but CST/X-SECURITY-TOKEN missing. See docs."}
        else:
            return False, {"status_code": r.status_code, "text": r.text}

    def get_account_overview(self):
        """
        Example call to retrieve account/funds. Endpoint names may differ; check your API docs.
        We'll try a commonly used endpoint "/clients" or "/tradingAccounts".
        """
        for endpoint in ["/clients", "/tradingAccounts", "/accounts"]:
            try:
                r = requests.get(self.BASE + endpoint, headers=self.headers, timeout=10)
                if r.status_code == 200:
                    return True, r.json()
            except Exception:
                pass
        return False, {"error": "Could not fetch account overview; adjust endpoint according to docs."}

    def place_market_order(self, symbol, direction, size_units, stop_loss=None, take_profit=None):
        """
        Place an order.
        This function is illustrative: adjust payload/endpoint to match Capital.com API.
        """
        payload = {
            "epic": symbol,
            "direction": "BUY" if direction == "long" else "SELL",
            "size": size_units,          # may be notional or units depending on API
            "orderType": "MARKET"
        }
        # attach SL/TP if supported
        if stop_loss:
            payload["stopLoss"] = stop_loss
        if take_profit:
            payload["takeProfit"] = take_profit
        r = requests.post(self.BASE + "/orders", json=payload, headers=self.headers)
        return r.status_code, r.text

    def close_position(self, position_id):
        r = requests.post(self.BASE + f"/positions/{position_id}/close", headers=self.headers)
        return r.status_code, r.text

    def get_prices(self, symbol):
        # Example polling endpoint - adjust if necessary
        r = requests.get(self.BASE + f"/prices/{symbol}", headers=self.headers, timeout=5)
        if r.status_code == 200:
            return True, r.json()
        return False, {"status": r.status_code, "text": r.text}

# ---------- Simulation utilities ----------
class Simulator:
    def __init__(self, starting_equity=10000.0):
        self.equity = starting_equity
        self.available = starting_equity
        self.positions = {}  # id -> dict
        self.trade_id_seq = 0
        # simple synthetic price series
        self.price = 50000.0 if "BTC" in INSTRUMENT else 100.0
        np.random.seed(42)

    def step_price(self):
        # micro price changes with random noise
        move = np.random.normal(loc=0.0, scale=self.price * 0.001)  # 0.1% noise
        self.price = max(0.01, self.price + move)
        return self.price

    def open_position(self, direction, fraction_of_available):
        notional = self.available * fraction_of_available
        size_units = notional / self.price
        self.trade_id_seq += 1
        tid = f"sim-{self.trade_id_seq}"
        self.positions[tid] = {
            "direction": direction,
            "units": size_units,
            "open_price": self.price,
            "notional": notional,
            "current_pnl": 0.0
        }
        self.available -= notional
        return tid

    def update_positions(self):
        for tid, pos in self.positions.items():
            if pos["direction"] == "long":
                pos["current_pnl"] = (self.price - pos["open_price"]) * pos["units"]
            else:
                pos["current_pnl"] = (pos["open_price"] - self.price) * pos["units"]
        # update equity visible
        total_pnl = sum(p["current_pnl"] for p in self.positions.values())
        self.equity = self.available + sum(p["notional"] for p in self.positions.values()) + total_pnl

    def close_position(self, tid):
        pos = self.positions.pop(tid, None)
        if not pos:
            return 0.0
        # realize PnL into available funds
        realized = pos["notional"] + pos["current_pnl"]
        self.available += realized
        self.update_positions()
        return realized

# ---------- Strategy: aggressive micro strategy ----------
class MicroTrader:
    def __init__(self, client=None, sim=None, max_fraction=0.8):
        self.client = client
        self.sim = sim
        self.max_fraction = max_fraction
        self.open_trades = {}  # id -> info
        self.log = []

    def decide_and_trade(self, current_price):
        """
        Very simple micro-strategy:
        - Look at short-term momentum across last N ticks
        - If momentum > threshold -> open long using up to max_fraction of available funds
        - If momentum < -threshold -> open short similarly
        - Use tight TP/SL and close quickly
        """
        # For demo: random micro-decisions
        momentum = np.random.normal(0, 1)
        if momentum > 1.2:
            # open long
            if USE_SIMULATION:
                tid = self.sim.open_position("long", self.max_fraction)
                self.open_trades[tid] = {"direction": "long", "open_price": current_price}
                self.log.append(f"SIM open long {tid} at {current_price:.2f}")
            else:
                # PLACE LIVE ORDER - adjust payload for real API
                status, text = self.client.place_market_order(INSTRUMENT, "long", size_units=0.01,
                                                              stop_loss=None, take_profit=None)
                self.log.append(f"LIVE open long status {status}: {text}")
        elif momentum < -1.2:
            if USE_SIMULATION:
                tid = self.sim.open_position("short", self.max_fraction)
                self.open_trades[tid] = {"direction": "short", "open_price": current_price}
                self.log.append(f"SIM open short {tid} at {current_price:.2f}")
            else:
                status, text = self.client.place_market_order(INSTRUMENT, "short", size_units=0.01)
                self.log.append(f"LIVE open short status {status}: {text}")

        # Aggressive closing: randomly close an open trade quickly
        if self.open_trades and np.random.rand() < 0.5:
            tid = next(iter(self.open_trades.keys()))
            if USE_SIMULATION:
                realized = self.sim.close_position(tid)
                self.log.append(f"SIM closed {tid} realized {realized:.2f}")
            else:
                status, text = self.client.close_position(tid)
                self.log.append(f"LIVE close {tid} status {status}: {text}")
            self.open_trades.pop(tid, None)

# ---------- App layout ----------
st.title("MicroTrader — aggressive micro-trading skeleton")
col1, col2, col3 = st.columns([2, 2, 3])

with col1:
    st.subheader("Equity / Margin / P&L")
    equity_text = st.empty()
    available_text = st.empty()
    margin_text = st.empty()
    total_pnl_text = st.empty()

with col2:
    st.subheader("AI log")
    log_box = st.empty()

with col3:
    st.subheader("Open Trades")
    trades_df_box = st.empty()

# Instantiate client/sim/trader
client = None
sim = None
if USE_SIMULATION:
    sim = Simulator(starting_equity=10000.0)
    trader = MicroTrader(client=None, sim=sim, max_fraction=MAX_RISK_FRACTION)
else:
    client = CapitalClient(CAP_API_KEY, CAP_EMAIL, CAP_PASSWORD)
    ok, resp = client.login()
    if not ok:
        st.error(f"Failed to login: {resp}")
        st.stop()
    # get account overview for baseline
    ok2, acct = client.get_account_overview()
    if not ok2:
        st.warning("Could not fetch account overview; continue but check endpoints/permissions.")
    trader = MicroTrader(client=client, sim=None, max_fraction=MAX_RISK_FRACTION)

# Background polling / trading loop
stop_event = threading.Event()

def run_loop():
    while not stop_event.is_set():
        try:
            if USE_SIMULATION:
                price = sim.step_price()
                sim.update_positions()
                equity = sim.equity
                available = sim.available
                total_pnl = equity - 10000.0
            else:
                okp, pdata = client.get_prices(INSTRUMENT)
                if okp:
                    # adapt to actual payload structure
                    price = pdata.get("bid") if isinstance(pdata, dict) else None
                    if price is None:
                        # fallback: put a dummy price
                        price = 1.0
                else:
                    price = 1.0

                # fetch balances (best-effort)
                okbal, bal = client.get_account_overview()
                if okbal:
                    # This is API-dependent: adapt to actual response shape
                    equity = bal.get("equity", 0.0) if isinstance(bal, dict) else 0.0
                    available = bal.get("available", 0.0) if isinstance(bal, dict) else 0.0
                    total_pnl = bal.get("pl", 0.0) if isinstance(bal, dict) else 0.0
                else:
                    equity = 0.0
                    available = 0.0
                    total_pnl = 0.0

            # strategy decision
            trader.decide_and_trade(price)

            # Update UI
            equity_text.markdown(f"**Equity:** {equity:,.2f}")
            available_text.markdown(f"**Available:** {available:,.2f}")
            margin_text.markdown(f"**Max usage fraction:** {MAX_RISK_FRACTION:.2f}")
            total_pnl_text.markdown(f"**Total P&L:** {total_pnl:,.2f}")

            # trades table
            if USE_SIMULATION:
                trades = []
                for tid, p in sim.positions.items():
                    trades.append({
                        "id": tid,
                        "direction": p["direction"],
                        "units": p["units"],
                        "open_price": p["open_price"],
                        "current_pnl": p["current_pnl"]
                    })
                df = pd.DataFrame(trades)
            else:
                # placeholder live-open-positions fetch (adjust to your API)
                df = pd.DataFrame([{"id":"live-1","direction":"long","open_price":1.0,"current_pnl":0.0}])
            trades_df_box.dataframe(df)

            # logs
            log_box.text("\n".join(trader.log[-20:]))

        except Exception as e:
            st.error(f"Error in loop: {e}")

        time.sleep(TICK_INTERVAL)

# Start / stop buttons
if st.button("Start Trading"):
    if "thread" not in st.session_state:
        st.session_state.thread = threading.Thread(target=run_loop, daemon=True)
        st.session_state.thread.start()
        st.success("Trading loop started.")
    else:
        st.info("Trading loop already running.")

if st.button("Stop Trading"):
    stop_event.set()
    st.session_state.pop("thread", None)
    st.warning("Trading loop stopped.")

st.caption("This is example/demo code. Adapt endpoints, payloads, and risk controls before any LIVE use.")


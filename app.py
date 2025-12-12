# app.py
"""
MicroTrader — updated:
- Top dashboard shows Total Assets, Equity, Available, P&L from Capital.com (best-effort)
- Diversified instrument set
- Simulation mode for safe testing
- Live mode scaffolding (adapt endpoints/payloads to your account)
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
st.set_page_config(layout="wide", page_title="MicroTrader — Diversified")

# ---------- Config ----------
MODE = st.sidebar.selectbox("Mode", ["SIMULATION", "LIVE"])
USE_SIMULATION = (MODE == "SIMULATION")
MAX_RISK_FRACTION = st.sidebar.slider("Max capital usage fraction per trade", 0.05, 0.95, 0.8, 0.05)
TOTAL_POSITION_CAP = st.sidebar.slider("Max total exposure fraction", 0.1, 1.0, 0.9, 0.05)
TICK_INTERVAL = st.sidebar.number_input("Poll interval (s)", 0.5, 60.0, 2.0, 0.5)

# diversified instruments (epics / symbols). Adjust to Capital.com epics you want to trade.
INSTRUMENTS = st.sidebar.multiselect(
    "Instruments (examples)", 
    ["BTCUSD", "ETHUSD", "XAUUSD", "EURUSD", "US100", "DE30", "AAPL", "TSLA", "GBPUSD"],
    default=["BTCUSD", "ETHUSD", "EURUSD", "US100"]
)

def get_secret(section, key, fallback=None):
    try:
        return st.secrets[section][key]
    except Exception:
        return os.getenv(f"{section.upper()}_{key.upper()}", fallback)

CAP_API_KEY = get_secret("capital_com", "api_key")
CAP_EMAIL = get_secret("capital_com", "email")
CAP_PASSWORD = get_secret("capital_com", "password")

if MODE == "LIVE" and not (CAP_API_KEY and CAP_EMAIL and CAP_PASSWORD):
    st.error("LIVE mode requires Capital.com credentials in st.secrets or environment variables.")
    st.stop()

# ---------- Capital.com helper (scaffold) ----------
class CapitalClient:
    BASE = "https://api-capital.backend-capital.com"  # adjust region if required
    def __init__(self, api_key, email=None, password=None):
        self.api_key = api_key
        self.email = email
        self.password = password
        self.headers = {"X-CAP-API-KEY": self.api_key, "Content-Type": "application/json"}
        self.cst = None
        self.xsec = None

    def start_session(self):
        """
        Proper flow per Capital.com docs:
         - GET /session/encryptionKey (optional) -> encrypt password (if required)
         - POST /session -> obtain CST & X-SECURITY-TOKEN headers
        """
        try:
            r = requests.post(self.BASE + "/session",
                              json={"identifier": self.email, "password": self.password, "encryptedPassword": False},
                              headers=self.headers, timeout=10)
            if r.status_code in (200,201):
                self.cst = r.headers.get("CST")
                self.xsec = r.headers.get("X-SECURITY-TOKEN")
                if self.cst and self.xsec:
                    self.headers["CST"] = self.cst
                    self.headers["X-SECURITY-TOKEN"] = self.xsec
                    return True, r.json()
                return False, {"error":"session ok but tokens missing"}
            return False, {"status": r.status_code, "text": r.text}
        except Exception as e:
            return False, {"error": str(e)}

    def get_account_summary(self):
        """
        Best-effort multi-endpoint approach:
         - GET /accounts or /tradingAccounts or /clients
        We'll try several shapes and return the best parsed result:
         {total_assets, equity, available, pnl}
        """
        endpoints = ["/accounts", "/tradingAccounts", "/clients", "/accounts/overview"]
        for ep in endpoints:
            try:
                r = requests.get(self.BASE + ep, headers=self.headers, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    # Attempt to parse common fields; adapt per your account response
                    # 1) If data is dict with 'equity' & 'available'
                    if isinstance(data, dict):
                        equity = data.get("equity") or data.get("balance") or data.get("availableBalance")
                        available = data.get("available") or data.get("freeMargin") or data.get("availableBalance")
                        pnl = data.get("pl") or data.get("unrealisedPnl") or 0.0
                        # total assets fallback
                        total = data.get("totalAssets") or equity or (available + pnl)
                        return True, {"total_assets": total or 0.0, "equity": equity or 0.0, "available": available or 0.0, "pnl": pnl or 0.0}
                    # 2) If data is list, try first account
                    if isinstance(data, list) and data:
                        acct = data[0]
                        equity = acct.get("equity") or acct.get("balance") or 0.0
                        available = acct.get("available") or acct.get("freeMargin") or 0.0
                        pnl = acct.get("pl") or 0.0
                        total = acct.get("totalAssets") or equity
                        return True, {"total_assets": total, "equity": equity, "available": available, "pnl": pnl}
            except Exception:
                continue
        return False, {"error":"no accounts endpoint matched"}

    def get_price(self, epic):
        # Common REST price polling endpoint
        try:
            r = requests.get(self.BASE + f"/prices/{epic}", headers=self.headers, timeout=5)
            if r.status_code == 200:
                return True, r.json()
        except Exception:
            pass
        return False, {}

    def place_market_order(self, epic, direction, notional):
        # Live order scaffolding: replace with exact payload per docs
        payload = {"epic": epic, "direction": "BUY" if direction == "long" else "SELL", "size": notional, "orderType":"MARKET"}
        try:
            r = requests.post(self.BASE + "/orders", json=payload, headers=self.headers, timeout=8)
            return r.status_code, r.text
        except Exception as e:
            return 500, str(e)

    def get_open_positions(self):
        # Try common open positions endpoints
        for ep in ["/positions", "/openPositions", "/tradingPositions"]:
            try:
                r = requests.get(self.BASE + ep, headers=self.headers, timeout=8)
                if r.status_code == 200:
                    return True, r.json()
            except Exception:
                continue
        return False, {}

# ---------- Simulation core ----------
class Simulator:
    def __init__(self, starting_equity=20000.0):
        self.starting_equity = starting_equity
        self.equity = starting_equity
        self.available = starting_equity
        self.positions = {}
        self.price_map = {sym: 100.0 + idx*50 for idx, sym in enumerate(INSTRUMENTS)}
        self.seq = 0
        np.random.seed(1)

    def step_prices(self):
        for sym in self.price_map:
            move = np.random.normal(0, self.price_map[sym]*0.001)
            self.price_map[sym] = max(0.0001, self.price_map[sym] + move)
        return self.price_map

    def open(self, sym, direction, fraction):
        notional = self.available * fraction
        price = self.price_map[sym]
        units = notional / price
        self.seq += 1
        tid = f"sim-{self.seq}"
        self.positions[tid] = {"sym": sym, "direction": direction, "units": units, "open_price": price, "notional": notional, "pnl": 0.0}
        self.available -= notional
        return tid

    def update(self):
        total_pnl = 0
        for p in self.positions.values():
            price = self.price_map[p["sym"]]
            if p["direction"] == "long":
                p["pnl"] = (price - p["open_price"]) * p["units"]
            else:
                p["pnl"] = (p["open_price"] - price) * p["units"]
            total_pnl += p["pnl"]
        self.equity = self.available + sum(p["notional"] for p in self.positions.values()) + total_pnl
        return self.equity, self.available, total_pnl

    def close(self, tid):
        pos = self.positions.pop(tid, None)
        if not pos:
            return 0.0
        realized = pos["notional"] + pos["pnl"]
        self.available += realized
        self.update()
        return realized

# ---------- MicroTrader with diversification ----------
class MicroTrader:
    def __init__(self, client=None, sim=None, max_fraction=0.8, cap=0.9):
        self.client = client
        self.sim = sim
        self.max_fraction = max_fraction
        self.cap = cap
        self.open_trades = {}  # tid -> info
        self.log = []

    def ai_score(self, symbol, price, history=None):
        """
        Placeholder AI scoring:
        - Replace this with your LLM or model that returns a score [-1,1]
        - For now we use a simple randomized score with tiny bias from price moves
        """
        return float(np.tanh(np.random.normal(0,1)))

    def current_total_exposure_fraction(self):
        if USE_SIMULATION:
            used = sum(p["notional"] for p in self.sim.positions.values())
            cap_val = self.sim.equity * self.cap
            return used / cap_val if cap_val>0 else 0.0
        # For LIVE: you should compute used margin from API
        return 0.0

    def decide(self, prices_map):
        # For each instrument compute AI score, attempt to open small micro trade on top picks
        scores = {}
        for sym, price in prices_map.items():
            scores[sym] = self.ai_score(sym, price)
        # pick top positive and top negative scores
        sorted_syms = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        # simple strategy: open long on highest positive if exposure allows, short on lowest negative
        to_try = []
        if sorted_syms:
            top_sym, top_score = sorted_syms[0]
            if top_score > 0.8:
                to_try.append((top_sym, "long", top_score))
            bot_sym, bot_score = sorted_syms[-1]
            if bot_score < -0.8:
                to_try.append((bot_sym, "short", bot_score))
        return to_try

    def execute(self, candidates):
        for sym, direction, score in candidates:
            # check exposure cap
            if self.current_total_exposure_fraction() >= self.cap:
                self.log.append(f"Exposure cap reached; skip {sym}")
                continue
            fraction = self.max_fraction  # fraction of available for this trade
            if USE_SIMULATION:
                tid = self.sim.open(sym, direction, fraction)
                self.open_trades[tid] = {"sym": sym, "dir": direction, "open_price": self.sim.price_map[sym]}
                self.log.append(f"SIM opened {direction} {sym} tid={tid} at {self.sim.price_map[sym]:.2f} score={score:.2f}")
            else:
                status, text = self.client.place_market_order(sym, direction, notional=0)  # notional compute and payload adapt
                self.log.append(f"LIVE order {sym} {direction} -> {status} {text}")

    def maybe_close_some(self):
        # Aggressive micro exit rule: small probability to close oldest
        if USE_SIMULATION and self.open_trades:
            if np.random.rand() < 0.6:
                tid = next(iter(self.open_trades.keys()))
                realized = self.sim.close(tid)
                self.log.append(f"SIM closed {tid} realized {realized:.2f}")
                self.open_trades.pop(tid, None)

# ---------- UI layout ----------
st.title("MicroTrader — Diversified portfolio")
top1, top2, top3 = st.columns([3,2,4])

with top1:
    st.subheader("Account overview")
    total_assets_el = st.empty()
    equity_el = st.empty()
    available_el = st.empty()
    pnl_el = st.empty()

with top2:
    st.subheader("Controls")
    st.write("Mode:", MODE)
    st.write("Max fraction / trade:", f"{MAX_RISK_FRACTION:.2f}")
    st.write("Total exposure cap:", f"{TOTAL_POSITION_CAP:.2f}")

with top3:
    st.subheader("AI Log")
    log_el = st.empty()

st.subheader("Open trades")
trades_el = st.empty()

# instantiate
client = None
sim = None
if USE_SIMULATION:
    sim = Simulator(starting_equity=20000.0)
    trader = MicroTrader(client=None, sim=sim, max_fraction=MAX_RISK_FRACTION, cap=TOTAL_POSITION_CAP)
else:
    client = CapitalClient(CAP_API_KEY, CAP_EMAIL, CAP_PASSWORD)
    ok, resp = client.start_session()
    if not ok:
        st.error(f"Login/session failed: {resp}")
        st.stop()
    trader = MicroTrader(client=client, sim=None, max_fraction=MAX_RISK_FRACTION, cap=TOTAL_POSITION_CAP)

# background loop
stop_event = threading.Event()

def loop():
    while not stop_event.is_set():
        try:
            if USE_SIMULATION:
                prices = sim.step_prices()  # dict symbol->price
                equity, available, total_pnl = sim.update()
            else:
                # live: bulk price fetch
                prices = {}
                for sym in INSTRUMENTS:
                    okp, pdata = client.get_price(sym)
                    if okp and isinstance(pdata, dict):
                        # adapt to response shape; common fields are 'bid', 'ask', 'snapshot'
                        prices[sym] = pdata.get("mid") or pdata.get("bid") or pdata.get("price") or 0.0
                    else:
                        prices[sym] = 0.0
                ok_acc, acc = client.get_account_summary()
                if ok_acc:
                    equity = acc["equity"]
                    available = acc["available"]
                    total_pnl = acc["pnl"]
                else:
                    equity = 0.0; available = 0.0; total_pnl = 0.0

            # update top UI
            total_assets_el.markdown(f"**Total assets:** {equity:,.2f}")
            equity_el.markdown(f"**Equity:** {equity:,.2f}")
            available_el.markdown(f"**Available:** {available:,.2f}")
            pnl_el.markdown(f"**P&L:** {total_pnl:,.2f}")

            # strategy decide & execute
            candidates = trader.decide(prices)
            trader.execute(candidates)
            trader.maybe_close_some()

            # trades display
            if USE_SIMULATION:
                df = []
                for tid, p in sim.positions.items():
                    price = sim.price_map[p["sym"]]
                    df.append({"id": tid, "symbol": p["sym"], "dir": p["direction"], "open_price": p["open_price"], "current_price": price, "pnl": p["pnl"]})
                trades_el.dataframe(pd.DataFrame(df))
            else:
                okpos, posdata = client.get_open_positions()
                if okpos and isinstance(posdata, (dict, list)):
                    # adapt parse
                    trades_el.write(posdata)
                else:
                    trades_el.write("No open positions or could not fetch.")

            # logs
            log_el.text("\n".join(trader.log[-40:]))

        except Exception as e:
            st.error(f"Error in loop: {e}")
        time.sleep(TICK_INTERVAL)

if st.button("Start"):
    if "thread" not in st.session_state:
        st.session_state.thread = threading.Thread(target=loop, daemon=True)
        st.session_state.thread.start()
        st.success("Loop started.")
    else:
        st.info("Already running")

if st.button("Stop"):
    stop_event.set()
    st.session_state.pop("thread", None)
    st.warning("Stopped")

st.caption("Demo code — adapt order payloads & endpoints for your account. Use SIMULATION mode first.")

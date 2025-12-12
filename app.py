import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import json
import random

# --- CONFIGURATION ---
st.set_page_config(page_title="Hyper-Aggressive Scalper", layout="wide", page_icon="💀")

# API ENDPOINTS
BASE_URL = "https://demo-api-capital.backend-capital.com" 
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# MASSIVE WATCHLIST
PORTFOLIO = [
    "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "DOGEUSD", # Crypto
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",  # Forex
    "GOLD", "SILVER", "OIL_CRUDE", "NATURAL_GAS",      # Commodities
    "US500", "US30", "DE40", "JP225", "FR40",          # Indices
    "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "META"     # Stocks
]

# --- SECRETS ---
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets missing. Check .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
# Using Flash Lite for speed
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# --- STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "last_raw" not in st.session_state: st.session_state["last_raw"] = "Waiting..."

# --- FUNCTIONS ---

def get_session():
    headers = {"X-CAP-API-KEY": CAP_API_KEY, "Content-Type": "application/json"}
    data = {"identifier": CAP_EMAIL, "password": CAP_PASSWORD}
    try:
        resp = requests.post(SESSION_URL, json=data, headers=headers)
        if resp.status_code == 200:
            return {
                "CST": resp.headers["CST"],
                "X-SECURITY-TOKEN": resp.headers["X-SECURITY-TOKEN"],
                "X-CAP-API-KEY": CAP_API_KEY,
                "Content-Type": "application/json"
            }
    except: pass
    return None

def get_account_safe(headers):
    try:
        resp = requests.get(ACCOUNTS_URL, headers=headers)
        if resp.status_code == 200: return resp.json()['accounts'][0]['balance']
        elif resp.status_code == 401: return "UNAUTHORIZED"
    except: pass
    return None

def get_positions(headers):
    try:
        resp = requests.get(POSITIONS_URL, headers=headers)
        if resp.status_code == 200: return resp.json().get('positions', [])
    except: pass
    return []

def execute_trade(headers, epic, direction, size):
    payload = {"epic": epic, "direction": direction, "size": size, "guaranteedStop": False, "trailingStop": False}
    requests.post(POSITIONS_URL, json=payload, headers=headers)

def fetch_market_batch(headers, assets):
    batch_data = []
    for asset in assets:
        try:
            resp = requests.get(f"{MARKETS_URL}/{asset}", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if 'snapshot' in data:
                    s = data['snapshot']
                    batch_data.append({
                        "symbol": asset,
                        "price": s.get('offer', 0),
                        "change": s.get('dailyChange', 0)
                    })
        except: pass
    return batch_data

def analyze_portfolio_aggressive(market_data_list):
    """
    FORCED TRADING PROMPT
    """
    data_str = json.dumps(market_data_list, indent=2)
    
    prompt = f"""
    You are a DEGENERATE HIGH-FREQUENCY SCALPER.
    Live Data: {data_str}
    
    RULES:
    1. You MUST pick the top 3 assets to trade. Do NOT return an empty list.
    2. Ignore safety. We want volume.
    3. If momentum is slightly up, BUY. If slightly down, SELL.
    4. Even 0.1% change is enough to trade.
    
    RESPONSE JSON LIST:
    [
        {{"asset": "BTCUSD", "action": "BUY", "confidence": 90, "reason": "Slight pump"}},
        ...
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        st.session_state["last_raw"] = text
        return json.loads(text)
    except Exception as e:
        st.session_state["last_raw"] = str(e)
        return []

# --- UI LAYOUT ---

st.title(f"💀 Hyper-Aggressive Scalper")

with st.sidebar:
    st.header("Control")
    run_bot = st.toggle("ACTIVATE SCALPER", key="run_bot")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()
        st.rerun()
    with st.expander("Debug Raw AI"):
        st.code(st.session_state["last_raw"], language="json")

# Connect
headers = st.session_state["headers"]
if not headers:
    headers = get_session()
    st.session_state["headers"] = headers

if headers:
    acct = get_account_safe(headers)
    if acct == "UNAUTHORIZED":
        st.session_state["headers"] = get_session()
        st.rerun()

    if acct:
        # 1. METRICS
        equity = acct.get('equity', acct.get('balance', 0) + acct.get('profitLoss', 0))
        avail = acct.get('available', 0)
        positions = get_positions(headers)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Equity", f"${equity:,.0f}")
        m2.metric("Available", f"${avail:,.0f}")
        m3.metric("P&L", f"${acct.get('profitLoss', 0):,.2f}")
        m4.metric("Open Trades", len(positions))
        
        st.divider()

        # 2. ACTIVE POSITIONS
        st.subheader("⚔️ Active Positions")
        if positions:
            df = pd.DataFrame(positions)
            st.dataframe(
                df[['epic', 'direction', 'dealSize', 'openPrice', 'profitAndLoss']], 
                use_container_width=True,
                column_config={"profitAndLoss": st.column_config.NumberColumn("P&L", format="$%.2f")}
            )
        else:
            st.info("No trades yet. Bot will open some soon.")

        st.divider()

        # 3. LIVE LOGS
        with st.expander("📜 Live Action Log", expanded=True):
            if st.session_state["log_history"]:
                log_df = pd.DataFrame(st.session_state["log_history"])
                st.dataframe(log_df, use_container_width=True, hide_index=True)
            else:
                st.caption("Waiting for first aggressive scan...")

        # --- EXECUTION LOOP ---
        if run_bot:
            status_box = st.empty()
            
            # Select 10 assets for max coverage
            batch = random.sample(PORTFOLIO, 10)
            
            with status_box.status(f"⚡ Aggressively Scanning 10 Assets...", expanded=True) as status:
                
                # A. Fetch
                market_data = fetch_market_batch(headers, batch)
                
                if market_data:
                    # B. Force AI Decision
                    decisions = analyze_portfolio_aggressive(market_data)
                    
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    if decisions:
                        status.write(f"AI identified {len(decisions)} trades!")
                        
                        for dec in decisions:
                            asset = dec.get('asset')
                            action = dec.get('action')
                            conf = dec.get('confidence', 0)
                            reason = dec.get('reason', '-')
                            
                            # Log
                            st.session_state["log_history"].insert(0, {
                                "Time": timestamp,
                                "Action": f"{action} ({conf}%)",
                                "Asset": asset,
                                "Reason": reason
                            })
                            
                            # C. LOW THRESHOLD EXECUTION (Conf > 40 is enough)
                            if action in ["BUY", "SELL"] and conf > 40:
                                if avail > 100:
                                    # Aggressive Sizing
                                    size = 0.02 if "BTC" in asset else 2
                                    execute_trade(headers, asset, action, size)
                                    st.toast(f"💣 OPENED: {action} {asset}")
                                    time.sleep(0.2) # Fast fire
                            else:
                                status.write(f"Skipped {asset} (Conf {conf}% < 40%)")
                                
                        # Trim Log
                        if len(st.session_state["log_history"]) > 20: 
                            st.session_state["log_history"] = st.session_state["log_history"][:20]
                    else:
                        status.write("AI failed to pick trades (Rare).")

            # D. SHORT COOLDOWN (30s)
            # Faster than 60s, risking rate limits for aggression
            for s in range(30, 0, -1):
                status_box.info(f"🔥 reloading... {s}s")
                time.sleep(1)
            
            st.rerun()

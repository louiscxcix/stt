import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import json
import random

# --- CONFIGURATION ---
st.set_page_config(page_title="Portfolio AI Manager", layout="wide", page_icon="🏢")

# API ENDPOINTS
BASE_URL = "https://demo-api-capital.backend-capital.com" 
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# MASSIVE PORTFOLIO
PORTFOLIO = [
    "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD",      # Crypto
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",      # Forex
    "GOLD", "SILVER", "OIL_CRUDE",               # Commodities
    "US500", "US30", "DE40", "JP225",            # Indices
    "TSLA", "NVDA", "AAPL", "MSFT", "AMZN"       # Stocks
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
# Using Flash Lite for large context windows
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# --- STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "last_raw_response" not in st.session_state: st.session_state["last_raw_response"] = "Waiting for first scan..."

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
    """Fetches price data for MULTIPLE assets at once."""
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

def analyze_portfolio_batch(market_data_list):
    """
    SENDS ONE MASSIVE PROMPT TO GEMINI.
    """
    data_str = json.dumps(market_data_list, indent=2)
    
    prompt = f"""
    You are a Hedge Fund Manager.
    Here is live market data:
    {data_str}
    
    TASK:
    1. Scan for High Volatility opportunities.
    2. Select the Top 3 trades (if any).
    3. Be Aggressive.
    
    RESPONSE FORMAT (JSON LIST):
    [
        {{"asset": "BTCUSD", "action": "BUY", "confidence": 85, "reason": "Momentum breakout"}},
        ...
    ]
    If market is boring, return [] (empty list).
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        st.session_state["last_raw_response"] = text # Save for debug
        return json.loads(text)
    except Exception as e:
        st.session_state["last_raw_response"] = f"Error: {e}"
        return []

# --- UI LAYOUT ---

st.title(f"🏢 Portfolio AI Manager")

# Sidebar
with st.sidebar:
    st.header("Control")
    run_bot = st.toggle("ACTIVATE FUND MANAGER", key="run_bot")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()
        st.rerun()
        
    st.divider()
    with st.expander("🛠️ Debug: Raw AI Output"):
        st.caption("See exactly what Gemini replied in the last cycle:")
        st.code(st.session_state["last_raw_response"], language="json")

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
        m4.metric("Active Trades", len(positions))
        
        st.divider()

        # 2. POSITIONS (TOP PRIORITY)
        st.subheader("⚔️ Active Positions")
        if positions:
            df = pd.DataFrame(positions)
            st.dataframe(
                df[['epic', 'direction', 'dealSize', 'openPrice', 'profitAndLoss']], 
                use_container_width=True,
                column_config={"profitAndLoss": st.column_config.NumberColumn("P&L", format="$%.2f")}
            )
        else:
            st.info("No trades currently open.")

        st.divider()

        # 3. LIVE ACTIVITY LOG (Folded)
        with st.expander("📜 Live System Log (Click to View)", expanded=True):
            if st.session_state["log_history"]:
                log_df = pd.DataFrame(st.session_state["log_history"])
                st.dataframe(
                    log_df, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Action": st.column_config.TextColumn("Action"),
                        "Details": st.column_config.TextColumn("Details", width="large"),
                    }
                )
            else:
                st.caption("Log is empty. Waiting for start...")

        # --- EXECUTION LOOP ---
        if run_bot:
            status_box = st.empty()
            
            # Select 8 random assets for this batch
            batch = random.sample(PORTFOLIO, 8)
            batch_names = ", ".join(batch[:3]) + "..."
            
            with status_box.status(f"⚡ Scanning Batch: {batch_names}", expanded=True) as status:
                
                # A. Fetch Data
                status.write("Fetching market prices...")
                market_data = fetch_market_batch(headers, batch)
                
                if market_data:
                    status.write(f"Analyzing {len(market_data)} assets with Gemini 2.5...")
                    
                    # B. AI Analysis
                    decisions = analyze_portfolio_batch(market_data)
                    
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    # C. Log Results (Even if Empty)
                    if not decisions:
                        status.write("AI found no lucrative trades.")
                        st.session_state["log_history"].insert(0, {
                            "Time": timestamp,
                            "Action": "SCAN",
                            "Details": f"Scanned {len(batch)} assets. No opportunities found."
                        })
                    else:
                        status.write(f"AI found {len(decisions)} opportunities!")
                        
                        for dec in decisions:
                            asset = dec.get('asset')
                            action = dec.get('action')
                            conf = dec.get('confidence', 0)
                            reason = dec.get('reason', '-')
                            
                            # Log Trade
                            st.session_state["log_history"].insert(0, {
                                "Time": timestamp,
                                "Action": f"{action} ({conf}%)",
                                "Details": f"{asset}: {reason}"
                            })
                            
                            # Execute
                            if action in ["BUY", "SELL"] and conf > 70:
                                if avail > 100:
                                    size = 0.01 if "BTC" in asset else 1
                                    execute_trade(headers, asset, action, size)
                                    st.toast(f"✅ Executed: {action} {asset}")
                                    time.sleep(0.5)
                            else:
                                status.write(f"Skipped {asset} (Conf {conf}% is too low)")

                    # Trim Log
                    if len(st.session_state["log_history"]) > 20: 
                        st.session_state["log_history"] = st.session_state["log_history"][:20]

            # D. Cooldown (60s)
            for s in range(60, 0, -1):
                status_box.info(f"⏳ Next Scan in {s}s")
                time.sleep(1)
            
            st.rerun()

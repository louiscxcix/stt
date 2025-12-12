import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import json
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Portfolio AI Manager", layout="wide", page_icon="🏢")

# API ENDPOINTS
BASE_URL = "https://demo-api-capital.backend-capital.com" 
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# MASSIVE PORTFOLIO (Analyzed in batches)
PORTFOLIO = [
    "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD",      # Crypto
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",      # Forex
    "GOLD", "SILVER", "OIL_CRUDE", "NATURAL_GAS",# Commodities
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
# Flash Lite is perfect for large context windows (batching)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# --- STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None

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
    """
    Fetches price data for MULTIPLE assets at once to save time.
    """
    batch_data = []
    for asset in assets:
        try:
            # Capital.com is fast, we can loop this quickly without hitting Gemini limits
            resp = requests.get(f"{MARKETS_URL}/{asset}", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if 'snapshot' in data:
                    s = data['snapshot']
                    batch_data.append({
                        "symbol": asset,
                        "price": s.get('offer', 0),
                        "change": s.get('dailyChange', 0),
                        "high": s.get('high', 0),
                        "low": s.get('low', 0)
                    })
        except: pass
    return batch_data

def analyze_portfolio_batch(market_data_list):
    """
    SENDS ONE MASSIVE PROMPT TO GEMINI.
    "Here is the data for 10 assets. Pick the top 3."
    """
    
    # Convert list of dicts to a string table for the AI
    data_str = json.dumps(market_data_list, indent=2)
    
    prompt = f"""
    You are a Senior Portfolio Manager.
    Here is the live market data for our watchlist:
    
    {data_str}
    
    TASK:
    1. Scan all assets.
    2. Identify ONLY the "Lucrative" opportunities (Strong Buy or Strong Sell).
    3. Ignore anything with weak momentum or low volatility.
    4. Select a maximum of 3 trades.
    
    RESPONSE FORMAT (JSON LIST):
    [
        {{
            "asset": "BTCUSD",
            "action": "BUY",
            "confidence": 85,
            "reason": "Breakout above resistance with 2% volume spike"
        }},
        ...
    ]
    If no good trades, return an empty list [].
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return []

# --- UI LAYOUT ---

st.title(f"🏢 Portfolio AI Manager")

with st.sidebar:
    st.header("Control")
    run_bot = st.toggle("ACTIVATE FUND MANAGER", key="run_bot")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()
        st.rerun()

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

        # 2. POSITIONS (Top Priority)
        st.subheader("⚔️ Active Positions")
        if positions:
            df = pd.DataFrame(positions)
            st.dataframe(
                df[['epic', 'direction', 'dealSize', 'openPrice', 'profitAndLoss']], 
                use_container_width=True,
                column_config={"profitAndLoss": st.column_config.NumberColumn("P&L", format="$%.2f")}
            )
        else:
            st.info("No trades open. Portfolio scanner active.")

        st.divider()

        # 3. LIVE DECISION LOG (Table View)
        st.subheader("📜 Portfolio Decisions")
        if st.session_state["log_history"]:
            log_df = pd.DataFrame(st.session_state["log_history"])
            
            # Use Streamlit's new column config for progress bars
            st.dataframe(
                log_df, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "Conf": st.column_config.ProgressColumn(
                        "AI Confidence",
                        format="%d%%",
                        min_value=0,
                        max_value=100
                    ),
                    "Action": st.column_config.TextColumn("Action"),
                    "Asset": st.column_config.TextColumn("Asset"),
                }
            )
        else:
            st.caption("Waiting for first batch analysis...")

        # --- EXECUTION LOOP ---
        if run_bot:
            status_box = st.empty()
            
            # BATCH LOGIC: Scan 8 assets at a time (Safe for 1 prompt)
            import random
            batch = random.sample(PORTFOLIO, 8) 
            
            with status_box.status(f"⚡ Analyzing Portfolio Batch ({len(batch)} assets)...", expanded=True) as status:
                
                # 1. Fetch ALL Data (Fast)
                status.write("Fetching market data...")
                market_data = fetch_market_batch(headers, batch)
                
                if market_data:
                    status.write(f"Data received for {len(market_data)} assets. Sending to AI...")
                    
                    # 2. Send ONE Prompt to AI
                    decisions = analyze_portfolio_batch(market_data)
                    
                    if decisions:
                        status.write(f"AI found {len(decisions)} opportunities!")
                        
                        for dec in decisions:
                            asset = dec.get('asset')
                            action = dec.get('action')
                            conf = dec.get('confidence', 0)
                            reason = dec.get('reason', '-')
                            
                            # Add to Log
                            new_log = {
                                "Time": datetime.now().strftime("%H:%M:%S"),
                                "Asset": asset,
                                "Action": action,
                                "Conf": conf, # Int for progress bar
                                "Reason": reason
                            }
                            st.session_state["log_history"].insert(0, new_log)
                            if len(st.session_state["log_history"]) > 20: st.session_state["log_history"].pop()
                            
                            # 3. Execute Lucrative Only
                            if action in ["BUY", "SELL"] and conf > 70:
                                if avail > 100:
                                    size = 0.01 if "BTC" in asset or "ETH" in asset else 1
                                    execute_trade(headers, asset, action, size)
                                    st.toast(f"✅ Executed: {action} {asset}")
                                    time.sleep(0.5)
                            else:
                                status.write(f"Skipping {asset}: {action} (Conf {conf}%) - Not lucrative enough.")
                    else:
                        status.write("AI decided NO TRADES for this batch.")
                
            # COOLDOWN (60s cycle)
            # Since we did 1 big call, we just wait 60s.
            for s in range(60, 0, -1):
                status_box.info(f"⏳ Next Portfolio Scan in {s}s")
                time.sleep(1)
            
            st.rerun()

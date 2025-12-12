import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import json
import random
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Capital.com AI Trader", layout="wide", page_icon="📈")

# API ENDPOINTS
BASE_URL = "https://demo-api-capital.backend-capital.com" 
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# PORTFOLIO WATCHLIST
PORTFOLIO = [
    "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD",      # Crypto
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",      # Forex
    "GOLD", "SILVER", "OIL_CRUDE", "NATURAL_GAS",# Commodities
    "US500", "US30", "DE40", "JP225",            # Indices
    "TSLA", "NVDA", "AAPL", "MSFT", "AMZN"       # Stocks
]

# --- SECRETS SETUP ---
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets missing. Please check .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# --- SESSION STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "connection_status" not in st.session_state: st.session_state["connection_status"] = "Disconnected"

# --- HELPER FUNCTIONS ---

def clean_json_response(text):
    """Cleans AI output to ensure valid JSON"""
    try:
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```", "", text)
        return json.loads(text.strip())
    except:
        return []

def get_session():
    """Connects to Capital.com"""
    headers = {"X-CAP-API-KEY": CAP_API_KEY, "Content-Type": "application/json"}
    data = {"identifier": CAP_EMAIL, "password": CAP_PASSWORD}
    try:
        resp = requests.post(SESSION_URL, json=data, headers=headers)
        if resp.status_code == 200:
            st.session_state["connection_status"] = "Connected ✅"
            return {
                "CST": resp.headers["CST"],
                "X-SECURITY-TOKEN": resp.headers["X-SECURITY-TOKEN"],
                "X-CAP-API-KEY": CAP_API_KEY,
                "Content-Type": "application/json"
            }
    except Exception as e:
        st.session_state["connection_status"] = f"Error: {str(e)}"
    return None

def get_account_data(headers):
    """Fetches Account Info (Equity, Funds)"""
    try:
        resp = requests.get(ACCOUNTS_URL, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if 'accounts' in data:
                return data['accounts'][0]['balance']
        elif resp.status_code == 401:
            return "UNAUTHORIZED"
    except: pass
    return None

def get_open_positions(headers):
    """Fetches Open Trades"""
    try:
        resp = requests.get(POSITIONS_URL, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('positions', [])
    except: pass
    return []

def execute_order(headers, epic, direction, size):
    """Executes a Trade on Capital.com"""
    payload = {
        "epic": epic,
        "direction": direction,
        "size": size,
        "guaranteedStop": False,
        "trailingStop": False
    }
    return requests.post(POSITIONS_URL, json=payload, headers=headers)

def fetch_market_prices(headers, assets):
    """Fetches Live Prices for a list of assets"""
    data_list = []
    for asset in assets:
        try:
            r = requests.get(f"{MARKETS_URL}/{asset}", headers=headers)
            if r.status_code == 200:
                d = r.json()
                if 'snapshot' in d:
                    data_list.append({
                        "symbol": asset,
                        "price": d['snapshot']['offer'],
                        "change": d['snapshot']['dailyChange']
                    })
        except: pass
    return data_list

# --- AI FUNCTIONS ---

def ai_design_portfolio(invest_amount, market_data):
    """
    Step 1: AI decides WHAT to buy and HOW MUCH.
    """
    data_str = json.dumps(market_data, indent=2)
    prompt = f"""
    You are a Portfolio Manager. I have ${invest_amount} USD.
    Live Market Data: {data_str}
    
    TASK:
    1. Select the Top 3-5 assets with best momentum.
    2. Allocate the ${invest_amount} across them.
    3. Return valid JSON.
    
    RESPONSE FORMAT:
    [
        {{"asset": "BTCUSD", "direction": "BUY", "usd_amount": 300, "reason": "Bullish trend"}},
        {{"asset": "GOLD", "direction": "SELL", "usd_amount": 200, "reason": "Bearish trend"}}
    ]
    """
    try:
        resp = model.generate_content(prompt)
        return clean_json_response(resp.text)
    except: return []

def ai_scalper_decision(market_data):
    """
    Auto-Trading logic for background loop.
    """
    data_str = json.dumps(market_data, indent=2)
    prompt = f"""
    Role: Aggressive Scalper.
    Data: {data_str}
    Task: Pick 3 trades. Ignore safety. If trend exists, trade it.
    Return JSON: [{{"asset": "BTCUSD", "action": "BUY", "confidence": 90, "reason": "Pump"}}, ...]
    """
    try:
        resp = model.generate_content(prompt)
        return clean_json_response(resp.text)
    except: return []

# --- MAIN UI ---

st.title("🤖 Capital.com AI Trader")

# 1. AUTHENTICATION & CONNECTION
# ---------------------------------------------------------
if "headers" not in st.session_state or not st.session_state["headers"]:
    st.session_state["headers"] = get_session()

headers = st.session_state["headers"]
account_data = None
positions_data = []

# If connected, fetch data
if headers:
    account_data = get_account_data(headers)
    
    # Auto-Reconnect if token expired
    if account_data == "UNAUTHORIZED":
        st.toast("⚠️ Session expired. Reconnecting...", icon="🔄")
        st.session_state["headers"] = get_session()
        headers = st.session_state["headers"]
        account_data = get_account_data(headers)

    if account_data:
        positions_data = get_open_positions(headers)

# 2. DASHBOARD DISPLAY
# ---------------------------------------------------------
if account_data:
    st.markdown(f"**Status:** {st.session_state['connection_status']}")
    
    # Metrics
    equity = account_data.get('equity', 0)
    avail = account_data.get('available', 0)
    pnl = account_data.get('profitLoss', 0)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Equity", f"${equity:,.2f}")
    col2.metric("Available Funds", f"${avail:,.2f}")
    col3.metric("Total P&L", f"${pnl:,.2f}", delta=pnl)
    col4.metric("Open Trades", len(positions_data))
    
    st.divider()
    
    # 3. OPEN POSITIONS TABLE (Fail-Safe)
    st.subheader("⚔️ Active Positions")
    if positions_data:
        # Build safe list to prevent KeyError
        clean_pos = []
        for p in positions_data:
            clean_pos.append({
                "Asset": p.get('epic', 'Unknown'),
                "Direction": p.get('direction', '-'),
                "Size": p.get('dealSize', 0),
                "Entry": p.get('openPrice', 0),
                "P&L": p.get('profitAndLoss', 0)
            })
        st.dataframe(pd.DataFrame(clean_pos), use_container_width=True)
    else:
        st.info("No active trades found.")

else:
    st.warning("⚠️ Not Connected to Capital.com. Check logs or credentials.")

# 4. SIDEBAR CONTROLS
# ---------------------------------------------------------
with st.sidebar:
    st.header("🎮 Portfolio Builder")
    st.caption("Step 1: AI Plans. Step 2: API Executes.")
    
    with st.form("portfolio_form"):
        amount = st.number_input("Invest Amount ($)", 100, 10000, 1000)
        build_btn = st.form_submit_button("🚀 Build & Execute")
        
        if build_btn and headers:
            st.info("1. Scanning Market Prices...")
            # Fetch Batch Data for Context
            batch = random.sample(PORTFOLIO, 10)
            mkt_data = fetch_market_prices(headers, batch)
            
            if mkt_data:
                st.info("2. Asking AI to Design Portfolio...")
                plan = ai_design_portfolio(amount, mkt_data)
                
                if plan:
                    st.success(f"AI Designed Plan with {len(plan)} trades!")
                    st.write(plan) # Show plan to user
                    
                    st.info("3. Executing Orders via Capital.com API...")
                    for item in plan:
                        asset = item.get('asset')
                        direction = item.get('direction')
                        
                        # Simple Sizing Logic (Safe for Demo)
                        size = 0.01 if "BTC" in asset or "ETH" in asset else 1.0
                        
                        res = execute_order(headers, asset, direction, size)
                        
                        if res.status_code == 200:
                            st.toast(f"✅ Executed: {direction} {asset}")
                        else:
                            st.error(f"❌ Failed {asset}: {res.text}")
                        time.sleep(0.5)
                    
                    st.success("Portfolio Execution Complete!")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error("AI returned an empty plan.")
            else:
                st.error("Failed to fetch market data.")

    st.divider()
    
    st.header("🤖 Auto-Scalper")
    run_bot = st.toggle("Activate Background Bot", key="bot_active")
    
    if st.button("Force Reconnect"):
        st.session_state["headers"] = get_session()
        st.rerun()

# 5. BACKGROUND AUTO-TRADING LOOP
# ---------------------------------------------------------
if run_bot and headers:
    status_box = st.empty()
    
    # Scan a batch of assets
    batch = random.sample(PORTFOLIO, 8)
    
    with status_box.status(f"⚡ Bot Scanning {len(batch)} Assets...", expanded=True) as status:
        mkt_data = fetch_market_prices(headers, batch)
        
        if mkt_data:
            decisions = ai_scalper_decision(mkt_data)
            
            if decisions:
                status.write(f"AI found {len(decisions)} opportunities.")
                for dec in decisions:
                    asset = dec.get('asset')
                    action = dec.get('action')
                    conf = dec.get('confidence', 0)
                    
                    if action in ["BUY", "SELL"] and conf > 50:
                        # Execution
                        size = 0.02 if "BTC" in asset else 1.0
                        execute_order(headers, asset, action, size)
                        
                        # Logging
                        msg = f"{action} {asset} (Conf: {conf}%)"
                        st.toast(f"💣 {msg}")
                        st.session_state["log_history"].insert(0, {
                            "Time": datetime.now().strftime("%H:%M:%S"),
                            "Log": msg
                        })
                        time.sleep(0.2)
            else:
                status.write("No trades found this cycle.")
    
    # Display Logs
    if st.session_state["log_history"]:
        with st.expander("📜 Activity Log", expanded=True):
            st.dataframe(pd.DataFrame(st.session_state["log_history"]), use_container_width=True)

    # Cooldown
    time.sleep(10)
    st.rerun()

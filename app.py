import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import json
import random

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Portfolio Architect", layout="wide", page_icon="🏗️")

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
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# --- STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "last_allocation" not in st.session_state: st.session_state["last_allocation"] = None

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
    return requests.post(POSITIONS_URL, json=payload, headers=headers)

def close_position(headers, deal_id):
    return requests.delete(f"{POSITIONS_URL}/{deal_id}", headers=headers)

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

# --- AI BRAINS ---

def ai_smart_allocate(total_funds, market_data):
    """
    Takes a $ amount and market data.
    Returns a portfolio allocation plan.
    """
    data_str = json.dumps(market_data, indent=2)
    prompt = f"""
    You are a Portfolio Manager.
    I have ${total_funds} to invest right now.
    Live Market Data: {data_str}
    
    TASK:
    1. Select the BEST 3-5 assets based on momentum/volatility.
    2. Allocate the ${total_funds} across them.
    3. Calculate the trade size for each (Assume leverage 1:1 for simplicity, Volume = Funds / Price).
    4. Be aggressive but diversified.
    
    RESPONSE JSON LIST:
    [
        {{"asset": "BTCUSD", "direction": "BUY", "usd_amount": 300, "reason": "Breakout"}},
        {{"asset": "TSLA", "direction": "SELL", "usd_amount": 200, "reason": "Overbought"}}
    ]
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        st.session_state["last_allocation"] = text
        return json.loads(text)
    except: return []

def analyze_portfolio_aggressive(market_data_list):
    """Brain 2: Auto-Scalper"""
    data_str = json.dumps(market_data_list, indent=2)
    prompt = f"""
    Role: Degenerate Scalper.
    Data: {data_str}
    Task: Pick top 3 assets. Return JSON: [{{"asset": "BTCUSD", "action": "BUY", "confidence": 90, "reason": "Pump"}}, ...]
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except: return []

def manage_positions_ai(positions_data):
    """Brain 3: Risk Manager"""
    if not positions_data: return []
    # Simplified data for AI
    summary = [{"id": p.get('dealId'), "asset": p.get('epic'), "pnl": p.get('profitAndLoss')} for p in positions_data]
    data_str = json.dumps(summary, indent=2)
    
    prompt = f"""
    Risk Manager. Open Positions: {data_str}.
    Task: CLOSE if PnL > 5 (Take Profit) or PnL < -15 (Stop Loss). HOLD otherwise.
    Return JSON: [{{"id": "123", "action": "CLOSE", "reason": "TP"}}, ...]
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except: return []

# --- UI LAYOUT ---

st.title(f"🏗️ AI Portfolio Architect")

# Connect
headers = st.session_state["headers"]
if not headers:
    headers = get_session()
    st.session_state["headers"] = headers

# --- SIDEBAR: SMART ALLOCATOR ---
with st.sidebar:
    st.header("🧠 Smart Allocate")
    st.caption("Let AI decide how to invest your money.")
    
    with st.form("smart_alloc_form"):
        invest_amount = st.number_input("Amount to Invest ($)", min_value=100, value=1000, step=100)
        alloc_btn = st.form_submit_button("🚀 Build & Buy Portfolio")
        
        if alloc_btn and headers:
            st.info("Scanning markets...")
            # 1. Fetch Batch
            batch = random.sample(PORTFOLIO, 10)
            mkt_data = fetch_market_batch(headers, batch)
            
            if mkt_data:
                # 2. Ask AI
                plan = ai_smart_allocate(invest_amount, mkt_data)
                
                if plan:
                    st.success(f"AI Selected {len(plan)} Assets!")
                    for item in plan:
                        asset = item.get('asset')
                        direction = item.get('direction')
                        usd = item.get('usd_amount')
                        reason = item.get('reason')
                        
                        # Crude size calc (Price is needed for exact size, approximating for Demo)
                        # In real app, fetch current price again to divide usd/price
                        size = 0.02 if "BTC" in asset else 1.0 
                        if "Stocks" in asset: size = 1
                        
                        res = execute_trade(headers, asset, direction, size)
                        if res.status_code == 200:
                            st.toast(f"✅ Bought ${usd} of {asset}")
                        else:
                            st.error(f"Failed {asset}")
                        time.sleep(0.2)
                    st.rerun()
                else:
                    st.error("AI couldn't build a plan.")

    st.divider()
    
    st.header("🤖 Auto-Scalper")
    run_bot = st.toggle("ACTIVATE SCALPER", key="run_bot")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()
        st.rerun()

if headers:
    acct = get_account_safe(headers)
    if acct == "UNAUTHORIZED":
        st.session_state["headers"] = get_session()
        st.rerun()

    if acct:
        # 1. METRICS
        equity = acct.get('equity', 0)
        avail = acct.get('available', 0)
        positions = get_positions(headers)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Equity", f"${equity:,.0f}")
        m2.metric("Available", f"${avail:,.0f}")
        m3.metric("P&L", f"${acct.get('profitLoss', 0):,.2f}")
        m4.metric("Open Trades", len(positions))
        
        st.divider()

        # 2. ACTIVE POSITIONS (FIXED CRASH)
        st.subheader("⚔️ Active Positions")
        if positions:
            df = pd.DataFrame(positions)
            
            # --- KEY ERROR FIX ---
            # We map the raw API keys to nice names. 
            # If a key is missing, we fill it with 0 or "-".
            safe_df = pd.DataFrame()
            safe_df['Symbol'] = df.get('epic', '-')
            safe_df['Direction'] = df.get('direction', '-')
            safe_df['Size'] = df.get('size', df.get('dealSize', 0)) # Try both keys
            safe_df['Entry'] = df.get('openPrice', df.get('level', 0))
            safe_df['P&L'] = df.get('profitAndLoss', df.get('upl', 0))
            
            st.dataframe(
                safe_df, 
                use_container_width=True,
                column_config={"P&L": st.column_config.NumberColumn("P&L", format="$%.2f")}
            )
        else:
            st.info("No trades currently open.")

        # 3. LIVE LOGS
        with st.expander("📜 Live Action Log", expanded=True):
            if st.session_state["log_history"]:
                st.dataframe(pd.DataFrame(st.session_state["log_history"]), use_container_width=True, hide_index=True)
            else:
                st.caption("Log empty...")

        # --- MAIN LOOP ---
        if run_bot:
            status_box = st.empty()
            
            # A. Manage Existing
            if positions:
                with status_box.status("🛡️ Managing Risk...", expanded=True) as status:
                    decisions = manage_positions_ai(positions)
                    for dec in decisions:
                        if dec.get('action') == "CLOSE":
                            deal_id = dec.get('id')
                            close_position(headers, deal_id)
                            st.toast(f"💰 Closed {deal_id}")
                            st.session_state["log_history"].insert(0, {"Time": datetime.now().strftime("%H:%M:%S"), "Action": "CLOSE", "Reason": dec.get('reason')})
                    status.write("Risk check done.")

            # B. Hunt New
            batch = random.sample(PORTFOLIO, 10)
            with status_box.status(f"⚡ Scalping 10 Assets...", expanded=True) as status:
                market_data = fetch_market_batch(headers, batch)
                if market_data:
                    decisions = analyze_portfolio_aggressive(market_data)
                    if decisions:
                        status.write(f"AI found {len(decisions)} trades!")
                        for dec in decisions:
                            asset = dec.get('asset')
                            action = dec.get('action')
                            conf = dec.get('confidence', 0)
                            
                            if action in ["BUY", "SELL"] and conf > 40:
                                if avail > 100:
                                    size = 0.02 if "BTC" in asset else 1.0
                                    execute_trade(headers, asset, action, size)
                                    st.toast(f"💣 {action} {asset}")
                                    st.session_state["log_history"].insert(0, {
                                        "Time": datetime.now().strftime("%H:%M:%S"),
                                        "Action": action,
                                        "Asset": asset,
                                        "Reason": dec.get('reason')
                                    })
                                    time.sleep(0.2)
                    
                    if len(st.session_state["log_history"]) > 20: 
                        st.session_state["log_history"] = st.session_state["log_history"][:20]

            # C. Cooldown
            for s in range(30, 0, -1):
                status_box.info(f"🔥 reloading... {s}s")
                time.sleep(1)
            
            st.rerun()

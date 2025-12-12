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
    return requests.post(POSITIONS_URL, json=payload, headers=headers)

def close_position(headers, deal_id):
    """Closes a specific trade"""
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

def analyze_portfolio_aggressive(market_data_list):
    """Brain 1: Finds NEW trades"""
    data_str = json.dumps(market_data_list, indent=2)
    prompt = f"""
    You are a DEGENERATE SCALPER.
    Live Data: {data_str}
    RULES: Pick Top 3 assets. Ignore safety. If momentum exists, trade it.
    RESPONSE JSON LIST: [{{"asset": "BTCUSD", "action": "BUY", "confidence": 90, "reason": "Pump"}}, ...]
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        st.session_state["last_raw"] = text
        return json.loads(text)
    except: return []

def manage_positions_ai(positions_data):
    """Brain 2: Decides to HOLD or CLOSE existing trades"""
    if not positions_data: return []
    
    # Create simple summary for AI
    summary = []
    for p in positions_data:
        summary.append({
            "dealId": p['dealId'],
            "asset": p['epic'],
            "direction": p['direction'],
            "pnl": p['profitAndLoss'],
            "entry": p['openPrice']
        })
        
    data_str = json.dumps(summary, indent=2)
    prompt = f"""
    You are a RISK MANAGER.
    Here are my open positions:
    {data_str}
    
    TASK: Decide to CLOSE or HOLD.
    RULES:
    1. If profit is good (> $2), CLOSE to take profit.
    2. If loss is getting bad (< -$10), CLOSE to stop loss.
    3. If mostly flat, HOLD.
    
    RESPONSE JSON LIST:
    [{{"dealId": "123", "action": "CLOSE", "reason": "Taking profit"}}, {{"dealId": "456", "action": "HOLD", "reason": "Waiting"}}]
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except: return []

# --- UI LAYOUT ---

st.title(f"💀 Hyper-Aggressive Scalper")

# Connect
headers = st.session_state["headers"]
if not headers:
    headers = get_session()
    st.session_state["headers"] = headers

# --- SIDEBAR: MANUAL TRADE ---
with st.sidebar:
    st.header("🎮 Manual Control")
    
    with st.form("manual_trade_form"):
        m_asset = st.selectbox("Asset", PORTFOLIO)
        m_action = st.radio("Direction", ["BUY", "SELL"], horizontal=True)
        m_size = st.number_input("Size", min_value=0.01, value=1.0, step=0.1)
        
        submitted = st.form_submit_button("🔥 FORCE OPEN TRADE")
        if submitted and headers:
            res = execute_trade(headers, m_asset, m_action, m_size)
            if res.status_code == 200:
                st.success(f"Opened {m_action} {m_asset}")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"Failed: {res.text}")

    st.divider()
    
    st.header("🤖 Auto-Bot")
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
            st.info("No trades yet.")

        # 3. LIVE LOGS
        with st.expander("📜 Live Action Log", expanded=True):
            if st.session_state["log_history"]:
                st.dataframe(pd.DataFrame(st.session_state["log_history"]), use_container_width=True, hide_index=True)
            else:
                st.caption("Log empty...")

        # --- MAIN LOOP ---
        if run_bot:
            status_box = st.empty()
            
            # --- PART A: MANAGE EXISTING TRADES ---
            if positions:
                with status_box.status("🛡️ AI Checking Existing Positions...", expanded=True) as status:
                    decisions = manage_positions_ai(positions)
                    for dec in decisions:
                        if dec.get('action') == "CLOSE":
                            deal_id = dec.get('dealId')
                            close_position(headers, deal_id)
                            st.toast(f"💰 CLOSED POSITION: {dec.get('reason')}")
                            st.session_state["log_history"].insert(0, {
                                "Time": datetime.now().strftime("%H:%M:%S"),
                                "Action": "CLOSE",
                                "Asset": "Existing",
                                "Reason": dec.get('reason')
                            })
                    status.write("Position check complete.")

            # --- PART B: HUNT NEW TRADES ---
            batch = random.sample(PORTFOLIO, 10)
            with status_box.status(f"⚡ Hunting New Trades...", expanded=True) as status:
                market_data = fetch_market_batch(headers, batch)
                if market_data:
                    decisions = analyze_portfolio_aggressive(market_data)
                    if decisions:
                        status.write(f"AI found {len(decisions)} opportunities!")
                        for dec in decisions:
                            asset = dec.get('asset')
                            action = dec.get('action')
                            conf = dec.get('confidence', 0)
                            
                            if action in ["BUY", "SELL"] and conf > 40:
                                if avail > 100:
                                    size = 0.02 if "BTC" in asset else 1.0
                                    execute_trade(headers, asset, action, size)
                                    st.toast(f"💣 OPENED: {action} {asset}")
                                    st.session_state["log_history"].insert(0, {
                                        "Time": datetime.now().strftime("%H:%M:%S"),
                                        "Action": action,
                                        "Asset": asset,
                                        "Reason": dec.get('reason')
                                    })
                                    time.sleep(0.2)
                    
                    if len(st.session_state["log_history"]) > 20: 
                        st.session_state["log_history"] = st.session_state["log_history"][:20]

            # D. COOLDOWN (30s)
            for s in range(30, 0, -1):
                status_box.info(f"🔥 reloading... {s}s")
                time.sleep(1)
            
            st.rerun()

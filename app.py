import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz

# --- CONFIGURATION ---
st.set_page_config(page_title="Ultra-Aggressive Trader", layout="wide", page_icon="🚀")

# ⚠️ LIVE TRADING URL (Switch carefully)
# BASE_URL = "https://api-capital.backend-capital.com"
BASE_URL = "https://demo-api-capital.backend-capital.com" 

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# Scans ALL of these every cycle
WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "US500", "TSLA"]

try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets missing.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

# --- NETWORK FUNCTIONS ---

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

def get_account(headers):
    try:
        resp = requests.get(ACCOUNTS_URL, headers=headers)
        if resp.status_code == 200:
            return resp.json()['accounts'][0]['balance']
        elif resp.status_code == 401:
            return "UNAUTHORIZED"
    except: pass
    return None

def get_positions(headers):
    try:
        resp = requests.get(POSITIONS_URL, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('positions', [])
    except: pass
    return []

def close_all_positions(headers, positions):
    st.toast("🔥 Closing ALL Trades (Midnight Protocol)")
    for p in positions:
        requests.delete(f"{POSITIONS_URL}/{p['dealId']}", headers=headers)

def execute_trade(headers, epic, direction, size):
    payload = {
        "epic": epic, "direction": direction, "size": size,
        "guaranteedStop": False, "trailingStop": False
    }
    # Fire and forget (don't wait for detailed response to speed up)
    requests.post(POSITIONS_URL, json=payload, headers=headers)

def ai_aggressive_decision(epic, price, change):
    # FORCE AI TO CHOOSE - Penalize 'WAIT'
    prompt = f"""
    You are a high-frequency scalper.
    Asset: {epic} | Price: {price} | Change: {change}%
    
    INSTRUCTIONS:
    1. You MUST pick BUY or SELL unless the market is dead flat.
    2. Be aggressive. Volatility is opportunity.
    3. Ignore safety. Focus on short-term direction.
    
    Output JSON ONLY: {{"action": "BUY" or "SELL", "confidence": 60-100}}
    """
    try:
        resp = model.generate_content(prompt)
        text = resp.text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except:
        # Default to a random aggressive move if AI fails (Fallback)
        return {"action": "BUY", "confidence": 50} 

# --- UI & LOGIC ---

st.title("🚀 Ultra-Aggressive Bot")

# Sidebar
with st.sidebar:
    is_running = st.toggle("ACTIVATE KILL SWITCH", value=False, key="run_state")
    st.write("Status:", "🟢 ACTIVE" if is_running else "🔴 STOPPED")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()

# Containers
metrics_area = st.container()
st.divider()
log_area = st.container()
st.divider()
trades_area = st.container()

# State
if "headers" not in st.session_state:
    st.session_state["headers"] = get_session()

# --- MAIN LOOP ---
headers = st.session_state["headers"]

if not headers:
    headers = get_session()
    st.session_state["headers"] = headers

if headers:
    acct = get_account(headers)
    
    if acct == "UNAUTHORIZED":
        st.session_state["headers"] = get_session()
        st.rerun()
        
    if acct:
        # 1. Update Metrics
        equity = acct.get('equity', 0.0)
        available = acct.get('available', 0.0)
        positions = get_positions(headers)
        
        with metrics_area:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"${equity:,.0f}")
            c2.metric("Available", f"${available:,.0f}")
            c3.metric("P&L", f"${acct.get('profitLoss', 0):,.2f}")
            c4.metric("Open Trades", len(positions))

        with trades_area:
            if positions:
                df = pd.DataFrame(positions)
                st.dataframe(df[['epic', 'direction', 'profitAndLoss', 'dealSize']], use_container_width=True)
            else:
                st.info("No positions. Hunting...")

        # 2. AGGRESSIVE LOGIC
        if is_running:
            now = datetime.now(pytz.utc)
            
            # Midnight Close
            if now.hour == 23 and now.minute >= 59:
                if positions: close_all_positions(headers, positions)
            
            else:
                # LOOP ALL ASSETS (No random choice anymore)
                for asset in WATCHLIST:
                    
                    # Check funds (Stop if > 80% used)
                    if (equity - available) / equity > 0.80:
                        st.warning("Max Margin Reached. Pausing entries.")
                        break

                    try:
                        # Get Price
                        mkt = requests.get(f"{MARKETS_URL}/{asset}", headers=headers).json()
                        if 'snapshot' in mkt:
                            price = mkt['snapshot']['offer']
                            change = mkt['snapshot']['dailyChange']
                            
                            # AI Decision
                            dec = ai_aggressive_decision(asset, price, change)
                            action = dec.get('action')
                            conf = dec.get('confidence', 0)
                            
                            # LOG IT
                            with log_area:
                                st.write(f"⚔️ **{asset}**: AI says **{action}** ({conf}%)")
                            
                            # EXECUTE (Threshold lowered to 60%)
                            if action in ["BUY", "SELL"] and conf >= 60:
                                # AGGRESSIVE SIZING
                                size = 0.02 if "BTC" in asset else 1  # Doubled size
                                execute_trade(headers, asset, action, size)
                                st.toast(f"💣 OPENED {action} on {asset}!")
                                time.sleep(0.5) # Slight delay to avoid API ban
                                
                    except Exception as e:
                        print(e)
            
            # Fast cycle
            time.sleep(1)
            st.rerun()

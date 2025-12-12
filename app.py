import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz

# --- CONFIGURATION ---
st.set_page_config(page_title="Aggressive AI Trader", layout="wide", page_icon="⚡")

# ⚠️ CHANGE TO 'https://api-capital.backend-capital.com' FOR LIVE
BASE_URL = "https://demo-api-capital.backend-capital.com" 

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "OIL_CRUDE", "US500", "AAPL"]

# --- SECRETS SETUP ---
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets file missing. Please set up .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

# --- ROBUST FUNCTIONS ---

def get_session():
    """Authenticates and returns headers. Returns None if fails."""
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
        else:
            print(f"Auth Failed: {resp.text}")
    except Exception as e:
        print(f"Connection Error: {e}")
    return None

def get_account(headers):
    """Fetches account data safely. Handles errors."""
    try:
        resp = requests.get(ACCOUNTS_URL, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            # Safety check for dictionary structure
            if 'accounts' in data and len(data['accounts']) > 0:
                return data['accounts'][0]['balance']
        elif resp.status_code == 401:
            return "UNAUTHORIZED" # Signal to re-login
    except Exception as e:
        print(f"Account Fetch Error: {e}")
    return None

def get_positions(headers):
    try:
        resp = requests.get(POSITIONS_URL, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('positions', [])
    except:
        pass
    return []

def close_all_positions(headers, positions):
    st.warning("⏰ MIDNIGHT: Closing ALL positions.")
    for p in positions:
        requests.delete(f"{POSITIONS_URL}/{p['dealId']}", headers=headers)
        time.sleep(0.2)

def execute_trade(headers, epic, direction, size):
    payload = {
        "epic": epic, "direction": direction, "size": size,
        "guaranteedStop": False, "trailingStop": False
    }
    requests.post(POSITIONS_URL, json=payload, headers=headers)

def ai_decision(epic, price, change, equity, available):
    prompt = f"""
    Act as a high-frequency trading bot.
    Context: {epic} | Price: {price} | Change: {change}% | Equity: {equity} | Funds: {available}
    Task: AGGRESSIVE profit maximization.
    Output JSON ONLY: {{"action": "BUY"/"SELL"/"WAIT", "confidence": 0-100}}
    """
    try:
        resp = model.generate_content(prompt)
        text = resp.text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except:
        return {"action": "WAIT", "confidence": 0}

# --- MAIN APP ---

st.title("⚡ Aggressive Bot (Stable)")

# UI Layout
col_ctrl, col_status = st.columns([1, 3])
with col_ctrl:
    run_bot = st.toggle("RUN BOT", value=False)
    
dash_place = st.empty()
log_place = st.empty()

# Session State Init
if "headers" not in st.session_state:
    st.session_state["headers"] = get_session()

# --- BOT LOOP ---
if run_bot:
    while True:
        # 1. Check Connection
        if not st.session_state["headers"]:
            st.session_state["headers"] = get_session()
            if not st.session_state["headers"]:
                st.error("Cannot Connect. Retrying in 5s...")
                time.sleep(5)
                continue

        # 2. Fetch Data (Robust)
        headers = st.session_state["headers"]
        acct = get_account(headers)
        
        # 3. Handle Auth/API Errors
        if acct == "UNAUTHORIZED":
            st.warning("Session Expired. Re-authenticating...")
            st.session_state["headers"] = get_session()
            continue
        elif acct is None:
            # Skip this loop iteration if data failed to load
            time.sleep(2)
            continue 

        # 4. Safe Data Access (Fixes KeyError)
        equity = acct.get('equity', 0.0)
        available = acct.get('available', 0.0)
        pnl = acct.get('profitLoss', 0.0)
        
        positions = get_positions(headers)
        
        # 5. Update UI
        with dash_place.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"${equity:.2f}")
            c2.metric("Available", f"${available:.2f}")
            c3.metric("P&L", f"${pnl:.2f}", delta_color="normal")
            c4.metric("Active Trades", len(positions))
            
            if positions:
                st.dataframe(pd.DataFrame(positions)[['epic', 'direction', 'profitAndLoss', 'openPrice']], use_container_width=True, height=150)

        # 6. Midnight Logic
        now = datetime.now(pytz.utc)
        if now.hour == 23 and now.minute >= 59:
            if positions: close_all_positions(headers, positions)
            time.sleep(60)
            continue

        # 7. Aggressive Trade Logic
        # Calculate usage safely to avoid ZeroDivisionError
        usage = (equity - available) / equity if equity > 0 else 0
        
        if usage < 0.80:
            import random
            target = random.choice(WATCHLIST)
            
            # Fetch Market Price
            try:
                mkt = requests.get(f"{MARKETS_URL}/{target}", headers=headers).json()
                if 'snapshot' in mkt:
                    price = mkt['snapshot']['offer']
                    change = mkt['snapshot']['dailyChange']
                    
                    # AI Decision
                    dec = ai_decision(target, price, change, equity, available)
                    
                    with log_place.container():
                        st.write(f"Scanning {target}... AI says: **{dec.get('action', 'WAIT')}** ({dec.get('confidence',0)}%)")
                    
                    # Execute
                    if dec.get('action') in ["BUY", "SELL"] and dec.get('confidence', 0) > 75:
                        size = 0.01 if "BTC" in target else 1
                        execute_trade(headers, target, dec['action'], size)
                        st.toast(f"⚡ Executed {dec['action']} on {target}")
                        time.sleep(2)
            except Exception as e:
                print(f"Market Data Error: {e}")

        time.sleep(3)
        st.rerun()

elif not run_bot:
    st.info("Bot Paused.")

import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz
import random

# --- CONFIGURATION ---
st.set_page_config(page_title="Ultra-Aggressive Trader", layout="wide", page_icon="💀")

# ⚠️ LIVE TRADING URL (Switch carefully)
# BASE_URL = "https://api-capital.backend-capital.com"
BASE_URL = "https://demo-api-capital.backend-capital.com" 

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# AGGRESSIVE WATCHLIST (Popular Volatile Assets)
WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "US500", "TSLA", "AAPL"]

# --- SETUP SECRETS ---
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ SECRETS MISSING! Please check .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

# --- STATE MANAGEMENT ---
if "log_history" not in st.session_state:
    st.session_state["log_history"] = []
if "system_logs" not in st.session_state:
    st.session_state["system_logs"] = []

def add_log(asset, action, conf, price, note=""):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "Time": timestamp,
        "Asset": asset,
        "Price": price,
        "Decision": action,
        "Conf": f"{conf}%",
        "Note": note
    }
    st.session_state["log_history"].insert(0, entry)
    # Keep last 20
    if len(st.session_state["log_history"]) > 20:
        st.session_state["log_history"] = st.session_state["log_history"][:20]

def log_system(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state["system_logs"].insert(0, f"[{timestamp}] {msg}")

# --- API FUNCTIONS ---

def get_session():
    headers = {"X-CAP-API-KEY": CAP_API_KEY, "Content-Type": "application/json"}
    data = {"identifier": CAP_EMAIL, "password": CAP_PASSWORD}
    try:
        resp = requests.post(SESSION_URL, json=data, headers=headers)
        if resp.status_code == 200:
            log_system("✅ Connected to Capital.com")
            return {
                "CST": resp.headers["CST"],
                "X-SECURITY-TOKEN": resp.headers["X-SECURITY-TOKEN"],
                "X-CAP-API-KEY": CAP_API_KEY,
                "Content-Type": "application/json"
            }
        else:
            log_system(f"❌ Login Failed: {resp.status_code} - {resp.text}")
    except Exception as e:
        log_system(f"❌ Connection Error: {e}")
    return None

def get_account_details(headers):
    try:
        resp = requests.get(ACCOUNTS_URL, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if 'accounts' in data:
                return data['accounts'][0]['balance']
        elif resp.status_code == 401:
            return "UNAUTHORIZED"
        else:
            log_system(f"⚠️ Account Fetch Fail: {resp.status_code}")
    except Exception as e:
        log_system(f"⚠️ Account Error: {e}")
    return None

def get_positions(headers):
    try:
        resp = requests.get(POSITIONS_URL, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('positions', [])
        else:
            log_system(f"⚠️ Position Fetch Fail: {resp.text}")
    except Exception as e:
        log_system(f"⚠️ Position Error: {e}")
    return []

def execute_trade(headers, epic, direction, size):
    payload = {
        "epic": epic,
        "direction": direction,
        "size": size,
        "guaranteedStop": False,
        "trailingStop": False
    }
    try:
        resp = requests.post(POSITIONS_URL, json=payload, headers=headers)
        if resp.status_code == 200:
            log_system(f"🚀 TRADE SUCCESS: {direction} {epic}")
            return True
        else:
            log_system(f"❌ TRADE FAILED: {resp.text}")
            return False
    except Exception as e:
        log_system(f"❌ Execution Error: {e}")
        return False

def ai_brain(epic, price, change):
    # Aggressive Prompt
    prompt = f"""
    You are a reckless crypto/stock trader.
    Asset: {epic}
    Price: {price}
    Change: {change}%
    
    TASK: Decided BUY or SELL immediately.
    Constraint: You CANNOT say WAIT unless market is closed.
    
    Return JSON: {{"action": "BUY" or "SELL", "confidence": 0-100, "reason": "short text"}}
    """
    try:
        resp = model.generate_content(prompt)
        text = resp.text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except Exception as e:
        log_system(f"AI Error: {e}")
        return {"action": "WAIT", "confidence": 0, "reason": "AI Fail"}

# --- APP LAYOUT ---

st.title("💀 Aggressive Auto-Trader (Debug Mode)")

if "headers" not in st.session_state:
    st.session_state["headers"] = get_session()

# Sidebar
with st.sidebar:
    run_bot = st.toggle("ACTIVATE BOT", value=False, key="active")
    if st.button("♻️ Reconnect"):
        st.session_state["headers"] = get_session()
    
    st.divider()
    st.subheader("System Logs")
    # Show last 10 system logs
    for log in st.session_state["system_logs"][:10]:
        st.caption(log)

# Main Dashboard
headers = st.session_state["headers"]

if not headers:
    st.warning("Not Connected. Click Reconnect.")
    if run_bot: st.stop()
else:
    # 1. Account Info
    raw_bal = get_account_details(headers)
    
    if raw_bal == "UNAUTHORIZED":
        log_system("Token Expired. Refreshing...")
        st.session_state["headers"] = get_session()
        st.rerun()
        
    if raw_bal and isinstance(raw_bal, dict):
        equity = raw_bal.get('equity', 0)
        # Fallback calculation if API returns 0 equity
        if equity == 0:
            equity = raw_bal.get('balance', 0) + raw_bal.get('profitLoss', 0)
            
        avail = raw_bal.get('available', 0)
        pnl = raw_bal.get('profitLoss', 0)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Equity", f"${equity:,.2f}")
        c2.metric("Available", f"${avail:,.2f}")
        c3.metric("P&L", f"${pnl:,.2f}", delta=pnl)
        
        positions = get_positions(headers)
        c4.metric("Open Trades", len(positions))

        # 2. Open Trades Table
        st.subheader("⚔️ Active Positions")
        if positions:
            df = pd.DataFrame(positions)
            st.dataframe(df[['epic', 'direction', 'size', 'openPrice', 'profitAndLoss']], use_container_width=True)
        else:
            st.info("No open trades.")

        # 3. AI Stream
        st.subheader("🧠 AI Thought Stream")
        if st.session_state["log_history"]:
            st.dataframe(pd.DataFrame(st.session_state["log_history"]), use_container_width=True)
        else:
            st.write("Waiting for analysis...")

        # --- TRADING LOOP ---
        if run_bot:
            # Pick ONE asset to process (avoids blocking UI)
            target = random.choice(WATCHLIST)
            
            # 1. Fetch Market
            try:
                mkt_resp = requests.get(f"{MARKETS_URL}/{target}", headers=headers)
                if mkt_resp.status_code == 200:
                    mkt_data = mkt_resp.json()
                    
                    if 'snapshot' in mkt_data:
                        price = mkt_data['snapshot']['offer']
                        change = mkt_data['snapshot']['dailyChange']
                        
                        # 2. AI Decision
                        dec = ai_brain(target, price, change)
                        action = dec.get('action', 'WAIT')
                        conf = int(dec.get('confidence', 0))
                        reason = dec.get('reason', '')
                        
                        add_log(target, action, conf, price, reason)
                        
                        # 3. Execution (Threshold 60%)
                        if action in ["BUY", "SELL"] and conf > 60:
                            # Verify Funds
                            if avail > 50: # Minimum buffer
                                size = 0.01 if "BTC" in target else 1
                                execute_trade(headers, target, action, size)
                            else:
                                log_system("❌ Insufficient Funds for Trade")
                    else:
                        log_system(f"⚠️ No snapshot for {target}")
                else:
                    log_system(f"⚠️ Market Fetch Fail {target}: {mkt_resp.status_code}")
                    
            except Exception as e:
                log_system(f"❌ Loop Error: {e}")

            time.sleep(1)
            st.rerun()

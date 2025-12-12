import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz

# --- CONFIGURATION ---
st.set_page_config(page_title="Aggressive AI Trader", layout="wide", page_icon="⚡")

# 1. API CONFIGURATION
# ---------------------------------------------------------
# WARNING: CHANGE TO 'https://api-capital.backend-capital.com' FOR LIVE TRADING
BASE_URL = "https://demo-api-capital.backend-capital.com" 
# ---------------------------------------------------------

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# DIVERSIFIED PORTFOLIO WATCHLIST (Epics)
# Mix of Crypto, Forex, Commodities, Stocks to spread risk
WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "OIL_CRUDE", "US500", "AAPL"]

# SECRETS LOADING
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets not found. Please create .streamlit/secrets.toml")
    st.stop()

# SETUP AI
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

# --- CORE FUNCTIONS ---

def get_session():
    """Authenticates and returns headers."""
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
    except Exception as e:
        st.error(f"Auth Error: {e}")
    return None

def get_account(headers):
    resp = requests.get(ACCOUNTS_URL, headers=headers)
    if resp.status_code == 200:
        return resp.json()['accounts'][0]['balance']
    return None

def get_positions(headers):
    resp = requests.get(POSITIONS_URL, headers=headers)
    if resp.status_code == 200:
        return resp.json()['positions']
    return []

def close_all_positions(headers, positions):
    """Emergency close function for 23:59 rule."""
    st.warning("⏰ MIDNIGHT PROTOCOL: Closing ALL positions.")
    for p in positions:
        deal_id = p['dealId']
        requests.delete(f"{POSITIONS_URL}/{deal_id}", headers=headers)
        time.sleep(0.2)

def execute_trade(headers, epic, direction, size):
    """Executes a trade on Capital.com"""
    payload = {
        "epic": epic,
        "direction": direction, # "BUY" or "SELL"
        "size": size,
        "guaranteedStop": False,
        "trailingStop": False
    }
    resp = requests.post(POSITIONS_URL, json=payload, headers=headers)
    return resp.json()

def ai_decision(epic, price, change, equity, available):
    """
    Asks Gemini for AGGRESSIVE micro-trading decision.
    """
    prompt = f"""
    Role: Aggressive High-Frequency Trading Bot.
    Context:
    - Asset: {epic}
    - Price: {price}
    - Day Change: {change}%
    - Account Equity: {equity}
    - Funds Available: {available}
    
    Strategy:
    - We want to maximize profit. 
    - Be aggressive. 
    - If trend is strong, ENTER.
    
    Output JSON ONLY:
    {{
        "action": "BUY" or "SELL" or "WAIT",
        "confidence": 0-100,
        "leverage_hint": "high"
    }}
    """
    try:
        resp = model.generate_content(prompt)
        text = resp.text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except:
        return {"action": "WAIT", "confidence": 0}

# --- MAIN UI & LOOP ---

st.title("⚡ Aggressive Auto-Trader (Midnight Protocol)")

# UI Containers
dash_placeholder = st.empty()
log_placeholder = st.empty()
pos_placeholder = st.empty()

# Sidebar Control
with st.sidebar:
    st.header("Control Panel")
    run_bot = st.toggle("ACTIVATE BOT", value=False)
    st.caption("While active, bot runs in loop. Do not close tab.")

if "headers" not in st.session_state:
    st.session_state["headers"] = get_session()

headers = st.session_state["headers"]

# --- THE BOT LOOP ---
if run_bot and headers:
    
    while True:
        # 1. TIME CHECK (Midnight Protocol)
        # Using UTC for consistency, adjust pytz.timezone if needed
        now = datetime.now(pytz.utc)
        current_time_str = now.strftime("%H:%M:%S")
        
        # Fetch Data
        acct = get_account(headers)
        positions = get_positions(headers)
        
        # UPDATE DASHBOARD
        with dash_placeholder.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"${acct['equity']:.2f}")
            c2.metric("Avail. Margin", f"${acct['available']:.2f}")
            c3.metric("P&L", f"${acct['profitLoss']:.2f}", delta_color="normal")
            c4.metric("Status", "RUNNING", f"Time: {current_time_str}")

        # UPDATE POSITIONS TABLE
        with pos_placeholder.container():
            if positions:
                df = pd.DataFrame(positions)
                st.dataframe(df[['epic', 'direction', 'size', 'openPrice', 'profitAndLoss']], use_container_width=True)
            else:
                st.info("No Open Trades")

        # LOGIC 1: MIDNIGHT CLOSE
        # Triggers if time is 23:59 (UTC)
        if now.hour == 23 and now.minute >= 59:
            if positions:
                close_all_positions(headers, positions)
                log_placeholder.error("🛑 MIDNIGHT: All trades closed.")
            else:
                log_placeholder.info("🌙 Midnight: Sleeping until reset.")
            time.sleep(60)
            continue

        # LOGIC 2: AGGRESSIVE ENTRY
        # Only enter if we are using less than 80% of funds
        equity = acct['equity']
        used_margin = acct['margin']
        utilization = used_margin / equity if equity > 0 else 1.0

        if utilization < 0.80:
            # Pick a random asset from watchlist to analyze (to avoid rate limits on scanning all at once)
            import random
            target = random.choice(WATCHLIST)
            
            # Get Market Price
            mkt_req = requests.get(f"{MARKETS_URL}/{target}", headers=headers)
            if mkt_req.status_code == 200:
                data = mkt_req.json()
                snapshot = data['snapshot']
                price = snapshot['offer']
                change = snapshot['dailyChange']

                # Ask AI
                decision = ai_decision(target, price, change, equity, acct['available'])
                
                with log_placeholder.container():
                    st.write(f"🤖 **AI Analysis on {target}:** {decision['action']} (Conf: {decision['confidence']}%)")

                # EXECUTE
                if decision['action'] in ["BUY", "SELL"] and decision['confidence'] > 75:
                    # Size calculation: 5% of available margin per trade to allow diversification
                    # Note: Capital.com requires minimum sizes, this is a simplified calculation
                    # You might need to adjust 'size' based on specific asset minimums (e.g. 0.01 for BTC)
                    trade_size = 0.01 if "BTC" in target else 1 
                    
                    st.toast(f"🚀 Executing {decision['action']} on {target}")
                    execute_trade(headers, target, decision['action'], trade_size)
                    time.sleep(2) # Cooldown to prevent API spam
        else:
            log_placeholder.warning("⚠️ Max Margin (80%) Reached. Holding positions.")

        # Loop delay
        time.sleep(5) 
        st.rerun()

elif not run_bot:
    st.info("Bot is deactivated. Toggle sidebar to start.")

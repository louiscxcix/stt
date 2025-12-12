import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz

# --- CONFIGURATION ---
st.set_page_config(page_title="Pro AI Trader", layout="wide", page_icon="📈")

# ⚠️ CHANGE TO 'https://api-capital.backend-capital.com' FOR LIVE
BASE_URL = "https://demo-api-capital.backend-capital.com" 

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "OIL_CRUDE", "US500", "AAPL", "TSLA"]

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
    except Exception as e:
        print(f"Connection Error: {e}")
    return None

def get_account(headers):
    """Fetches account data safely."""
    try:
        resp = requests.get(ACCOUNTS_URL, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if 'accounts' in data and len(data['accounts']) > 0:
                return data['accounts'][0]['balance']
        elif resp.status_code == 401:
            return "UNAUTHORIZED"
    except Exception as e:
        print(f"Account Fetch Error: {e}")
    return None

def get_positions(headers):
    """Fetches full position details."""
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

st.title("💸 AI Wealth Manager")

# UI Layout: Sidebar for controls
with st.sidebar:
    st.header("⚙️ Bot Control")
    run_bot = st.toggle("ACTIVATE TRADING", value=False)
    st.markdown("---")
    st.markdown("**Strategy:** Aggressive Micro-Trading")
    st.markdown("**Max Allocation:** 80%")
    st.markdown("**Midnight Close:** ON")

# Layout Placeholders
metrics_container = st.container()
st.markdown("---")
positions_container = st.container()
st.markdown("---")
log_container = st.container()

# Session State Init
if "headers" not in st.session_state:
    st.session_state["headers"] = get_session()

# --- BOT LOOP ---
if run_bot:
    while True:
        # 1. Connection Check
        if not st.session_state["headers"]:
            st.session_state["headers"] = get_session()
            if not st.session_state["headers"]:
                st.error("Waiting for connection...")
                time.sleep(5)
                continue

        # 2. Fetch Data
        headers = st.session_state["headers"]
        acct = get_account(headers)
        
        # 3. Handle Auth
        if acct == "UNAUTHORIZED":
            st.session_state["headers"] = get_session()
            continue
        elif acct is None:
            time.sleep(2)
            continue 

        # 4. Extract Metrics
        equity = acct.get('equity', 0.0)      # Total Asset Value
        available = acct.get('available', 0.0) # Free to trade
        pnl = acct.get('profitLoss', 0.0)      # Total P&L
        balance = acct.get('balance', 0.0)     # Cash Balance
        
        positions = get_positions(headers)
        
        # 5. RENDER DASHBOARD (Account Metrics)
        with metrics_container:
            # Clear previous content slightly by overwriting
            metrics_container.subheader("🏦 Account Overview")
            m1, m2, m3, m4 = st.columns(4)
            
            # Styling metrics
            m1.metric("Total Equity (Assets)", f"${equity:,.2f}", help="Cash + Open P&L")
            m2.metric("Available Funds", f"${available:,.2f}", help="Funds available for new trades")
            m3.metric("Total P&L", f"${pnl:,.2f}", delta=f"{pnl:,.2f}")
            m4.metric("Active Trades", len(positions))

        # 6. RENDER OPEN TRADES (Detailed)
        with positions_container:
            positions_container.subheader("📊 Open Positions Breakdown")
            if positions:
                # Prepare data for cleaner display
                pos_data = []
                for p in positions:
                    pos_data.append({
                        "Instrument": p['epic'],
                        "Action": p['direction'],
                        "Size": p['dealSize'],
                        "Open Price": f"${p['openPrice']}",
                        "Current P&L": p['profitAndLoss'],
                        "Date": p['createdDate']
                    })
                
                df = pd.DataFrame(pos_data)
                
                # Use column configuration for better P&L coloring
                st.dataframe(
                    df,
                    column_config={
                        "Current P&L": st.column_config.NumberColumn(
                            "Profit / Loss ($)",
                            format="$%.2f",
                        )
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No trades currently open. AI is scanning...")

        # 7. Midnight Protocol
        now = datetime.now(pytz.utc)
        if now.hour == 23 and now.minute >= 59:
            if positions: close_all_positions(headers, positions)
            time.sleep(60)
            continue

        # 8. AI Scanning & Execution
        usage = (equity - available) / equity if equity > 0 else 0
        
        if usage < 0.80:
            import random
            target = random.choice(WATCHLIST)
            
            try:
                mkt = requests.get(f"{MARKETS_URL}/{target}", headers=headers).json()
                if 'snapshot' in mkt:
                    price = mkt['snapshot']['offer']
                    change = mkt['snapshot']['dailyChange']
                    
                    dec = ai_decision(target, price, change, equity, available)
                    
                    with log_container:
                        # Keep only the latest log
                        log_container.text(f"🤖 Scanning {target}... Action: {dec.get('action')} | Conf: {dec.get('confidence')}%")
                    
                    if dec.get('action') in ["BUY", "SELL"] and dec.get('confidence', 0) > 75:
                        size = 0.01 if "BTC" in target else 1
                        execute_trade(headers, target, dec['action'], size)
                        st.toast(f"⚡ Executed {dec['action']} on {target}")
                        time.sleep(2)
            except Exception as e:
                pass

        time.sleep(3)
        st.rerun()

elif not run_bot:
    st.info("Bot is paused. Toggle 'Activate Trading' in the sidebar to start.")

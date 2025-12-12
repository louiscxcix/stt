import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz

# --- CONFIGURATION ---
st.set_page_config(page_title="Ultra-Aggressive Trader", layout="wide", page_icon="🧠")

# ⚠️ LIVE TRADING URL
# BASE_URL = "https://api-capital.backend-capital.com"
BASE_URL = "https://demo-api-capital.backend-capital.com" 

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# AGGRESSIVE WATCHLIST
WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "US500", "TSLA", "AAPL"]

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

# --- LOGGING STATE ---
if "log_history" not in st.session_state:
    st.session_state["log_history"] = []

def add_log(asset, action, conf, price):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "Time": timestamp, "Asset": asset, "Price": price,
        "AI Decision": action, "Conf": f"{conf}%"
    }
    st.session_state["log_history"].insert(0, entry)
    if len(st.session_state["log_history"]) > 15:
        st.session_state["log_history"] = st.session_state["log_history"][:15]

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

def get_account_details(headers):
    """
    Fetches full account details and handles missing keys manually.
    """
    try:
        resp = requests.get(ACCOUNTS_URL, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if 'accounts' in data and len(data['accounts']) > 0:
                return data['accounts'][0]['balance'] # Returns the specific balance object
        elif resp.status_code == 401:
            return "UNAUTHORIZED"
    except Exception as e:
        st.error(f"API Error: {e}")
    return None

def get_positions(headers):
    try:
        resp = requests.get(POSITIONS_URL, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('positions', [])
    except: pass
    return []

def execute_trade(headers, epic, direction, size):
    payload = {
        "epic": epic, "direction": direction, "size": size,
        "guaranteedStop": False, "trailingStop": False
    }
    requests.post(POSITIONS_URL, json=payload, headers=headers)

def ai_aggressive_decision(epic, price, change):
    prompt = f"""
    You are a high-frequency scalper.
    Asset: {epic} | Price: {price} | Change: {change}%
    
    INSTRUCTIONS:
    1. Analyze the trend briefly.
    2. Output BUY or SELL if there is ANY momentum.
    3. Only output WAIT if market is completely flat.
    
    Output JSON ONLY: {{"action": "BUY" or "SELL" or "WAIT", "confidence": 0-100}}
    """
    try:
        resp = model.generate_content(prompt)
        text = resp.text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)
    except:
        return {"action": "WAIT", "confidence": 0} 

# --- UI & LOGIC ---

st.title("🧠 AI Brain Logs & Execution")

# Sidebar
with st.sidebar:
    is_running = st.toggle("ACTIVATE BOT", value=False, key="run_state")
    st.write("Status:", "🟢 RUNNING" if is_running else "🔴 PAUSED")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()

# Containers
metrics_area = st.container()
st.divider()
col_logs, col_trades = st.columns([1, 1])
debug_expander = st.expander("🔍 Debug Raw API Data (Check if Equity is missing)")

# State Init
if "headers" not in st.session_state:
    st.session_state["headers"] = get_session()

# --- MAIN LOOP ---
headers = st.session_state["headers"]

if not headers:
    headers = get_session()
    st.session_state["headers"] = headers

if headers:
    # Get raw balance object
    raw_balance = get_account_details(headers)
    
    if raw_balance == "UNAUTHORIZED":
        st.session_state["headers"] = get_session()
        st.rerun()
        
    if raw_balance and isinstance(raw_balance, dict):
        # --- FIXED DATA MAPPING ---
        # 1. Try to get direct values
        available = raw_balance.get('available', 0.0)
        pnl = raw_balance.get('profitLoss', 0.0)
        equity = raw_balance.get('equity', 0.0)
        balance_cash = raw_balance.get('balance', 0.0)
        
        # 2. CALCULATION FALLBACK
        # If Equity is 0 but we have Available/Cash, calculate it manually
        if equity == 0 and balance_cash > 0:
            equity = balance_cash + pnl

        positions = get_positions(headers)
        
        # 3. Render Metrics
        with metrics_area:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"${equity:,.2f}", help="Cash + P&L")
            c2.metric("Available", f"${available:,.2f}")
            c3.metric("P&L", f"${pnl:,.2f}", delta=f"{pnl:,.2f}")
            c4.metric("Open Trades", len(positions))

        # 4. Debug Section (Use this to see what API sends!)
        with debug_expander:
            st.write("Raw Balance Data from Capital.com:")
            st.json(raw_balance)

        # 5. LOGIC LOOP
        if is_running:
            import random
            target_asset = random.choice(WATCHLIST)
            
            # Check Margin (Safety)
            usage = (equity - available) / equity if equity > 0 else 0
            
            if usage < 0.80:
                try:
                    mkt = requests.get(f"{MARKETS_URL}/{target_asset}", headers=headers).json()
                    if 'snapshot' in mkt:
                        price = mkt['snapshot']['offer']
                        change = mkt['snapshot']['dailyChange']
                        
                        dec = ai_aggressive_decision(target_asset, price, change)
                        action = dec.get('action')
                        conf = dec.get('confidence', 0)
                        
                        add_log(target_asset, action, conf, price)
                        
                        if action in ["BUY", "SELL"] and conf >= 60:
                            size = 0.02 if "BTC" in target_asset else 1
                            execute_trade(headers, target_asset, action, size)
                            st.toast(f"💣 OPENED {action} on {target_asset}!")
                            
                except Exception as e:
                    pass
            else:
                st.warning("Max Margin Reached. Holding...")
        
        # 6. RENDER LOGS
        with col_logs:
            st.subheader("📜 Live AI Thought Stream")
            if st.session_state["log_history"]:
                log_df = pd.DataFrame(st.session_state["log_history"])
                def color_action(val):
                    color = 'grey'
                    if val == 'BUY': color = '#90EE90' 
                    elif val == 'SELL': color = '#FFB6C1'
                    return f'background-color: {color}; color: black'
                st.dataframe(log_df.style.applymap(color_action, subset=['AI Decision']), 
                             use_container_width=True, height=400)

        with col_trades:
            st.subheader("📊 Active Positions")
            if positions:
                pos_df = pd.DataFrame(positions)
                st.dataframe(pos_df[['epic', 'direction', 'profitAndLoss', 'dealSize']], 
                             use_container_width=True, height=400)
            else:
                st.info("No open trades.")

        if is_running:
            time.sleep(1)
            st.rerun()

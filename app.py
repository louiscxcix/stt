import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import random
import json
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Hedge Fund AI Manager", layout="wide", page_icon="🏦")

# API ENDPOINTS
BASE_URL = "https://demo-api-capital.backend-capital.com" 
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# DIVERSIFIED PORTFOLIO (15+ Assets)
FULL_PORTFOLIO = [
    # Crypto
    "BTCUSD", "ETHUSD", "XRPUSD",
    # Forex
    "EURUSD", "GBPUSD", "USDJPY",
    # Commodities
    "GOLD", "OIL_CRUDE", "NATURAL_GAS",
    # Indices
    "US500", "US30", "DE40",
    # Tech Stocks
    "TSLA", "NVDA", "AAPL"
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
# Using Flash Lite for speed/cost balance
TARGET_MODEL_NAME = 'gemini-2.5-flash-lite'
model = genai.GenerativeModel(TARGET_MODEL_NAME)

# --- STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "cycle_status" not in st.session_state: st.session_state["cycle_status"] = "Ready."

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

# --- 2-STEP AI LOGIC ---

def generate_strategy_prompt(epic):
    """Step 1: Get Strategy"""
    meta_prompt = f"""
    You are a hedge fund manager.
    Create a 1-sentence aggressive strategy to trade {epic}.
    Focus on current volatility.
    """
    try:
        response = model.generate_content(meta_prompt)
        return response.text.strip()
    except Exception as e:
        if "429" in str(e): return "RATE_LIMIT"
        return f"Analyze {epic} for immediate volatility."

def analyze_market(strategy_instruction, price, change):
    """Step 2: Get Decision"""
    final_prompt = f"""
    STRATEGY: {strategy_instruction}
    DATA: Price {price} | Change {change}%
    
    TASK: Decide BUY, SELL, or WAIT.
    Maximize profit. Be aggressive.
    
    JSON format: {{"action": "BUY"/"SELL"/"WAIT", "confidence": 0-100, "reason": "brief text"}}
    """
    
    try:
        response = model.generate_content(final_prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        if "429" in str(e): return {"action": "RATE_LIMIT"}
        return {"action": "WAIT", "reason": "Error"}

# --- UI LAYOUT ---

st.title(f"🏦 Hedge Fund AI Manager")

with st.sidebar:
    st.header("Control")
    run_bot = st.toggle("START PORTFOLIO SCANNER", key="run_bot")
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

        # 2. POSITIONS (TOP PRIORITY)
        st.subheader("⚔️ Active Positions")
        if positions:
            df = pd.DataFrame(positions)
            st.dataframe(
                df[['epic', 'direction', 'dealSize', 'openPrice', 'profitAndLoss']], 
                use_container_width=True,
                column_config={"profitAndLoss": st.column_config.NumberColumn("P&L", format="$%.2f")}
            )
        else:
            st.info("No trades open. Scanning portfolio...")

        st.divider()

        # 3. LIVE SESSION LOGS
        st.subheader("📜 Live Session Log")
        if st.session_state["log_history"]:
            # Create a nice table from the history
            log_df = pd.DataFrame(st.session_state["log_history"])
            st.dataframe(
                log_df, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "Conf": st.column_config.TextColumn("Conf", width="small"),
                    "Action": st.column_config.TextColumn("Action", width="small"),
                }
            )
        else:
            st.caption("Waiting for first scan batch...")

        # --- EXECUTION LOOP ---
        if run_bot:
            status_box = st.empty()
            
            # BATCH LOGIC: Select 5 random assets to scan this minute
            # This prevents 429 Rate Limits (Quota)
            batch = random.sample(FULL_PORTFOLIO, 5)
            
            with status_box.status(f"⚡ Scanning Batch: {', '.join(batch)}", expanded=True) as status:
                
                for i, target in enumerate(batch):
                    status.write(f"**({i+1}/5) Analyzing {target}...**")
                    
                    try:
                        # 1. Get Data
                        mkt = requests.get(f"{MARKETS_URL}/{target}", headers=headers).json()
                        
                        if 'snapshot' in mkt:
                            snap = mkt['snapshot']
                            price = snap.get('offer', snap.get('bid', 0))
                            change = snap.get('dailyChange', 0)
                            
                            # 2. Step 1 (Strategy)
                            strategy = generate_strategy_prompt(target)
                            if strategy == "RATE_LIMIT":
                                status.warning("Rate Limit Hit. Cooling down 15s...")
                                time.sleep(15)
                                continue

                            # 3. Step 2 (Decision)
                            decision = analyze_market(strategy, price, change)
                            
                            action = decision.get('action', 'WAIT')
                            
                            if action == "RATE_LIMIT":
                                status.warning("Rate Limit Hit. Cooling down...")
                                time.sleep(15)
                                continue

                            conf = decision.get('confidence', 0)
                            reason = decision.get('reason', '-')
                            
                            # Add to Log
                            new_log = {
                                "Time": datetime.now().strftime("%H:%M:%S"),
                                "Asset": target,
                                "Action": action,
                                "Conf": f"{conf}%",
                                "Reason": reason
                            }
                            st.session_state["log_history"].insert(0, new_log)
                            # Keep log clean (last 20)
                            if len(st.session_state["log_history"]) > 20:
                                st.session_state["log_history"].pop()
                            
                            # 4. Execute
                            if action in ["BUY", "SELL"] and conf > 60:
                                if avail > 100:
                                    status.write(f"🚀 **EXECUTING {action}!**")
                                    # Sizing: Crypto needs small size (0.01), Stocks need 1
                                    size = 0.01 if "USD" in target and "BTC" in target else 1
                                    execute_trade(headers, target, action, size)
                                    st.toast(f"✅ Trade Sent: {target}")
                                else:
                                    st.error("Insufficient Funds")
                            
                            # SMART DELAY (12s per asset = 60s total for 5 assets)
                            # This keeps us under the 15 request/min limit
                            time.sleep(10) 
                            
                    except Exception as e:
                        status.write(f"Error on {target}: {e}")
            
            # Loop Reset
            st.rerun()

import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz
import random
import json
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Gemini 2.5 Flash Trader", layout="wide", page_icon="⚡")

# ⚠️ DEMO API
BASE_URL = "https://demo-api-capital.backend-capital.com" 

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "US500", "TSLA", "AAPL"]

# --- SECRETS & MODEL ---
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets missing! Check .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
# Using Flash Lite
TARGET_MODEL_NAME = 'gemini-2.5-flash-lite' 
model = genai.GenerativeModel(TARGET_MODEL_NAME)

# --- SESSION STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "last_prompt" not in st.session_state: st.session_state["last_prompt"] = "Waiting..."
if "last_response" not in st.session_state: st.session_state["last_response"] = "Waiting..."

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
        if resp.status_code == 200:
            return resp.json()['accounts'][0]['balance']
        elif resp.status_code == 401:
            return "UNAUTHORIZED"
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

# --- PROMPT ENGINE ---
def generate_varied_prompt(epic, price, change):
    # Aggressive personas only
    personas = [
        "A Reckless High-Frequency Scalper (You love volatility)",
        "A Momentum Algorithm (You chase trends immediately)",
        "A Breakout Trader (You buy high and sell low for speed)"
    ]
    selected_persona = random.choice(personas)
    
    prompt = f"""
    IDENTITY: You are {selected_persona}.
    ASSET: {epic} | PRICE: {price} | CHANGE: {change}%
    
    CRITICAL RULE:
    - You CANNOT say "WAIT".
    - You MUST pick "BUY" or "SELL" based on the slightest momentum.
    - If unsure, guess based on the trend direction.
    
    RESPONSE FORMAT (JSON ONLY):
    {{
        "action": "BUY" or "SELL",
        "confidence": 60-100,
        "reason": "1 sentence why"
    }}
    """
    return prompt

def ask_gemini_robust(epic, price, change):
    prompt = generate_varied_prompt(epic, price, change)
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            raw_text = response.text
            clean_json = raw_text.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_json), prompt, raw_text
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                st.toast(f"⚠️ Quota Hit (Attempt {attempt+1}). Retrying...", icon="⏳")
                time.sleep(20) # Simple fixed wait for simplicity
                continue
            return {"action": "WAIT", "confidence": 0, "reason": f"Error: {error_msg}"}, prompt, error_msg

    return {"action": "WAIT", "confidence": 0, "reason": "Failed"}, prompt, "Failed"

# --- UI LAYOUT ---

st.title(f"⚡ {TARGET_MODEL_NAME} Auto-Trader")

with st.sidebar:
    st.header("Control")
    run_bot = st.toggle("ACTIVATE BOT", key="bot_active")
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
        # --- 1. METRICS (TOP) ---
        equity = acct.get('equity', acct.get('balance', 0) + acct.get('profitLoss', 0))
        avail = acct.get('available', 0)
        positions = get_positions(headers)
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Equity", f"${equity:,.0f}")
        m2.metric("Available", f"${avail:,.0f}")
        m3.metric("P&L", f"${acct.get('profitLoss', 0):,.2f}")
        m4.metric("Active Trades", len(positions))

        st.divider()

        # --- 2. ACTIVE TRADES (PRIORITY VIEW) ---
        st.subheader("⚔️ Active Positions")
        if positions:
            df = pd.DataFrame(positions)
            # Formatting for clarity
            st.dataframe(
                df[['epic', 'direction', 'dealSize', 'openPrice', 'profitAndLoss']], 
                use_container_width=True,
                column_config={
                    "profitAndLoss": st.column_config.NumberColumn("P&L", format="$%.2f")
                }
            )
        else:
            st.info("No open trades. Bot is hunting...")

        st.divider()

        # --- 3. LIVE AI BRAIN (FOLDED) ---
        with st.expander("🧠 Live AI Decision Logs (Click to Expand)", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.caption("Latest Prompt Sent:")
                st.code(st.session_state["last_prompt"], language="text")
            with c2:
                st.caption("Latest AI Reply:")
                st.code(st.session_state["last_response"], language="json")

            if st.session_state["log_history"]:
                st.markdown("### History")
                st.dataframe(pd.DataFrame(st.session_state["log_history"]), use_container_width=True)

        # --- 4. EXECUTION LOOP ---
        if run_bot:
            status_box = st.empty()
            with status_box.status("⚡ AI Analyzing...", expanded=True) as status:
                
                target = random.choice(WATCHLIST)
                status.write(f"Target: **{target}**")
                
                try:
                    mkt = requests.get(f"{MARKETS_URL}/{target}", headers=headers).json()
                    
                    if 'snapshot' in mkt:
                        snap = mkt['snapshot']
                        price = snap.get('offer', snap.get('bid', 0))
                        change = snap.get('dailyChange', 0)
                        
                        # AI Call
                        decision, raw_prompt, raw_resp = ask_gemini_robust(target, price, change)
                        
                        st.session_state["last_prompt"] = raw_prompt
                        st.session_state["last_response"] = raw_resp
                        
                        action = decision.get('action', 'WAIT')
                        conf = decision.get('confidence', 0)
                        
                        # Log
                        new_log = {
                            "Time": datetime.now().strftime("%H:%M:%S"), 
                            "Asset": target, "Action": action, 
                            "Conf": f"{conf}%", "Reason": decision.get("reason", "-")
                        }
                        st.session_state["log_history"].insert(0, new_log)
                        
                        # Execute if BUY or SELL (WAIT is effectively banned by prompt)
                        if action in ["BUY", "SELL"]:
                            if avail > 50: 
                                status.write(f"🚀 EXECUTING {action}!")
                                size = 0.01 if "BTC" in target else 1
                                execute_trade(headers, target, action, size)
                                st.toast(f"Sent {action} {target}")
                            else:
                                st.error("Insufficient Funds")
                    
                except Exception as e:
                    status.write(f"Error: {e}")
            
            # Countdown
            for s in range(60, 0, -1):
                status_box.info(f"⏳ Next scan in {s}s")
                time.sleep(1)
            st.rerun()

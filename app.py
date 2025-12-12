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

# ⚠️ DEMO API (Switch to live only when ready)
BASE_URL = "https://demo-api-capital.backend-capital.com" 

SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "US500", "TSLA", "AAPL"]

# --- SECRETS & MODEL SETUP ---
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets missing! Check .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GEMINI_KEY)

# Using Flash Lite (Note: If 2.5 is too restricted, try 'gemini-1.5-flash')
TARGET_MODEL_NAME = 'gemini-2.5-flash-lite' 
model = genai.GenerativeModel(TARGET_MODEL_NAME)

# --- SESSION STATE INITIALIZATION ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "last_prompt" not in st.session_state: st.session_state["last_prompt"] = "Waiting..."
if "last_response" not in st.session_state: st.session_state["last_response"] = "Waiting..."

# --- HELPER FUNCTIONS ---

def get_session():
    """Connects to Capital.com"""
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
    """Fetches account info safely"""
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

# --- ADVANCED PROMPT GENERATOR ---
def generate_varied_prompt(epic, price, change):
    """
    Creates a unique, professional prompt every time to force the AI to think differently.
    """
    personas = [
        "The High-Frequency Scalper (Focus: Speed, Momentum, Instant Execution)",
        "The Contrarian Analyst (Focus: Overbought/Oversold Reversals)",
        "The Macro Risk Manager (Focus: Safety, Trend Confirmation, Volume)",
        "The Technical Chartist (Focus: Support/Resistance Breakouts)",
        "The Volatility Hunter (Focus: Large % Changes, Aggressive Entries)"
    ]
    
    selected_persona = random.choice(personas)
    
    prompt = f"""
    IDENTITY: You are an elite algorithmic trader acting as: {selected_persona}.
    
    MARKET DATA:
    - Asset: {epic}
    - Current Price: {price}
    - Daily Change: {change}%
    
    TASK:
    Analyze the data strictly through the lens of your assigned persona.
    If the data fits your specific strategy, execute aggressively. 
    If it is ambiguous, HOLD.
    
    RESPONSE FORMAT (Strict JSON):
    {{
        "action": "BUY" or "SELL" or "WAIT",
        "confidence": 0-100,
        "reason": "Professional analysis relative to {selected_persona}"
    }}
    """
    return prompt

def ask_gemini_robust(epic, price, change):
    """
    Communicates with Gemini and handles 429 Errors (Quota Exceeded) automatically.
    """
    prompt = generate_varied_prompt(epic, price, change)
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # 1. Send Request
            response = model.generate_content(prompt)
            
            # 2. Parse Response
            raw_text = response.text
            clean_json = raw_text.replace("```json", "").replace("```", "").strip()
            
            return json.loads(clean_json), prompt, raw_text
            
        except Exception as e:
            error_msg = str(e)
            
            # 3. CATCH 429 QUOTA ERRORS
            if "429" in error_msg or "Quota exceeded" in error_msg:
                st.toast(f"⚠️ Quota Hit (Attempt {attempt+1}/{max_retries}). Retrying...", icon="⏳")
                
                # Try to find the specific wait time in the error message (e.g. "retry in 17s")
                match = re.search(r"retry in (\d+\.?\d*)s", error_msg)
                wait_time = float(match.group(1)) + 1 if match else 20
                
                # Wait professionally
                time.sleep(wait_time)
                continue # Retry loop
            
            # If it's another error (not 429), break and return failure
            return {"action": "WAIT", "confidence": 0, "reason": f"Error: {error_msg}"}, prompt, error_msg

    return {"action": "WAIT", "confidence": 0, "reason": "Max Retries Exceeded"}, prompt, "Failed"

# --- DASHBOARD UI ---

st.title(f"⚡ {TARGET_MODEL_NAME} Pro Trader")

# Sidebar Controls
with st.sidebar:
    st.header("Control Center")
    run_bot = st.toggle("ACTIVATE BOT", key="bot_active")
    
    st.divider()
    if st.button("Reconnect Capital.com"):
        st.session_state["headers"] = get_session()
        st.rerun()

    with st.expander("🔎 Models"):
        try:
            st.write("Available Models:")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    st.caption(m.name)
        except: pass

# 1. Connect
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
        # --- TOP METRICS ---
        equity = acct.get('equity', acct.get('balance', 0) + acct.get('profitLoss', 0))
        avail = acct.get('available', 0)
        positions = get_positions(headers)
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Equity", f"${equity:,.0f}")
        m2.metric("Available", f"${avail:,.0f}")
        m3.metric("P&L", f"${acct.get('profitLoss', 0):,.2f}")
        m4.metric("Active Trades", len(positions))

        st.divider()

        # --- LIVE AI WIRETAP ---
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("📡 Varied Outgoing Prompt")
            st.caption("Notice how the 'Identity' changes every scan:")
            st.code(st.session_state["last_prompt"], language="text")
            
        with c2:
            st.subheader(f"📥 {TARGET_MODEL_NAME} Analysis")
            st.code(st.session_state["last_response"], language="json")

        st.divider()

        # --- LOGS & TRADES ---
        c_log, c_pos = st.columns(2)
        
        with c_log:
            st.subheader("📜 Decision Log")
            if st.session_state["log_history"]:
                df_log = pd.DataFrame(st.session_state["log_history"])
                st.dataframe(df_log, use_container_width=True, hide_index=True)
            else:
                st.info("Log empty. Activate bot to start scanning.")

        with c_pos:
            st.subheader("⚔️ Open Positions")
            if positions:
                st.dataframe(pd.DataFrame(positions)[['epic', 'direction', 'profitAndLoss']], use_container_width=True)
            else:
                st.info("No open trades.")

        # --- MAIN EXECUTION LOOP ---
        if run_bot:
            status_box = st.empty()
            
            with status_box.status("⚡ AI is analyzing markets...", expanded=True) as status:
                
                # 1. Pick Target
                target = random.choice(WATCHLIST)
                status.write(f"Target Acquired: **{target}**")
                
                try:
                    # 2. Fetch Market Data
                    mkt = requests.get(f"{MARKETS_URL}/{target}", headers=headers).json()
                    
                    if 'snapshot' in mkt:
                        snap = mkt['snapshot']
                        price = snap.get('offer', snap.get('bid', 0))
                        change = snap.get('dailyChange', 0)
                        
                        status.write(f"Price: {price} | Volatility: {change}%")
                        
                        # 3. ASK GEMINI (With 429 Auto-Fix)
                        decision, raw_prompt, raw_resp = ask_gemini_robust(target, price, change)
                        
                        # Save for UI
                        st.session_state["last_prompt"] = raw_prompt
                        st.session_state["last_response"] = raw_resp
                        
                        action = decision.get('action', 'WAIT')
                        conf = decision.get('confidence', 0)
                        reason = decision.get('reason', '-')
                        
                        # 4. Update Logs
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        new_log = {
                            "Time": timestamp, 
                            "Asset": target, 
                            "Action": action, 
                            "Conf": f"{conf}%",
                            "Reason": reason
                        }
                        st.session_state["log_history"].insert(0, new_log)
                        if len(st.session_state["log_history"]) > 10: st.session_state["log_history"].pop()

                        # 5. Execute Trade
                        if action in ["BUY", "SELL"] and conf > 60:
                            if avail > 100: 
                                status.write(f"🚀 EXECUTING {action}!")
                                size = 0.01 if "BTC" in target else 1
                                execute_trade(headers, target, action, size)
                                st.toast(f"Trade Sent: {action} {target}")
                            else:
                                st.warning("Insufficient funds")
                        else:
                            status.write(f"Action: {action} (Confidence {conf}%)")

                except Exception as e:
                    status.write(f"Loop Error: {e}")
            
            # 6. WAIT FOR 1 MINUTE (With Countdown)
            # 60s is usually enough to clear the basic Flash Lite rate limit buffer
            for seconds_left in range(60, 0, -1):
                status_box.info(f"⏳ Cooling down... Next scan in: {seconds_left}s")
                time.sleep(1)
            
            st.rerun()

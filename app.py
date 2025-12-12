import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import pytz
import random
import json

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

# ⚠️ FORCE USING GEMINI 2.5 FLASH LITE ⚠️
# If this fails, check the "Available Models" in the sidebar
TARGET_MODEL_NAME = 'gemini-2.5-flash-lite' 

try:
    model = genai.GenerativeModel(TARGET_MODEL_NAME)
except Exception as e:
    st.error(f"Error init model: {e}")

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

def ask_gemini(epic, price, change):
    """
    Communicates with Gemini 2.5 Flash Lite.
    """
    # 1. Prompt Construction
    prompt = f"""
    You are a high-frequency trading algorithm using Gemini 2.5 Flash Lite.
    Current Market Data:
    - Asset: {epic}
    - Price: {price}
    - Daily Change: {change}%
    
    INSTRUCTIONS:
    1. Analyze the volatility.
    2. Output strictly JSON.
    3. Format: {{"action": "BUY" or "SELL" or "WAIT", "confidence": 0-100, "reason": "brief reason"}}
    """
    
    try:
        # 2. Generate Content
        response = model.generate_content(prompt)
        
        # 3. Parse
        raw_text = response.text
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        
        return json.loads(clean_json), prompt, raw_text
    except Exception as e:
        return {"action": "WAIT", "confidence": 0, "reason": f"AI Error: {str(e)}"}, prompt, str(e)

# --- DASHBOARD UI ---

st.title(f"⚡ {TARGET_MODEL_NAME} Auto-Trader")

# Sidebar Controls
with st.sidebar:
    st.header("Control Center")
    run_bot = st.toggle("ACTIVATE BOT", key="bot_active")
    
    st.divider()
    if st.button("Reconnect Capital.com"):
        st.session_state["headers"] = get_session()
        st.rerun()

    # DEBUG: Show available models to verify the name exists
    with st.expander("🔎 Check Available Models"):
        try:
            st.write("Models available to your API key:")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    st.code(m.name)
        except Exception as e:
            st.error(e)

# 1. Connect
headers = st.session_state["headers"]
if not headers:
    headers = get_session()
    st.session_state["headers"] = headers

if headers:
    acct = get_account_safe(headers)
    
    # Auth Check
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
            st.subheader("📡 Outgoing Prompt")
            st.code(st.session_state["last_prompt"], language="text")
            
        with c2:
            st.subheader(f"📥 {TARGET_MODEL_NAME} Response")
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
            with st.status("⚡ 2.5 Flash Lite is thinking...", expanded=True) as status:
                
                # 1. Pick Target
                target = random.choice(WATCHLIST)
                status.write(f"Scanning: **{target}**")
                
                try:
                    # 2. Fetch Market Data
                    mkt = requests.get(f"{MARKETS_URL}/{target}", headers=headers).json()
                    
                    if 'snapshot' in mkt:
                        snap = mkt['snapshot']
                        price = snap.get('offer', snap.get('bid', 0))
                        change = snap.get('dailyChange', 0)
                        
                        status.write(f"Price: ${price} | Change: {change}%")
                        
                        # 3. ASK GEMINI 2.5
                        decision, raw_prompt, raw_resp = ask_gemini(target, price, change)
                        
                        # Save for UI Display
                        st.session_state["last_prompt"] = raw_prompt
                        st.session_state["last_response"] = raw_resp
                        
                        action = decision.get('action', 'WAIT')
                        conf = decision.get('confidence', 0)
                        
                        # 4. Update Logs
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        new_log = {
                            "Time": timestamp, 
                            "Asset": target, 
                            "Action": action, 
                            "Conf": f"{conf}%",
                            "Reason": decision.get("reason", "-")
                        }
                        st.session_state["log_history"].insert(0, new_log)
                        if len(st.session_state["log_history"]) > 10:
                            st.session_state["log_history"].pop()

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
                            status.write("Confidence too low.")

                except Exception as e:
                    status.write(f"Error: {e}")
            
            time.sleep(1.5)
            st.rerun()

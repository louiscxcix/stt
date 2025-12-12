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
st.set_page_config(page_title="Chain-of-Thought Trader", layout="wide", page_icon="🔗")

# API ENDPOINTS (Demo)
BASE_URL = "https://demo-api-capital.backend-capital.com" 
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

WATCHLIST = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "US500", "TSLA", "AAPL"]

# --- SECRETS SETUP ---
try:
    CAP_API_KEY = st.secrets["capital_com"]["api_key"]
    CAP_EMAIL = st.secrets["capital_com"]["email"]
    CAP_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except:
    st.error("❌ Secrets missing. Check .streamlit/secrets.toml")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
TARGET_MODEL_NAME = 'gemini-2.5-flash-lite'
model = genai.GenerativeModel(TARGET_MODEL_NAME)

# --- STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "step1_log" not in st.session_state: st.session_state["step1_log"] = "System Ready. Waiting for start..."
if "step2_log" not in st.session_state: st.session_state["step2_log"] = "System Ready. Waiting for start..."
if "headers" not in st.session_state: st.session_state["headers"] = None

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

# --- THE 2-STEP AI LOGIC ---

def generate_strategy_prompt(epic):
    """
    Step 1: Ask AI to create a professional trading persona/strategy for this specific asset.
    """
    meta_prompt = f"""
    You are a hedge fund manager. 
    Create a 1-sentence, highly aggressive trading instruction for an analyst to evaluate {epic}.
    Focus on volatility and breakout potential.
    Example output: "Act as a momentum scalper and evaluate if BTCUSD is breaking resistance for a quick long."
    Output ONLY the instruction text.
    """
    try:
        response = model.generate_content(meta_prompt)
        return response.text.strip()
    except Exception as e:
        return f"Act as a scalper and evaluate {epic} for immediate volatility."

def analyze_market(strategy_instruction, price, change):
    """
    Step 2: Send the AI's own strategy back to it with data to get a decision.
    """
    final_prompt = f"""
    INSTRUCTION: {strategy_instruction}
    
    MARKET DATA:
    - Price: {price}
    - Daily Change: {change}%
    
    TASK:
    Follow the instruction above. You MUST make a decision.
    - If positive momentum: BUY
    - If negative momentum: SELL
    - ONLY WAIT if market is flat (0% change).
    
    RESPONSE FORMAT (JSON ONLY):
    {{
        "action": "BUY" or "SELL" or "WAIT",
        "confidence": 0-100,
        "reason": "Brief explanation"
    }}
    """
    
    # Retry logic for Quota (429)
    for _ in range(3):
        try:
            response = model.generate_content(final_prompt)
            text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(text), final_prompt, text
        except Exception as e:
            if "429" in str(e):
                time.sleep(10) # Wait for quota
                continue
            return {"action": "WAIT", "confidence": 0, "reason": str(e)}, final_prompt, str(e)
            
    return {"action": "WAIT"}, final_prompt, "Failed"

# --- UI LAYOUT ---

st.title(f"🔗 Chain-of-Thought AI Trader")

# Sidebar
with st.sidebar:
    st.header("Control")
    run_bot = st.toggle("ACTIVATE BOT", key="run_bot")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()
        st.rerun()

# Connect
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
        # 1. TOP METRICS
        equity = acct.get('equity', acct.get('balance', 0) + acct.get('profitLoss', 0))
        avail = acct.get('available', 0)
        positions = get_positions(headers)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Equity", f"${equity:,.0f}")
        m2.metric("Available", f"${avail:,.0f}")
        m3.metric("P&L", f"${acct.get('profitLoss', 0):,.2f}")
        m4.metric("Active Trades", len(positions))
        
        st.divider()

        # 2. ACTIVE TRADES (TOP PRIORITY)
        st.subheader("⚔️ Open Positions")
        if positions:
            df = pd.DataFrame(positions)
            st.dataframe(
                df[['epic', 'direction', 'dealSize', 'openPrice', 'profitAndLoss']], 
                use_container_width=True,
                column_config={"profitAndLoss": st.column_config.NumberColumn("P&L", format="$%.2f")}
            )
        else:
            st.info("No trades open. Waiting for AI trigger...")

        st.divider()

        # 3. AI CHAIN LOGS (Step 1 -> Step 2)
        with st.expander("🧠 Live AI Decision Chain (Click to View)", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Step 1: AI Generated Strategy**")
                st.info(st.session_state["step1_log"])
            with c2:
                st.markdown("**Step 2: AI Execution Decision**")
                st.success(st.session_state["step2_log"])
            
            if st.session_state["log_history"]:
                st.dataframe(pd.DataFrame(st.session_state["log_history"]), use_container_width=True)

        # 4. EXECUTION LOOP
        if run_bot:
            status_box = st.empty()
            with status_box.status("⚙️ AI Chain Running...", expanded=True) as status:
                
                # A. Select Asset
                target = random.choice(WATCHLIST)
                status.write(f"1. Selected Asset: **{target}**")
                
                try:
                    # B. Get Data
                    mkt = requests.get(f"{MARKETS_URL}/{target}", headers=headers).json()
                    
                    if 'snapshot' in mkt:
                        snap = mkt['snapshot']
                        price = snap.get('offer', snap.get('bid', 0))
                        change = snap.get('dailyChange', 0)
                        
                        # C. Step 1: Ask AI for Strategy
                        status.write("2. Asking AI for professional prompt...")
                        strategy_prompt = generate_strategy_prompt(target)
                        st.session_state["step1_log"] = strategy_prompt # Update UI
                        
                        # D. Step 2: Analyze using that Strategy
                        status.write("3. Analyzing market data...")
                        decision, prompt_sent, raw_resp = analyze_market(strategy_prompt, price, change)
                        
                        # Update UI Logs
                        action = decision.get('action', 'WAIT')
                        conf = decision.get('confidence', 0)
                        st.session_state["step2_log"] = f"Decision: {action} ({conf}%) | Reason: {decision.get('reason')}"
                        
                        # Add to History
                        new_log = {
                            "Time": datetime.now().strftime("%H:%M:%S"),
                            "Asset": target,
                            "Strategy": strategy_prompt[:50]+"...",
                            "Action": action,
                            "Conf": f"{conf}%"
                        }
                        st.session_state["log_history"].insert(0, new_log)
                        
                        # E. Execute
                        if action in ["BUY", "SELL"] and conf > 50:
                            if avail > 50:
                                status.write(f"🚀 EXECUTING {action}!")
                                size = 0.01 if "BTC" in target else 1
                                execute_trade(headers, target, action, size)
                                st.toast(f"✅ {action} {target} Executed!")
                            else:
                                st.error("Insufficient Funds")
                        else:
                            status.write("Confidence too low.")
                    
                except Exception as e:
                    status.write(f"Error: {e}")
            
            # F. Cooldown (60s to save quota)
            for s in range(60, 0, -1):
                status_box.info(f"⏳ Cycle Complete. Next scan in {s}s")
                time.sleep(1)
            st.rerun()

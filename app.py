import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
from datetime import datetime
import json
import random
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Capital.com AI Pipeline", layout="wide", page_icon="⚙️")

# API ENDPOINTS
BASE_URL = "https://demo-api-capital.backend-capital.com"
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# ROBUST PORTFOLIO (Mix of standard EPICS)
PORTFOLIO = [
    "BTCUSD", "ETHUSD", "XRPUSD",           # Crypto
    "EURUSD", "GBPUSD", "USDJPY",           # Forex
    "GOLD", "SILVER", "OIL_CRUDE",          # Commodities
    "US500", "US30", "DE40",                # Indices
    "TSLA", "AAPL", "AMZN", "MSFT"          # Stocks
]

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
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# --- STATE ---
if "logs" not in st.session_state: st.session_state["logs"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None

# --- HELPER FUNCTIONS ---

def log_event(event_type, message):
    """Adds an event to the UI log"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state["logs"].insert(0, {"Time": timestamp, "Type": event_type, "Message": message})

def clean_json(text):
    """Force cleans Gemini output into valid JSON"""
    try:
        # Remove markdown wrappers
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```", "", text)
        return json.loads(text.strip())
    except Exception as e:
        log_event("JSON ERROR", f"Could not parse AI response: {str(e)}")
        return []

# --- API CORE ---

def connect_capital():
    """Establishes session and returns headers"""
    headers = {"X-CAP-API-KEY": CAP_API_KEY, "Content-Type": "application/json"}
    data = {"identifier": CAP_EMAIL, "password": CAP_PASSWORD}
    
    try:
        r = requests.post(SESSION_URL, json=data, headers=headers)
        if r.status_code == 200:
            log_event("AUTH", "✅ Connected to Capital.com")
            return {
                "CST": r.headers["CST"],
                "X-SECURITY-TOKEN": r.headers["X-SECURITY-TOKEN"],
                "X-CAP-API-KEY": CAP_API_KEY,
                "Content-Type": "application/json"
            }
        else:
            log_event("AUTH ERROR", f"Status: {r.status_code} - {r.text}")
    except Exception as e:
        log_event("CONN ERROR", str(e))
    return None

def fetch_market_data(headers, assets):
    """Fetches prices for a list of assets"""
    results = []
    
    # Check headers first
    if not headers:
        log_event("DATA ERROR", "No headers provided. Please connect first.")
        return []

    for asset in assets:
        try:
            r = requests.get(f"{MARKETS_URL}/{asset}", headers=headers)
            if r.status_code == 200:
                d = r.json()
                if 'snapshot' in d:
                    results.append({
                        "symbol": asset,
                        "price": d['snapshot']['offer'],
                        "change": d['snapshot']['dailyChange']
                    })
            elif r.status_code == 401:
                log_event("AUTH ERROR", "Token Expired. Please Reconnect.")
                return [] # Stop if unauthorized
            else:
                # Log minor errors (like Market Closed) but don't stop
                pass 
        except Exception as e:
            log_event("FETCH ERROR", f"Failed {asset}: {str(e)}")
            
    if not results:
        log_event("DATA WARNING", "Fetched 0 assets. Markets might be closed or API Changed.")
        
    return results

def execute_trade(headers, epic, direction, size):
    """Executes a trade order"""
    payload = {
        "epic": epic,
        "direction": direction,
        "size": size,
        "guaranteedStop": False,
        "trailingStop": False
    }
    try:
        r = requests.post(POSITIONS_URL, json=payload, headers=headers)
        if r.status_code == 200:
            log_event("EXECUTION", f"✅ {direction} {epic} Success!")
            return True
        else:
            err = r.json()
            code = err.get('errorCode', 'Unknown')
            log_event("EXECUTION FAIL", f"❌ {epic}: {code}")
            return False
    except Exception as e:
        log_event("EXECUTION ERROR", str(e))
        return False

# --- AI LOGIC ---

def get_ai_plan(invest_amount, market_data):
    """Phase 1: Get the Plan"""
    if not market_data:
        return []
        
    data_str = json.dumps(market_data, indent=2)
    prompt = f"""
    You are a Hedge Fund Algorithm.
    Capital Available: ${invest_amount}
    Market Data: {data_str}
    
    TASK:
    1. Identify the Top 3 assets with the best momentum.
    2. Create an allocation plan.
    3. Be aggressive.
    
    OUTPUT JSON ONLY:
    [
        {{"asset": "BTCUSD", "direction": "BUY", "reason": "Breakout"}},
        {{"asset": "GOLD", "direction": "SELL", "reason": "Resistance"}}
    ]
    """
    try:
        resp = model.generate_content(prompt)
        return clean_json(resp.text)
    except Exception as e:
        log_event("AI ERROR", str(e))
        return []

# --- UI ---

st.title("⚙️ Transparent AI Pipeline")

# Sidebar - Diagnostics
with st.sidebar:
    st.header("1. Diagnostics")
    if st.button("🔌 Test Connection"):
        st.session_state["headers"] = connect_capital()
        
    if st.button("📊 Test Market Data"):
        if st.session_state["headers"]:
            test_data = fetch_market_data(st.session_state["headers"], ["BTCUSD", "EURUSD"])
            st.write(test_data)
            if test_data:
                st.success(f"Fetched {len(test_data)} assets successfully.")
            else:
                st.error("Fetch failed. Check Logs.")
        else:
            st.error("Connect first.")

    st.divider()
    st.header("3. System Logs")
    if st.session_state["logs"]:
        for l in st.session_state["logs"][:10]:
            st.text(f"{l['Time']} [{l['Type']}]")
            st.caption(l['Message'])

# Main Area
headers = st.session_state["headers"]
account = None

if headers:
    # Get Account Info safely
    try:
        acc_req = requests.get(ACCOUNTS_URL, headers=headers)
        if acc_req.status_code == 200:
            account = acc_req.json()['accounts'][0]['balance']
        else:
            st.error("Session Invalid. Please click 'Test Connection' again.")
    except: pass

if account:
    # METRICS
    c1, c2, c3 = st.columns(3)
    c1.metric("Equity", f"${account.get('equity', 0):,.2f}")
    c2.metric("Available", f"${account.get('available', 0):,.2f}")
    c3.metric("P&L", f"${account.get('profitLoss', 0):,.2f}", delta_color="normal")
    
    st.divider()
    
    # 2. PORTFOLIO BUILDER
    st.subheader("🚀 AI Portfolio Builder")
    
    with st.form("builder"):
        amount = st.number_input("Capital to Deploy ($)", 100, 10000, 1000)
        go_btn = st.form_submit_button("Generate Plan & Execute")
        
        if go_btn:
            # STEP A: FETCH
            status = st.status("1. Fetching Market Data...", expanded=True)
            batch = random.sample(PORTFOLIO, 8)
            market_data = fetch_market_data(headers, batch)
            
            if market_data:
                status.write(f"✅ Fetched {len(market_data)} assets.")
                
                # STEP B: AI PLAN
                status.write("2. Sending to Gemini AI...")
                plan = get_ai_plan(amount, market_data)
                
                if plan:
                    status.write("✅ AI Blueprint Created:")
                    st.table(pd.DataFrame(plan))
                    
                    # STEP C: EXECUTE
                    status.write("3. Executing Orders...")
                    for item in plan:
                        asset = item.get('asset')
                        direction = item.get('direction')
                        
                        # Size logic (Demo Safe)
                        size = 0.01 if "BTC" in asset or "ETH" in asset else 1.0
                        
                        success = execute_trade(headers, asset, direction, size)
                        if success:
                            st.toast(f"Bought {asset}")
                        time.sleep(0.5)
                        
                    status.update(label="Process Complete!", state="complete", expanded=False)
                    time.sleep(1)
                    st.rerun()
                else:
                    status.update(label="AI Failed to Generate Plan", state="error")
            else:
                status.update(label="Market Data Fetch Failed", state="error")

    # 3. OPEN POSITIONS
    st.subheader("Open Positions")
    try:
        pos_req = requests.get(POSITIONS_URL, headers=headers)
        if pos_req.status_code == 200:
            positions = pos_req.json()['positions']
            if positions:
                # Clean Data for Display
                clean_p = []
                for p in positions:
                    clean_p.append({
                        "Symbol": p['epic'],
                        "Direction": p['direction'],
                        "Size": p['dealSize'],
                        "P&L": p['profitAndLoss']
                    })
                st.dataframe(pd.DataFrame(clean_p), use_container_width=True)
            else:
                st.info("No open trades.")
    except:
        st.error("Could not load positions.")

else:
    st.info("👈 Please click **'Test Connection'** in the sidebar to start.")

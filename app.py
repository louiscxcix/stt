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
st.set_page_config(page_title="AI Portfolio Architect", layout="wide", page_icon="🏗️")

# API ENDPOINTS
BASE_URL = "[https://demo-api-capital.backend-capital.com](https://demo-api-capital.backend-capital.com)" 
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKETS_URL = f"{BASE_URL}/api/v1/markets"

# MASSIVE WATCHLIST
PORTFOLIO = [
    "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "DOGEUSD", # Crypto
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",  # Forex
    "GOLD", "SILVER", "OIL_CRUDE", "NATURAL_GAS",      # Commodities
    "US500", "US30", "DE40", "JP225", "FR40",          # Indices
    "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "META"     # Stocks
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
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# --- STATE ---
if "log_history" not in st.session_state: st.session_state["log_history"] = []
if "headers" not in st.session_state: st.session_state["headers"] = None
if "last_plan_debug" not in st.session_state: st.session_state["last_plan_debug"] = "Waiting..."

# --- HELPER: JSON CLEANER ---
def clean_and_parse_json(raw_text):
    """
    Robustly cleans AI response to ensure valid JSON.
    """
    try:
        # 1. Remove Markdown code blocks
        text = re.sub(r"```json\s*", "", raw_text)
        text = re.sub(r"```", "", text)
        text = text.strip()
        
        # 2. Try parse
        return json.loads(text)
    except json.JSONDecodeError:
        # 3. If fail, return empty list and log error
        st.session_state["last_plan_debug"] = f"JSON PARSE ERROR:\n{raw_text}"
        return []

# --- API FUNCTIONS ---

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
    return requests.post(POSITIONS_URL, json=payload, headers=headers)

def close_position(headers, deal_id):
    return requests.delete(f"{POSITIONS_URL}/{deal_id}", headers=headers)

def fetch_market_batch(headers, assets):
    batch_data = []
    for asset in assets:
        try:
            resp = requests.get(f"{MARKETS_URL}/{asset}", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if 'snapshot' in data:
                    s = data['snapshot']
                    batch_data.append({
                        "symbol": asset,
                        "price": s.get('offer', 0),
                        "change": s.get('dailyChange', 0)
                    })
        except: pass
    return batch_data

# --- AI LOGIC ---

def ai_smart_allocate(total_funds, market_data):
    # Simplified data for AI context
    data_str = json.dumps(market_data, indent=2)
    
    prompt = f"""
    You are a Portfolio Manager. 
    Funds: ${total_funds}.
    Market Data: {data_str}
    
    TASK:
    1. Identify the 3 best assets based on momentum.
    2. Create a diversified allocation plan.
    3. Return strictly valid JSON.
    
    EXAMPLE RESPONSE:
    [
        {{"asset": "BTCUSD", "direction": "BUY", "usd_amount": 300, "reason": "High Volatility"}},
        {{"asset": "GOLD", "direction": "SELL", "usd_amount": 200, "reason": "Dropping"}}
    ]
    """
    try:
        response = model.generate_content(prompt)
        # Store raw text for debugging if it fails
        st.session_state["last_plan_debug"] = response.text 
        return clean_and_parse_json(response.text)
    except Exception as e:
        st.session_state["last_plan_debug"] = str(e)
        return []

def analyze_portfolio_aggressive(market_data_list):
    data_str = json.dumps(market_data_list, indent=2)
    prompt = f"""
    Role: High-Frequency Scalper.
    Data: {data_str}
    Task: Pick 3 trades. Ignore safety.
    Return JSON: [{{"asset": "BTCUSD", "action": "BUY", "confidence": 90, "reason": "Pump"}}, ...]
    """
    try:
        response = model.generate_content(prompt)
        return clean_and_parse_json(response.text)
    except: return []

def manage_positions_ai(positions_data):
    if not positions_data: return []
    
    # Safe summary builder
    summary = []
    for p in positions_data:
        summary.append({
            "id": p.get('dealId'), 
            "asset": p.get('epic'), 
            "pnl": p.get('profitAndLoss')
        })

    data_str = json.dumps(summary, indent=2)
    prompt = f"""
    Risk Manager. 
    Positions: {data_str}.
    
    Rules:
    - CLOSE if PnL > 1.0 (Take Profit).
    - CLOSE if PnL < -5.0 (Stop Loss).
    - Otherwise HOLD.
    
    Return JSON: [{{"id": "123", "action": "CLOSE", "reason": "TP"}}, ...]
    """
    try:
        response = model.generate_content(prompt)
        return clean_and_parse_json(response.text)
    except: return []

# --- UI LAYOUT ---

st.title(f"🏗️ AI Portfolio Architect")

# Headers Init
headers = st.session_state["headers"]
if not headers:
    headers = get_session()
    st.session_state["headers"] = headers

# --- SIDEBAR ---
with st.sidebar:
    st.header("🧠 Smart Allocate")
    with st.form("smart_alloc_form"):
        invest_amount = st.number_input("Invest Amount ($)", 100, 10000, 1000)
        alloc_btn = st.form_submit_button("🚀 Build Portfolio")
        
        if alloc_btn and headers:
            st.info("Scanning...")
            batch = random.sample(PORTFOLIO, 10)
            mkt_data = fetch_market_batch(headers, batch)
            
            if mkt_data:
                plan = ai_smart_allocate(invest_amount, mkt_data)
                
                if plan:
                    st.success(f"Executing {len(plan)} trades!")
                    for item in plan:
                        asset = item.get('asset')
                        direction = item.get('direction')
                        usd = item.get('usd_amount')
                        
                        # Dynamic Sizing (Approximate)
                        size = 0.02 if "BTC" in asset else 1.0
                        
                        res = execute_trade(headers, asset, direction, size)
                        if res.status_code == 200:
                            st.toast(f"✅ Bought ${usd} of {asset}")
                        else:
                            st.error(f"Failed {asset}: {res.text}")
                        time.sleep(0.3)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("AI returned invalid plan.")
                    with st.expander("See Raw AI Error"):
                        st.code(st.session_state["last_plan_debug"])
            else:
                st.error("Could not fetch market data.")

    st.divider()
    st.header("🤖 Auto-Scalper")
    run_bot = st.toggle("ACTIVATE SCALPER", key="run_bot")
    if st.button("Reconnect"):
        st.session_state["headers"] = get_session()
        st.rerun()

# --- MAIN DASHBOARD ---
if headers:
    acct = get_account_safe(headers)
    
    # Auto-Reauth
    if acct == "UNAUTHORIZED":
        st.session_state["headers"] = get_session()
        st.rerun()

    if acct:
        # 1. METRICS
        equity = acct.get('equity', 0)
        avail = acct.get('available', 0)
        pnl = acct.get('profitLoss', 0)
        positions = get_positions(headers)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Equity", f"${equity:,.0f}")
        m2.metric("Available", f"${avail:,.0f}")
        m3.metric("P&L", f"${pnl:,.2f}", delta=pnl)
        m4.metric("Open Trades", len(positions))
        
        st.divider()

        # 2. ACTIVE POSITIONS (MANUAL BUILD - NO CRASH)
        st.subheader("⚔️ Active Positions")
        if positions:
            # We build the list manually to ensure keys exist
            clean_positions = []
            for p in positions:
                clean_positions.append({
                    "Symbol": p.get('epic', 'Unknown'),
                    "Direction": p.get('direction', '-'),
                    "Size": p.get('dealSize', 0),
                    "Entry": p.get('openPrice', 0),
                    "P&L": p.get('profitAndLoss', 0)
                })
            
            df = pd.DataFrame(clean_positions)
            st.dataframe(
                df, 
                use_container_width=True,
                column_config={
                    "P&L": st.column_config.NumberColumn("P&L", format="$%.2f")
                }
            )
        else:
            st.info("No trades currently open.")

        # 3. LOGS
        with st.expander("📜 Live Action Log", expanded=True):
            if st.session_state["log_history"]:
                st.dataframe(pd.DataFrame(st.session_state["log_history"]), use_container_width=True, hide_index=True)
            else:
                st.caption("Log empty...")

        # --- EXECUTION LOOP ---
        if run_bot:
            status_box = st.empty()
            
            # A. Manage Risk
            if positions:
                with status_box.status("🛡️ Managing Risk...", expanded=True) as status:
                    decisions = manage_positions_ai(positions)
                    if decisions:
                        for dec in decisions:
                            if dec.get('action') == "CLOSE":
                                deal_id = dec.get('id')
                                close_position(headers, deal_id)
                                st.toast(f"💰 Closed Trade {deal_id}")
                                st.session_state["log_history"].insert(0, {"Time": datetime.now().strftime("%H:%M:%S"), "Action": "CLOSE", "Reason": dec.get('reason')})
                    status.write("Risk Check Complete.")

            # B. Hunt Trades
            batch = random.sample(PORTFOLIO, 10)
            with status_box.status(f"⚡ Scalping 10 Assets...", expanded=True) as status:
                market_data = fetch_market_batch(headers, batch)
                if market_data:
                    decisions = analyze_portfolio_aggressive(market_data)
                    if decisions:
                        status.write(f"AI found {len(decisions)} trades!")
                        for dec in decisions:
                            asset = dec.get('asset')
                            action = dec.get('action')
                            conf = dec.get('confidence', 0)
                            
                            if action in ["BUY", "SELL"] and conf > 40:
                                if avail > 100:
                                    size = 0.02 if "BTC" in asset else 1.0
                                    execute_trade(headers, asset, action, size)
                                    st.toast(f"💣 {action} {asset}")
                                    st.session_state["log_history"].insert(0, {
                                        "Time": datetime.now().strftime("%H:%M:%S"),
                                        "Action": action,
                                        "Asset": asset,
                                        "Reason": dec.get('reason')
                                    })
                                    time.sleep(0.3)
                    
                    if len(st.session_state["log_history"]) > 20: 
                        st.session_state["log_history"] = st.session_state["log_history"][:20]

            # C. Cooldown
            for s in range(30, 0, -1):
                status_box.info(f"🔥 reloading... {s}s")
                time.sleep(1)
            
            st.rerun()

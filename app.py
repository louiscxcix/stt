import streamlit as st
import requests
import pandas as pd
import google.generativeai as genai
import time
import json

# --- CONFIGURATION & SETUP ---
st.set_page_config(page_title="Aggressive Auto-Trader", layout="wide")

# 1. API CONFIGURATION (Load from st.secrets)
try:
    CAPITAL_API_KEY = st.secrets["capital_com"]["api_key"]
    CAPITAL_EMAIL = st.secrets["capital_com"]["email"]
    CAPITAL_PASSWORD = st.secrets["capital_com"]["password"]
    GEMINI_API_KEY = st.secrets["gemini"]["GEMINI_API_KEY"]
except FileNotFoundError:
    st.error("Secrets file not found. Please set up .streamlit/secrets.toml")
    st.stop()

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# Capital.com API Endpoints (Using DEMO for safety - Change to 'api-capital' for live)
# BASE_URL = "https://api-capital.backend-capital.com" # LIVE
BASE_URL = "https://demo-api-capital.backend-capital.com" # DEMO
SESSION_URL = f"{BASE_URL}/api/v1/session"
ACCOUNTS_URL = f"{BASE_URL}/api/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/api/v1/positions"
MARKET_URL = f"{BASE_URL}/api/v1/markets"

# --- HELPER FUNCTIONS ---

def get_capital_session():
    """Authenticates and returns session headers (CST, X-SECURITY-TOKEN)."""
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "identifier": CAPITAL_EMAIL,
        "password": CAPITAL_PASSWORD
    }
    
    try:
        response = requests.post(SESSION_URL, json=data, headers=headers)
        if response.status_code == 200:
            cst = response.headers.get("CST")
            x_sec = response.headers.get("X-SECURITY-TOKEN")
            return {"CST": cst, "X-SECURITY-TOKEN": x_sec}
        else:
            st.error(f"Login Failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

def get_account_data(auth_headers):
    """Fetches equity, margin, and available funds."""
    response = requests.get(ACCOUNTS_URL, headers=auth_headers)
    if response.status_code == 200:
        return response.json()
    return None

def get_open_positions(auth_headers):
    """Fetches current open trades."""
    response = requests.get(POSITIONS_URL, headers=auth_headers)
    if response.status_code == 200:
        return response.json()['positions']
    return []

def get_market_price(auth_headers, epic="BTCUSD"):
    """Fetches current price for a target asset (e.g., Bitcoin)."""
    # Note: Using a specific epic for micro-trading example
    url = f"{MARKET_URL}/{epic}"
    response = requests.get(url, headers=auth_headers)
    if response.status_code == 200:
        return response.json()
    return None

def ai_strategy_decision(market_data, account_data, positions):
    """
    Aggressive Strategy: Uses Gemini to decide BUY/SELL/HOLD based on data.
    """
    
    # Construct a prompt for Gemini
    current_equity = account_data['accounts'][0]['balance']['equity']
    available_funds = account_data['accounts'][0]['balance']['available']
    
    prompt = f"""
    You are a high-frequency, aggressive trading bot. 
    Goal: Maximize profit using up to 80% of available funds.
    
    Context:
    - Asset: {market_data.get('instrument', {}).get('name', 'Unknown')}
    - Current Bid: {market_data.get('snapshot', {}).get('bid')}
    - Current Ask: {market_data.get('snapshot', {}).get('offer')}
    - Price Change %: {market_data.get('snapshot', {}).get('dailyChange')}
    - Total Equity: {current_equity}
    - Available Funds: {available_funds}
    - Current Open Positions Count: {len(positions)}
    
    Task:
    Analyze the data. If the price direction looks strong, recommend an aggressive entry.
    If we are losing money on open positions, recommend a quick close.
    
    Response Format (JSON only):
    {{
        "decision": "BUY" or "SELL" or "HOLD" or "CLOSE_ALL",
        "reasoning": "Short explanation (max 1 sentence)",
        "confidence": "0-100"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        # Clean up code blocks if Gemini adds them
        text = response.text.replace('```json', '').replace('```', '')
        return json.loads(text)
    except Exception as e:
        return {"decision": "HOLD", "reasoning": f"AI Error: {e}", "confidence": 0}

# --- MAIN UI LAYOUT ---

st.title("🤖 AI Algo-Trader (Capital.com)")

# Sidebar for controls
with st.sidebar:
    st.header("Settings")
    target_asset = st.text_input("Target Asset (Epic)", "BTCUSD")
    trade_mode = st.radio("Trading Mode", ["Paper (Simulation)", "Live (DANGEROUS)"])
    if trade_mode == "Live (DANGEROUS)":
        st.warning("You are in LIVE mode. Real money will be used.")
    
    if st.button("Connect & Refresh"):
        st.session_state['refresh'] = True

# Main Logic
if 'auth_headers' not in st.session_state:
    with st.spinner("Authenticating with Capital.com..."):
        headers = get_capital_session()
        if headers:
            st.session_state['auth_headers'] = headers
            st.success("Connected!")
        else:
            st.stop()

headers = st.session_state['auth_headers']

# 1. Dashboard (Top)
col1, col2, col3, col4 = st.columns(4)
acct_raw = get_account_data(headers)

if acct_raw:
    acct = acct_raw['accounts'][0]['balance']
    col1.metric("Equity", f"${acct['equity']:.2f}")
    col2.metric("Available Margin", f"${acct['available']:.2f}")
    col3.metric("Total P&L", f"${acct['profitLoss']:.2f}", delta_color="normal")
    col4.metric("Used Margin", f"{acct['margin']:.2f}")

    st.markdown("---")

    # 2. AI & Market Data
    market_raw = get_market_price(headers, target_asset)
    positions = get_open_positions(headers)
    
    col_ai, col_mkt = st.columns([2, 1])
    
    with col_mkt:
        st.subheader("Market Data")
        if market_raw:
            snapshot = market_raw.get('snapshot', {})
            st.write(f"**Asset:** {target_asset}")
            st.write(f"**Bid:** {snapshot.get('bid')}")
            st.write(f"**Ask:** {snapshot.get('offer')}")
            st.write(f"**Change:** {snapshot.get('dailyChange')}%")
        else:
            st.error("Market closed or invalid Epic.")

    with col_ai:
        st.subheader("AI Strategy Log")
        if st.button("RUN AI ANALYSIS NOW"):
            with st.spinner("Gemini is analyzing market structure..."):
                decision = ai_strategy_decision(market_raw, acct_raw, positions)
                
                st.info(f"**Decision:** {decision['decision']}")
                st.write(f"**Reasoning:** {decision['reasoning']}")
                st.progress(int(decision['confidence']))
                
                # EXECUTION LOGIC (Stubbed for safety)
                if decision['decision'] in ["BUY", "SELL"] and int(decision['confidence']) > 70:
                    st.write(f"🚀 **Action Triggered:** Attempting to {decision['decision']} {target_asset}")
                    if trade_mode == "Live (DANGEROUS)":
                        # Actual API call to place trade would go here
                        # requests.post(f"{BASE_URL}/api/v1/positions", ...)
                        st.error("Live execution paused for safety in this template.")
                    else:
                        st.success("Paper Trade Simulated Successfully.")

    st.markdown("---")

    # 3. Open Positions Table
    st.subheader("Aggressive Positions (Open)")
    if positions:
        df = pd.DataFrame(positions)
        # Select relevant columns for display
        display_df = df[['dealId', 'epic', 'direction', 'openPrice', 'size', 'profitAndLoss']]
        st.dataframe(display_df, use_container_width=True)
    else:
        st.write("No open positions. AI is waiting for entry.")

else:
    st.error("Failed to fetch account data. Please check your token expiration.")

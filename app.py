import streamlit as st
import requests
import base64
import time
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai
from datetime import datetime, timedelta
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

# ==========================================
# 1. CORE API CLIENT (Capital.com)
# ==========================================
class CapitalClient:
    def __init__(self):
        # Load Secrets
        try:
            self.cap_key = st.secrets["capital_com"]["api_key"]
            self.login = st.secrets["capital_com"]["email"]
            self.password = st.secrets["capital_com"]["password"]
            
            # Setup Gemini
            genai.configure(api_key=st.secrets["gemini"]["api_key"])
            self.model = genai.GenerativeModel('gemini-pro')
            
        except Exception:
            st.error("❌ Secrets missing! Add [capital_com] and [gemini] to secrets.toml")
            st.stop()
        
        self.base_url = "https://demo-api-capital.backend-capital.com" # Change to LIVE for real money
        self.session = requests.Session()
        self.cst = None
        self.x_security = None

    # --- AUTHENTICATION ---
    def _encrypt_password(self, key_b64, timestamp):
        input_str = f"{self.password}|{timestamp}"
        input_bytes = base64.b64encode(input_str.encode('utf-8'))
        key_bytes = base64.b64decode(key_b64)
        public_key = RSA.import_key(key_bytes)
        cipher = PKCS1_v1_5.new(public_key)
        encrypted = cipher.encrypt(input_bytes)
        return base64.b64encode(encrypted).decode('utf-8')

    def connect(self):
        try:
            # 1. Get Key
            r = self.session.get(f"{self.base_url}/api/v1/session/encryptionKey", headers={'X-CAP-API-KEY': self.cap_key})
            r.raise_for_status()
            data = r.json()
            
            # 2. Encrypt & Login
            pw = self._encrypt_password(data['encryptionKey'], int(data['timeStamp']))
            payload = {"identifier": self.login, "password": pw, "encryptedPassword": True}
            
            r = self.session.post(f"{self.base_url}/api/v1/session", json=payload, headers={'X-CAP-API-KEY': self.cap_key, 'Content-Type': 'application/json'})
            
            if r.status_code == 200:
                self.cst = r.headers.get('CST')
                self.x_security = r.headers.get('X-SECURITY-TOKEN')
                return True
            return False
        except Exception as e:
            st.error(f"Login Error: {e}")
            return False

    # --- DATA FETCHING ---
    def get_market_data(self, epic="ETHUSD"):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        
        # Get Price
        price = 0
        try:
            r = self.session.get(f"{self.base_url}/api/v1/markets/{epic}", headers=headers)
            if r.status_code == 200: price = r.json()['snapshot']['offer']
        except: pass

        # Get Account
        account = {}
        try:
            r = self.session.get(f"{self.base_url}/api/v1/accounts", headers=headers)
            if r.status_code == 200: account = r.json()['accounts'][0]['balance']
        except: pass
        
        # Get Positions
        positions = []
        try:
            r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
            if r.status_code == 200: positions = r.json()['positions']
        except: pass

        # Get Candles (History for AI)
        candles = []
        try:
            r = self.session.get(f"{self.base_url}/api/v1/prices/{epic}?resolution=MINUTE&max=15", headers=headers)
            if r.status_code == 200: 
                raw = r.json()['prices']
                for c in raw:
                    candles.append(c['closePrice']['bid'])
        except: pass

        return price, account, positions, candles

    # --- TRADING ACTIONS ---
    def place_order(self, epic, side, size, leverage=10):
        # NOTE: Capital.com sets leverage on the ACCOUNT level per asset, usually not per API call.
        # We calculate size based on the leverage we assume is active.
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security, 'Content-Type': 'application/json'}
        
        payload = {
            "epic": epic,
            "direction": side, # "BUY" or "SELL"
            "size": size
        }
        r = self.session.post(f"{self.base_url}/api/v1/positions", json=payload, headers=headers)
        return r.status_code == 200, r.text

    def close_all(self):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        # 1. Close Positions
        r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
        if r.status_code == 200:
            for p in r.json()['positions']:
                self.session.delete(f"{self.base_url}/api/v1/positions/{p['dealId']}", headers=headers)
        return "Positions Closed"

# ==========================================
# 2. AI STRATEGY ENGINE (Gemini)
# ==========================================
def ask_gemini_for_decision(bot, current_price, candles, equity, available):
    """
    Sends market data to Gemini and asks for a trading decision based on the 50/30/20 rule.
    """
    
    # 1. Construct the Prompt
    trend_str = " -> ".join([str(c) for c in candles[-10:]]) # Last 10 mins trend
    
    prompt = f"""
    You are a professional Crypto Trading Agent. 
    Current Asset: ETH/USD. Current Price: {current_price}.
    Recent 10m Trend (Close Prices): {trend_str}
    
    My Portfolio Rules:
    1. Total Equity: {equity:.2f}
    2. Available Cash: {available:.2f}
    3. Strategy: 
       - 20% MUST remain cash (Safety Reserve).
       - 50% Allocation for Strong Trends.
       - 30% Allocation for Micro-Fluctuations (High Leverage).
    
    Task:
    Analyze the trend. 
    - If price is rising consistently, signal BUY.
    - If price is falling consistently, signal SELL.
    - If flat or available cash is near the 20% limit ({equity*0.2:.2f}), signal HOLD.
    
    Output ONLY one word: BUY, SELL, or HOLD.
    """
    
    try:
        response = bot.model.generate_content(prompt)
        decision = response.text.strip().upper()
        # Sanitize output
        if "BUY" in decision: return "BUY"
        if "SELL" in decision: return "SELL"
        return "HOLD"
    except Exception as e:
        return "HOLD" # Safety default

# ==========================================
# 3. STREAMLIT APP
# ==========================================
def main():
    st.set_page_config(page_title="Gemini AI Trader", page_icon="🤖", layout="wide")
    
    # --- CSS for Professional Look ---
    st.markdown("""
        <style>
        .metric-box {
            background-color: #0E1117;
            border: 1px solid #262730;
            padding: 15px;
            border-radius: 5px;
            text-align: center;
        }
        .big-font { font-size: 24px; font-weight: bold; }
        .green { color: #00FF00; }
        .red { color: #FF0000; }
        </style>
    """, unsafe_allow_html=True)

    # --- STATE INIT ---
    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalClient()
        st.session_state.connected = False
        st.session_state.active = False
        st.session_state.last_ai_check = datetime.now() - timedelta(minutes=5)
        st.session_state.ai_decision = "WAITING"
        st.session_state.midnight_mode = False

    bot = st.session_state.bot

    # --- SIDEBAR ---
    with st.sidebar:
        st.header("🤖 AI Controls")
        if not st.session_state.connected:
            if st.button("🔌 Connect APIs", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("Systems Online")
            
            st.divider()
            st.subheader("Strategy Config")
            leverage = st.number_input("Target Leverage", value=10)
            base_invest = st.number_input("Base Trade Size ($)", value=100)
            
            st.divider()
            col1, col2 = st.columns(2)
            if st.session_state.active:
                if col1.button("🛑 STOP"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if col1.button("▶️ START"):
                    st.session_state.active = True
                    st.rerun()
            
            if col2.button("⚠️ CLOSE ALL"):
                bot.close_all()
                st.toast("Panic Close Triggered!")

    # --- MAIN UI ---
    st.title("🤖 Gemini AI Hedge Fund Agent")
    
    if not st.session_state.connected:
        st.info("Please connect via the sidebar to start the feed.")
        st.stop()

    # --- PLACEHOLDERS ---
    # We use placeholders to update specific parts of the UI without full reloads
    header_ph = st.empty()
    chart_ph = st.empty()
    log_ph = st.empty()
    table_ph = st.empty()

    # --- MAIN LOOP ---
    while True:
        # 1. Fetch Data (Real-time)
        price, account, positions, candles = bot.get_market_data("ETHUSD")
        
        # 2. Extract Metrics
        equity = account.get('equity', 0)
        available = account.get('available', 0)
        margin_used = account.get('margin', 0)
        pl = account.get('profitLoss', 0)
        
        # 3. Calculate 20% Reserve Logic
        cash_reserve_limit = equity * 0.20
        is_reserve_danger = available < cash_reserve_limit

        # 4. Midnight Logic (Barcelona Time handling manually or just use System Time)
        now = datetime.now()
        is_midnight = now.hour == 23 and now.minute == 59
        
        if is_midnight and not st.session_state.midnight_mode:
            st.session_state.midnight_mode = True
            st.toast("🌙 Midnight Protocol: Closing Trades...", icon="🌑")
            bot.close_all()
            st.session_state.active = False # Pause execution
        
        if st.session_state.midnight_mode and now.hour == 0 and now.minute == 5:
            st.session_state.midnight_mode = False
            st.session_state.active = True
            st.toast("☀️ Morning Protocol: Resuming Strategy", icon="🌅")

        # 5. AI Decision Loop (Every 1 Minute)
        time_since_last = (now - st.session_state.last_ai_check).total_seconds()
        
        if st.session_state.active and not is_reserve_danger and time_since_last > 60:
            # Ask Gemini
            decision = ask_gemini_for_decision(bot, price, candles, equity, available)
            st.session_state.ai_decision = decision
            st.session_state.last_ai_check = now
            
            # Execute Decision
            if decision == "BUY":
                # Calc size: (Investment * Leverage) / Price
                size = round((base_invest * leverage) / price, 2)
                bot.place_order("ETHUSD", "BUY", size)
                st.toast(f"🤖 AI Bought {size} ETH", icon="📈")
            
            elif decision == "SELL":
                # For CFD, SELL means Short. If we just want to close, we'd use close logic.
                # Here we assume aggressive 30% fluctuation capture -> Opening Short
                size = round((base_invest * leverage) / price, 2)
                bot.place_order("ETHUSD", "SELL", size)
                st.toast(f"🤖 AI Shorted {size} ETH", icon="📉")

        # --- UI UPDATES ---
        
        # A. Header Metrics
        with header_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity (Total)", f"€{equity:,.2f}")
            
            # Color Available Funds Red if near 20% limit
            avail_color = "inverse" if is_reserve_danger else "normal"
            c2.metric("Available (Free)", f"€{available:,.2f}", delta=f"Reserve Limit: €{cash_reserve_limit:.0f}", delta_color=avail_color)
            
            c3.metric("Used Margin (Active)", f"€{margin_used:,.2f}")
            c4.metric("Total P/L", f"€{pl:,.2f}", delta=pl)

        # B. Status & Log
        with log_ph.container():
            s1, s2 = st.columns([1, 3])
            status_text = "RUNNING" if st.session_state.active else "PAUSED"
            if st.session_state.midnight_mode: status_text = "MIDNIGHT RESET"
            
            s1.info(f"**Bot Status:** {status_text}")
            s2.success(f"🤖 **Gemini Analysis:** {st.session_state.ai_decision} | Last Check: {st.session_state.last_ai_check.strftime('%H:%M:%S')}")

        # C. Active Trade Table
        trade_data = []
        for p in positions:
            trade_data.append({
                "Asset": p.get('epic'),
                "Side": p.get('direction'),
                "Size": p.get('size'),
                "Entry": p.get('openPrice'),
                "Live P/L": f"€{p.get('profitAndLoss'):.2f}"
            })
        
        if trade_data:
            table_ph.dataframe(pd.DataFrame(trade_data), use_container_width=True)
        else:
            table_ph.caption("No Active Positions")

        # Refresh Rate
        time.sleep(1)

if __name__ == "__main__":
    main()

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
        # --- SECRETS MANAGEMENT ---
        try:
            # Capital.com Credentials
            self.cap_key = st.secrets["capital_com"]["api_key"]
            self.login = st.secrets["capital_com"]["email"]
            self.password = st.secrets["capital_com"]["password"]
            
            # Google Gemini Credentials
            genai.configure(api_key=st.secrets["gemini"]["api_key"])
            self.model = genai.GenerativeModel('gemini-pro')
            
        except Exception as e:
            st.error(f"❌ Secret Error: {e}")
            st.info("Ensure .streamlit/secrets.toml has [capital_com] and [gemini] sections.")
            st.stop()
        
        # Base Configuration
        self.base_url = "https://demo-api-capital.backend-capital.com" # Switch to LIVE url for real money
        self.session = requests.Session()
        self.cst = None
        self.x_security = None

    # --- ENCRYPTION & LOGIN ---
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
            # 1. Fetch Encryption Key
            r = self.session.get(f"{self.base_url}/api/v1/session/encryptionKey", headers={'X-CAP-API-KEY': self.cap_key})
            r.raise_for_status()
            data = r.json()
            
            # 2. Encrypt Password
            pw = self._encrypt_password(data['encryptionKey'], int(data['timeStamp']))
            
            # 3. Create Session
            payload = {"identifier": self.login, "password": pw, "encryptedPassword": True}
            r = self.session.post(f"{self.base_url}/api/v1/session", json=payload, headers={'X-CAP-API-KEY': self.cap_key, 'Content-Type': 'application/json'})
            
            if r.status_code == 200:
                self.cst = r.headers.get('CST')
                self.x_security = r.headers.get('X-SECURITY-TOKEN')
                return True
            return False
        except Exception as e:
            st.error(f"Login Failed: {e}")
            return False

    # --- MARKET DATA ---
    def get_market_data(self, epic="ETHUSD"):
        """Fetches Price, Account Status, Positions, and History in one go."""
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        
        price = 0
        account = {}
        positions = []
        candles = []

        try:
            # Price
            r = self.session.get(f"{self.base_url}/api/v1/markets/{epic}", headers=headers)
            if r.status_code == 200: price = r.json()['snapshot']['offer']
            
            # Account Info (Equity, Margin)
            r = self.session.get(f"{self.base_url}/api/v1/accounts", headers=headers)
            if r.status_code == 200: account = r.json()['accounts'][0]['balance']
            
            # Active Positions
            r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
            if r.status_code == 200: positions = r.json()['positions']

            # Candle History (For AI Context)
            r = self.session.get(f"{self.base_url}/api/v1/prices/{epic}?resolution=MINUTE&max=15", headers=headers)
            if r.status_code == 200: 
                raw = r.json()['prices']
                for c in raw: candles.append(c['closePrice']['bid'])
                
        except Exception:
            pass # Silent fail to keep loop running

        return price, account, positions, candles

    # --- TRADING ACTIONS ---
    def place_order(self, epic, side, size):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security, 'Content-Type': 'application/json'}
        payload = {
            "epic": epic,
            "direction": side, # "BUY" or "SELL"
            "size": size
        }
        r = self.session.post(f"{self.base_url}/api/v1/positions", json=payload, headers=headers)
        return r.status_code == 200

    def close_all_positions(self):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
        if r.status_code == 200:
            for p in r.json()['positions']:
                self.session.delete(f"{self.base_url}/api/v1/positions/{p['dealId']}", headers=headers)
        return "Positions Closed"

# ==========================================
# 2. AI STRATEGY ENGINE (Gemini)
# ==========================================
def ask_gemini_strategy(bot, price, candles, equity, available):
    # Prepare Data Context for the LLM
    trend_str = " -> ".join([str(c) for c in candles[-10:]])
    
    prompt = f"""
    Act as a Hedge Fund Algo. Asset: ETH/USD. Price: {price}.
    Recent 10m Trend: {trend_str}
    
    Portfolio State:
    - Equity: {equity}
    - Available Cash: {available}
    
    Rules:
    1. Maintain 20% Cash Reserve. (Current Reserve Floor: {equity*0.2})
    2. If Available Cash < Reserve Floor, signal HOLD (Defensive Mode).
    3. If Trend is clearly UP, signal BUY.
    4. If Trend is clearly DOWN, signal SELL (Short).
    
    Output strictly one word: BUY, SELL, or HOLD.
    """
    
    try:
        response = bot.model.generate_content(prompt)
        decision = response.text.strip().upper()
        if "BUY" in decision: return "BUY"
        if "SELL" in decision: return "SELL"
        return "HOLD"
    except:
        return "HOLD"

# ==========================================
# 3. STREAMLIT FRONTEND
# ==========================================
def main():
    st.set_page_config(page_title="AI Hedge Fund", page_icon="🏦", layout="wide")
    
    # Custom CSS for the Dashboard Header
    st.markdown("""
        <style>
        div[data-testid="metric-container"] {
            background-color: #1E1E1E;
            border: 1px solid #333;
            padding: 10px;
            border-radius: 8px;
        }
        </style>
    """, unsafe_allow_html=True)

    # Initialize State
    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalClient()
        st.session_state.connected = False
        st.session_state.active = False
        st.session_state.last_ai_check = datetime.now() - timedelta(minutes=2) # Force check on start
        st.session_state.ai_decision = "INITIALIZING"
        st.session_state.midnight_mode = False

    bot = st.session_state.bot

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🏦 Fund Controls")
        
        if not st.session_state.connected:
            if st.button("🔌 Connect to Broker", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("API Uplink Established")
            
            st.divider()
            st.subheader("Allocation Strategy")
            leverage = st.number_input("Leverage (1:X)", value=10)
            base_invest = st.number_input("Base Trade Size ($)", value=100)
            
            st.divider()
            col1, col2 = st.columns(2)
            if st.session_state.active:
                if col1.button("🛑 PAUSE"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if col1.button("▶️ RUN AI"):
                    st.session_state.active = True
                    st.rerun()
            
            if col2.button("⚠️ CLOSE ALL"):
                bot.close_all_positions()
                st.toast("Executed Emergency Close")

    # --- MAIN DASHBOARD ---
    st.title("🤖 Gemini AI Hedge Fund Agent")
    
    if not st.session_state.connected:
        st.info("Waiting for connection... (Check Sidebar)")
        st.stop()

    # Layout Placeholders
    header_ph = st.empty()
    status_ph = st.empty()
    table_ph = st.empty()

    # --- MAIN EXECUTION LOOP ---
    while True:
        # 1. Fetch Live Data
        price, account, positions, candles = bot.get_market_data("ETHUSD")
        
        # 2. Parse Metrics
        equity = account.get('equity', 0)
        available = account.get('available', 0)
        margin = account.get('margin', 0)
        pl = account.get('profitLoss', 0)
        
        # 3. Strategy Checks
        reserve_limit = equity * 0.20
        is_safe_to_trade = available > reserve_limit
        
        # 4. Midnight Protocol (Close 1m before, Resume 5m after)
        now = datetime.now()
        if now.hour == 23 and now.minute == 59 and not st.session_state.midnight_mode:
            st.session_state.midnight_mode = True
            bot.close_all_positions()
            st.toast("🌙 Midnight Protocol: Positions Cleared.")
        
        if st.session_state.midnight_mode and now.hour == 0 and now.minute >= 5:
            st.session_state.midnight_mode = False
            st.toast("☀️ Morning Protocol: Trading Resumed.")

        # 5. AI Decision Cycle (Every 60s)
        time_since_ai = (now - st.session_state.last_ai_check).total_seconds()
        
        if st.session_state.active and not st.session_state.midnight_mode and time_since_ai > 60:
            if is_safe_to_trade:
                decision = ask_gemini_strategy(bot, price, candles, equity, available)
                st.session_state.ai_decision = decision
                st.session_state.last_ai_check = now
                
                # Execute
                if decision in ["BUY", "SELL"]:
                    size = round((base_invest * leverage) / price, 2)
                    bot.place_order("ETHUSD", decision, size)
                    st.toast(f"🤖 AI Executed: {decision} {size} ETH")
            else:
                st.session_state.ai_decision = "HOLD (Cash Reserve Low)"

        # --- UI RENDER ---
        
        # A. Header (Real-Time)
        with header_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Equity", f"€{equity:,.2f}")
            c2.metric("Available Funds", f"€{available:,.2f}", delta=f"Reserve: €{reserve_limit:.0f}")
            c3.metric("Margin Used", f"€{margin:,.2f}")
            c4.metric("Total P/L", f"€{pl:,.2f}", delta=pl)

        # B. Status Bar
        with status_ph.container():
            s1, s2 = st.columns([1, 4])
            state_label = "ACTIVE" if st.session_state.active else "IDLE"
            if st.session_state.midnight_mode: state_label = "SLEEPING"
            
            s1.info(f"**State:** {state_label}")
            s2.success(f"🧠 **AI Strategy:** {st.session_state.ai_decision} (Last Update: {st.session_state.last_ai_check.strftime('%H:%M:%S')})")

        # C. Active Trades Table
        trade_list = []
        for p in positions:
            trade_list.append({
                "Asset": p.get('epic'),
                "Side": p.get('direction'),
                "Size": p.get('size'),
                "Entry Price": p.get('openPrice'),
                "Current P/L": f"€{p.get('profitAndLoss'):.2f}"
            })
        
        if trade_list:
            table_ph.dataframe(pd.DataFrame(trade_list), use_container_width=True)
        else:
            table_ph.caption("No Active Positions")

        time.sleep(1)

if __name__ == "__main__":
    main()

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
# 1. CAPITAL.COM API CLIENT
# ==========================================
class CapitalClient:
    def __init__(self):
        try:
            self.cap_key = st.secrets["capital_com"]["api_key"]
            self.login = st.secrets["capital_com"]["email"]
            self.password = st.secrets["capital_com"]["password"]
            genai.configure(api_key=st.secrets["gemini"]["api_key"])
            self.model = genai.GenerativeModel('gemini-pro')
        except Exception:
            st.error("❌ Secrets missing! Check .streamlit/secrets.toml")
            st.stop()
        
        self.base_url = "https://demo-api-capital.backend-capital.com"
        self.session = requests.Session()
        self.cst = None
        self.x_security = None

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
            r = self.session.get(f"{self.base_url}/api/v1/session/encryptionKey", headers={'X-CAP-API-KEY': self.cap_key})
            r.raise_for_status()
            data = r.json()
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

    def get_market_data(self, epic="ETHUSD"):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        price = 0
        account = {}
        positions = []
        candles = []

        try:
            # 1. Price
            r = self.session.get(f"{self.base_url}/api/v1/markets/{epic}", headers=headers)
            if r.status_code == 200: price = r.json()['snapshot']['offer']
            
            # 2. Account
            r = self.session.get(f"{self.base_url}/api/v1/accounts", headers=headers)
            if r.status_code == 200: account = r.json()['accounts'][0]['balance']
            
            # 3. Positions
            r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
            if r.status_code == 200: positions = r.json()['positions']

            # 4. History (15 mins)
            r = self.session.get(f"{self.base_url}/api/v1/prices/{epic}?resolution=MINUTE&max=15", headers=headers)
            if r.status_code == 200: 
                raw = r.json()['prices']
                for c in raw: candles.append(c['closePrice']['bid'])
        except: pass

        return price, account, positions, candles

    def place_order(self, epic, side, size):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security, 'Content-Type': 'application/json'}
        payload = {"epic": epic, "direction": side, "size": size}
        r = self.session.post(f"{self.base_url}/api/v1/positions", json=payload, headers=headers)
        return r.status_code == 200

    def close_all_positions(self):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
        if r.status_code == 200:
            for p in r.json()['positions']:
                self.session.delete(f"{self.base_url}/api/v1/positions/{p['dealId']}", headers=headers)

# ==========================================
# 2. AI HEDGE FUND MANAGER
# ==========================================
def ask_gemini_strategy(bot, price, candles):
    trend_str = " -> ".join([str(c) for c in candles[-10:]])
    
    prompt = f"""
    Act as a Senior Crypto Hedge Fund Manager. Asset: ETH/USD. Price: {price}.
    Recent 10m Trend: {trend_str}
    
    You have two trading desks:
    1. CORE DESK (Safe, Trend Following)
    2. MICRO DESK (Aggressive, High Leverage, Volatility Capture)
    
    Analyze the market structure.
    - If strong sustained trend: Signal 'CORE BUY' or 'CORE SELL'.
    - If high volatility/choppy but clear direction: Signal 'MICRO BUY' or 'MICRO SELL'.
    - If unclear: Signal 'HOLD'.
    
    Output strictly one of these 5 options: CORE BUY, CORE SELL, MICRO BUY, MICRO SELL, HOLD.
    """
    
    try:
        response = bot.model.generate_content(prompt)
        decision = response.text.strip().upper()
        # Validation
        valid_cmds = ["CORE BUY", "CORE SELL", "MICRO BUY", "MICRO SELL", "HOLD"]
        if any(cmd in decision for cmd in valid_cmds):
            return decision
        return "HOLD"
    except:
        return "HOLD"

# ==========================================
# 3. DYNAMIC SIZING ENGINE
# ==========================================
def calculate_trade_size(decision, equity, price):
    """
    Auto-calculates trade size based on the 50/30/20 Rule.
    Risks small % of the specific bucket per trade to survive drawdown.
    """
    
    # 1. Define Buckets
    core_fund = equity * 0.50
    micro_fund = equity * 0.30
    # Reserve (20%) is untouched
    
    size = 0.0
    
    if "CORE" in decision:
        # Core Strategy: Use 5% of the Core Fund per trade
        # Standard Leverage (Assumed 1:2 for safety)
        invest_amount = core_fund * 0.05
        leverage = 2
        size = (invest_amount * leverage) / price
        
    elif "MICRO" in decision:
        # Micro Strategy: Use 5% of the Micro Fund per trade
        # HIGH Leverage (1:10)
        invest_amount = micro_fund * 0.05
        leverage = 10
        size = (invest_amount * leverage) / price
        
    return round(size, 2)

# ==========================================
# 4. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="AI Hedge Fund", page_icon="🏦", layout="wide")
    
    # Custom Dark Mode Styling
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

    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalClient()
        st.session_state.connected = False
        st.session_state.active = False
        st.session_state.last_ai_check = datetime.now() - timedelta(minutes=2)
        st.session_state.ai_decision = "INITIALIZING"
        st.session_state.midnight_mode = False

    bot = st.session_state.bot

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🏦 Fund Admin")
        
        if not st.session_state.connected:
            if st.button("🔌 Connect to Broker", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("Connected to Capital.com")
            
            st.divider()
            st.caption("Strategy Allocation:")
            st.progress(50, text="Core Fund (50%) - Standard")
            st.progress(30, text="Micro Fund (30%) - 1:10 Lev")
            st.progress(20, text="Cash Reserve (20%) - Locked")
            
            st.divider()
            c1, c2 = st.columns(2)
            if st.session_state.active:
                if c1.button("🛑 PAUSE"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if c1.button("▶️ RUN AI"):
                    st.session_state.active = True
                    st.rerun()
            
            if c2.button("⚠️ LIQUIDATE"):
                bot.close_all_positions()
                st.toast("Forced Liquidation Executed.")

    # --- DASHBOARD ---
    st.title("🤖 AI Hedge Fund Dashboard")
    
    if not st.session_state.connected:
        st.info("👈 Please connect via Sidebar.")
        st.stop()

    header_ph = st.empty()
    status_ph = st.empty()
    table_ph = st.empty()

    # --- MAIN LOOP ---
    while True:
        # 1. Live Data
        price, account, positions, candles = bot.get_market_data("ETHUSD")
        
        # 2. Metrics
        equity = account.get('equity', 0)
        available = account.get('available', 0)
        margin = account.get('margin', 0)
        pl = account.get('profitLoss', 0)
        
        # 3. Strategy Limits
        reserve_floor = equity * 0.20
        safe_to_trade = available > reserve_floor
        
        # 4. Midnight Protocol (Close 1m before midnight, wait 5m)
        now = datetime.now()
        if now.hour == 23 and now.minute == 59 and not st.session_state.midnight_mode:
            st.session_state.midnight_mode = True
            bot.close_all_positions()
            st.toast("🌙 Midnight Protocol Initiated")
        
        if st.session_state.midnight_mode and now.hour == 0 and now.minute >= 5:
            st.session_state.midnight_mode = False
            st.toast("☀️ Morning Protocol: Resuming")

        # 5. AI Cycle (Every 60s)
        time_since = (now - st.session_state.last_ai_check).total_seconds()
        
        if st.session_state.active and not st.session_state.midnight_mode and time_since > 60:
            if safe_to_trade:
                decision = ask_gemini_strategy(bot, price, candles)
                st.session_state.ai_decision = decision
                st.session_state.last_ai_check = now
                
                # Execute if BUY/SELL
                if "BUY" in decision or "SELL" in decision:
                    side = "BUY" if "BUY" in decision else "SELL"
                    
                    # DYNAMIC SIZING "Do as you want"
                    size = calculate_trade_size(decision, equity, price)
                    
                    if size > 0:
                        bot.place_order("ETHUSD", side, size)
                        st.toast(f"🤖 Executed: {decision} | Size: {size} ETH")
            else:
                st.session_state.ai_decision = "HOLD (Cash Reserve Hit)"

        # --- UI UPDATE ---
        with header_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Equity", f"€{equity:,.2f}")
            c2.metric("Free Funds", f"€{available:,.2f}", delta=f"Floor: €{reserve_floor:.0f}")
            c3.metric("Margin Used", f"€{margin:,.2f}")
            c4.metric("Total P/L", f"€{pl:,.2f}", delta=pl)

        with status_ph.container():
            s1, s2 = st.columns([1, 4])
            mode = "ACTIVE" if st.session_state.active else "PAUSED"
            if st.session_state.midnight_mode: mode = "MIDNIGHT WAIT"
            
            s1.info(f"**Bot Mode:** {mode}")
            s2.success(f"🧠 **Gemini Strategy:** {st.session_state.ai_decision} (Updated: {st.session_state.last_ai_check.strftime('%H:%M:%S')})")

        # Active Positions Table
        trade_list = []
        for p in positions:
            trade_list.append({
                "Asset": p.get('epic'),
                "Direction": p.get('direction'),
                "Size": p.get('size'),
                "Entry": p.get('openPrice'),
                "Live P/L": f"€{p.get('profitAndLoss'):.2f}"
            })
        
        if trade_list:
            table_ph.dataframe(pd.DataFrame(trade_list), use_container_width=True)
        else:
            table_ph.info("No Active Positions. AI is scanning...")

        time.sleep(1)

if __name__ == "__main__":
    main()

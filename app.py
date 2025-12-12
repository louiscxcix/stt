import streamlit as st
import requests
import base64
import time
import pandas as pd
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

            # 4. History (Short term for scalping)
            r = self.session.get(f"{self.base_url}/api/v1/prices/{epic}?resolution=MINUTE&max=10", headers=headers)
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
# 2. AGGRESSIVE AI ENGINE
# ==========================================
def ask_gemini_aggressive(bot, price, candles):
    # Format trend for the prompt
    trend_str = " -> ".join([str(c) for c in candles[-5:]])
    
    prompt = f"""
    You are an Aggressive Crypto Scalper running a Hedge Fund.
    Asset: ETH/USD. Current Price: {price}.
    Last 5 candles: {trend_str}
    
    YOUR GOAL: OPEN TRADES. DO NOT BE PASSIVE.
    You have two modes:
    1. "CORE BUY/SELL": For clear trends (Safe Sizing).
    2. "MICRO BUY/SELL": For quick scalps (High Leverage).
    
    INSTRUCTIONS:
    - Look at the last 3 candles. If they moved up, "MICRO BUY".
    - If they moved down, "MICRO SELL".
    - Only output "HOLD" if the market is completely flat (zero movement).
    - Be biased towards ACTION.
    
    Output ONE command: CORE BUY, CORE SELL, MICRO BUY, MICRO SELL, or HOLD.
    """
    
    try:
        response = bot.model.generate_content(prompt)
        decision = response.text.strip().upper()
        # Fallback if AI hallucinates
        valid = ["CORE BUY", "CORE SELL", "MICRO BUY", "MICRO SELL", "HOLD"]
        if any(v in decision for v in valid):
            return decision
        return "MICRO BUY" # Default to aggressive buy if confused
    except:
        return "HOLD"

# ==========================================
# 3. DYNAMIC SIZING (50/30/20 RULE)
# ==========================================
def calculate_trade_size(decision, equity, price):
    # Rule Buckets
    core_bucket = equity * 0.50
    micro_bucket = equity * 0.30
    
    size = 0.0
    
    # Risk 5% of the respective bucket per trade to keep it sustainable
    if "CORE" in decision:
        invest = core_bucket * 0.05
        lev = 2
        size = (invest * lev) / price
        
    elif "MICRO" in decision:
        invest = micro_bucket * 0.05
        lev = 10 # High Leverage for Micro
        size = (invest * lev) / price
        
    return round(size, 2)

# ==========================================
# 4. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="Active Fund", page_icon="🚀", layout="wide")
    
    st.markdown("""
        <style>
        div[data-testid="metric-container"] { background-color: #111; border: 1px solid #333; padding: 10px; border-radius: 8px; }
        .stAlert { background-color: #111; border: 1px solid #333; color: #0f0; }
        </style>
    """, unsafe_allow_html=True)

    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalClient()
        st.session_state.connected = False
        st.session_state.active = False
        st.session_state.last_ai_check = datetime.now() - timedelta(minutes=2)
        st.session_state.ai_log = "Initializing..."
        st.session_state.midnight_mode = False

    bot = st.session_state.bot

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🚀 Active Fund")
        if not st.session_state.connected:
            if st.button("🔌 Connect", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("Connected")
            st.divider()
            c1, c2 = st.columns(2)
            if st.session_state.active:
                if c1.button("🛑 STOP"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if c1.button("▶️ START"):
                    st.session_state.active = True
                    st.rerun()
            
            if c2.button("⚠️ CLOSE ALL"):
                bot.close_all_positions()
                st.toast("Forced Close")

    st.title("🤖 High-Frequency AI Manager")
    
    if not st.session_state.connected:
        st.info("👈 Connect via Sidebar")
        st.stop()

    # Placeholders
    header_ph = st.empty()
    live_log_ph = st.empty() # For "Thinking" stream
    table_ph = st.empty()

    # --- LOOP ---
    while True:
        # 1. Fetch
        price, account, positions, candles = bot.get_market_data("ETHUSD")
        
        # 2. Metrics
        equity = account.get('equity', 0)
        available = account.get('available', 0)
        margin = account.get('margin', 0)
        pl = account.get('profitLoss', 0)
        
        # 3. Reserve Check (20% Rule)
        reserve_floor = equity * 0.20
        can_trade = available > reserve_floor

        # 4. Midnight Protocol
        now = datetime.now()
        if now.hour == 23 and now.minute == 59 and not st.session_state.midnight_mode:
            st.session_state.midnight_mode = True
            bot.close_all_positions()
            st.session_state.ai_log = "🌙 Midnight: Closing & Sleeping..."
        
        if st.session_state.midnight_mode and now.hour == 0 and now.minute >= 5:
            st.session_state.midnight_mode = False
            st.session_state.ai_log = "☀️ Morning: Waking up..."

        # 5. AI LOGIC (Every 15 Seconds - FAST)
        time_since = (now - st.session_state.last_ai_check).total_seconds()
        
        if st.session_state.active and not st.session_state.midnight_mode and time_since > 15:
            if can_trade:
                st.session_state.ai_log = f"⚡ Scanning Volatility... Price: ${price}"
                
                # Get Decision
                decision = ask_gemini_aggressive(bot, price, candles)
                
                if "BUY" in decision or "SELL" in decision:
                    side = "BUY" if "BUY" in decision else "SELL"
                    size = calculate_trade_size(decision, equity, price)
                    
                    if size > 0:
                        bot.place_order("ETHUSD", side, size)
                        st.session_state.ai_log = f"🚀 EXECUTED: {decision} | Size: {size}"
                        st.toast(f"Trade: {decision}", icon="💸")
                    else:
                        st.session_state.ai_log = "⚠️ Signal valid but Size calculated to 0."
                else:
                    st.session_state.ai_log = "👀 Market Flat. Holding for breakout."
                
                st.session_state.last_ai_check = now
            else:
                st.session_state.ai_log = f"🛑 LOW CASH. Reserved: €{reserve_floor:.0f}"

        # --- UI UPDATE ---
        with header_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"€{equity:,.2f}")
            c2.metric("Free Cash", f"€{available:,.2f}", delta=f"Floor: €{reserve_floor:.0f}")
            c3.metric("Used Margin", f"€{margin:,.2f}")
            c4.metric("Live P/L", f"€{pl:,.2f}", delta=pl)

        # LIVE LOG STREAM
        live_log_ph.info(f"**AI FEED:** {st.session_state.ai_log}")

        # TABLE
        trades = []
        for p in positions:
            trades.append({
                "Type": p.get('direction'),
                "Size": p.get('size'),
                "Entry": p.get('openPrice'),
                "P/L": f"€{p.get('profitAndLoss'):.2f}"
            })
        
        if trades:
            table_ph.dataframe(pd.DataFrame(trades), use_container_width=True)
        else:
            table_ph.text("Searching for entries...")

        time.sleep(1)

if __name__ == "__main__":
    main()

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

            # 4. History (Short term context for Scalping)
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
        return r.status_code == 200, r.text

    def close_all_positions(self):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
        if r.status_code == 200:
            for p in r.json()['positions']:
                self.session.delete(f"{self.base_url}/api/v1/positions/{p['dealId']}", headers=headers)

# ==========================================
# 2. AGGRESSIVE SCALPER AI
# ==========================================
def ask_gemini_aggressive(bot, price, candles):
    trend_str = " -> ".join([str(c) for c in candles[-5:]]) # Last 5 minutes focus
    
    # HYPER-AGGRESSIVE PROMPT
    prompt = f"""
    You are an Ultra-Aggressive Crypto Scalper. 
    Asset: ETH/USD. Price: {price}.
    Last 5m Prices: {trend_str}
    
    Your goal is High Frequency Trading. 
    DO NOT HOLD. DO NOT WAIT.
    
    Analysis Logic:
    1. If price moved UP in last 2 mins -> MOMENTUM BUY (CORE)
    2. If price moved DOWN in last 2 mins -> MOMENTUM SELL (CORE)
    3. If price is flat -> MEAN REVERSION (MICRO)
       - If barely red, BUY (betting on bounce)
       - If barely green, SELL (betting on pullback)
    
    You MUST output a decision. "HOLD" is forbidden unless API is broken.
    
    Output Format: "DECISION | REASON"
    Options for Decision: CORE BUY, CORE SELL, MICRO BUY, MICRO SELL
    """
    
    try:
        response = bot.model.generate_content(prompt)
        text = response.text.strip()
        if "|" in text:
            decision, reason = text.split("|", 1)
            return decision.strip().upper(), reason.strip()
        # Fallback if AI hallucinates format
        return "MICRO BUY", "AI Default Aggressive" 
    except:
        return "MICRO BUY", "Connection Fail - Forcing Trade"

# ==========================================
# 3. DYNAMIC SIZING (50/30/20 Rule)
# ==========================================
def calculate_trade_size(decision, equity, price):
    core_fund = equity * 0.50
    micro_fund = equity * 0.30
    
    size = 0.0
    
    if "CORE" in decision:
        # Core: Heavy Trend -> Risk 10% of Core Fund
        invest = core_fund * 0.10
        leverage = 5
        size = (invest * leverage) / price
        
    elif "MICRO" in decision:
        # Micro: Scalp -> Risk 15% of Micro Fund
        invest = micro_fund * 0.15
        leverage = 10 
        size = (invest * leverage) / price
        
    return round(size, 2)

# ==========================================
# 4. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="AI Scalper", page_icon="⚡", layout="wide")
    
    st.markdown("""
        <style>
        div[data-testid="metric-container"] {
            background-color: #111;
            border: 1px solid #444;
            padding: 10px;
            border-radius: 5px;
        }
        </style>
    """, unsafe_allow_html=True)

    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalClient()
        st.session_state.connected = False
        st.session_state.active = False
        # Set to past so it triggers immediately on start
        st.session_state.last_ai_check = datetime.now() - timedelta(minutes=5) 
        st.session_state.ai_log = []
        st.session_state.midnight_mode = False

    bot = st.session_state.bot

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("⚡ Scalper Admin")
        
        if not st.session_state.connected:
            if st.button("🔌 Connect", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("System Online")
            
            c1, c2 = st.columns(2)
            if st.session_state.active:
                if c1.button("🛑 STOP"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if c1.button("▶️ START NOW"):
                    st.session_state.active = True
                    # Force Immediate Trigger
                    st.session_state.last_ai_check = datetime.now() - timedelta(minutes=5)
                    st.rerun()
            
            if c2.button("⚠️ CLOSE ALL"):
                bot.close_all_positions()
                st.toast("Dumped all positions.")

    # --- DASHBOARD ---
    st.title("🤖 AI High-Frequency Scalper")
    
    if not st.session_state.connected:
        st.info("👈 Connect via Sidebar")
        st.stop()

    header_ph = st.empty()
    
    col_left, col_right = st.columns([2, 1])
    with col_left:
        st.subheader("📡 Live Positions")
        table_ph = st.empty()
    with col_right:
        st.subheader("🧠 Neural Feed")
        log_ph = st.empty()

    # --- LOOP ---
    while True:
        # 1. Live Data
        price, account, positions, candles = bot.get_market_data("ETHUSD")
        
        equity = account.get('equity', 0)
        available = account.get('available', 0)
        margin = account.get('margin', 0)
        pl = account.get('profitLoss', 0)
        
        # 2. Strategy Logic
        reserve_floor = equity * 0.20
        # Relaxed Safety: Trade as long as we have > 20% reserve
        safe_to_trade = available > reserve_floor
        
        # 3. AI Cycle (Every 10 seconds for Scalping)
        now = datetime.now()
        time_since = (now - st.session_state.last_ai_check).total_seconds()
        
        # ACTIVE LOGIC
        if st.session_state.active:
            # Check Every 10 Seconds (Aggressive)
            if time_since > 10:
                if safe_to_trade:
                    # Limit max open positions to prevent over-exposure
                    if len(positions) < 5: 
                        decision, reason = ask_gemini_aggressive(bot, price, candles)
                        
                        # Log
                        timestamp = now.strftime('%H:%M:%S')
                        log_entry = f"[{timestamp}] {decision}: {reason}"
                        st.session_state.ai_log.insert(0, log_entry)
                        st.session_state.last_ai_check = now
                        
                        # Execute
                        side = "BUY" if "BUY" in decision else "SELL"
                        size = calculate_trade_size(decision, equity, price)
                        
                        if size > 0:
                            success, msg = bot.place_order("ETHUSD", side, size)
                            if success:
                                st.toast(f"⚡ {decision} {size} ETH", icon="🔥")
                    else:
                        st.session_state.ai_log.insert(0, f"[{now.strftime('%H:%M:%S')}] MAX POSITIONS (5). Holding.")
                else:
                    st.session_state.ai_log.insert(0, "⚠️ LOW CASH RESERVE - Pausing Buys")

        # --- UI UPDATE ---
        with header_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"€{equity:,.2f}")
            c2.metric("Free Funds", f"€{available:,.2f}", delta=f"Floor: €{reserve_floor:.0f}")
            c3.metric("Margin Used", f"€{margin:,.2f}")
            c4.metric("Total P/L", f"€{pl:,.2f}", delta=pl)

        if positions:
            trade_list = []
            for p in positions:
                trade_list.append({
                    "Type": p.get('direction'),
                    "Size": p.get('size'),
                    "Entry": p.get('openPrice'),
                    "P/L": f"€{p.get('profitAndLoss'):.2f}"
                })
            table_ph.dataframe(pd.DataFrame(trade_list), use_container_width=True)
        else:
            table_ph.info("Scanning for setup...")

        with log_ph.container(height=400):
            for log in st.session_state.ai_log[:20]:
                st.text(log)

        time.sleep(1)

if __name__ == "__main__":
    main()

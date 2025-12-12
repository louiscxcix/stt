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
            
            genai.configure(api_key=st.secrets["gemini"]["GEMINI_API_KEY"])
            
            # FORCE 2.5 FLASH LITE
            try:
                self.model_name = "gemini-2.5-flash-lite"
                self.model = genai.GenerativeModel(self.model_name)
            except:
                self.model_name = "gemini-2.0-flash-lite-preview-02-05"
                self.model = genai.GenerativeModel(self.model_name)
            
        except Exception as e:
            st.error(f"❌ Connection Error: {e}")
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
            if r.status_code == 401: return False
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
        except: return False

    def get_market_data(self, epic="ETHUSD"):
        headers = {'X-CAP-API-KEY': self.cap_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security}
        price = 0
        account = {}
        positions = []
        candles = []

        try:
            r = self.session.get(f"{self.base_url}/api/v1/markets/{epic}", headers=headers)
            if r.status_code == 200: price = r.json()['snapshot']['offer']
            
            r = self.session.get(f"{self.base_url}/api/v1/accounts", headers=headers)
            if r.status_code == 200: account = r.json()['accounts'][0]['balance']
            
            r = self.session.get(f"{self.base_url}/api/v1/positions", headers=headers)
            if r.status_code == 200: positions = r.json()['positions']

            r = self.session.get(f"{self.base_url}/api/v1/prices/{epic}?resolution=MINUTE&max=5", headers=headers)
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
# 2. MANIC AI MANAGER (NO HOLDING ALLOWED)
# ==========================================
def ask_gemini_aggressive(bot, price, candles):
    if not candles: return "MICRO BUY", "No Data - Force Entry"

    trend_str = " -> ".join([str(c) for c in candles[-5:]]) 
    
    prompt = f"""
    You are a High-Frequency Crypto Trading Bot.
    Asset: ETH/USD. Price: {price}.
    Recent 5m Trend: {trend_str}
    
    YOUR JOB IS TO TRADE. HOLDING IS FORBIDDEN.
    
    Rules:
    1. If price is moving UP even slightly -> CORE BUY
    2. If price is moving DOWN even slightly -> CORE SELL
    3. If flat -> Scalp the noise (MICRO BUY/SELL)
    
    You MUST output strictly: "DECISION | REASON"
    Valid Decisions: CORE BUY, CORE SELL, MICRO BUY, MICRO SELL
    """
    
    try:
        response = bot.model.generate_content(prompt)
        text = response.text.strip()
        if "|" in text:
            decision, reason = text.split("|", 1)
            return decision.strip().upper(), reason.strip()
        # Fallback if AI hallucinates format
        return "MICRO BUY", "AI Format Error - Defaulting to Buy"
    except Exception as e:
        return "MICRO BUY", f"API Fail - Force Buy: {str(e)[:10]}"

# ==========================================
# 3. DYNAMIC SIZING
# ==========================================
def calculate_trade_size(decision, equity, price):
    if price == 0 or equity == 0: return 0.01 # Fail-safe small size
    
    core_fund = equity * 0.50
    micro_fund = equity * 0.30
    
    size = 0.0
    
    if "CORE" in decision:
        invest = core_fund * 0.10
        leverage = 5
        size = (invest * leverage) / price
        
    elif "MICRO" in decision:
        invest = micro_fund * 0.15
        leverage = 10 
        size = (invest * leverage) / price
        
    return round(size, 2)

# ==========================================
# 4. MAIN LOOP
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
        # Force immediate start
        st.session_state.last_ai_check = datetime.now() - timedelta(minutes=1) 
        st.session_state.ai_log = []
        st.session_state.cooldown_until = None

    bot = st.session_state.bot

    with st.sidebar:
        st.title("⚡ Scalper Admin")
        st.caption(f"🧠 Brain: {bot.model_name}")
        
        if not st.session_state.connected:
            if st.button("🔌 Connect", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("Connected")
            
            c1, c2 = st.columns(2)
            if st.session_state.active:
                if c1.button("🛑 STOP"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if c1.button("▶️ START NOW"):
                    st.session_state.active = True
                    # Reset triggers
                    st.session_state.last_ai_check = datetime.now() - timedelta(minutes=1)
                    st.rerun()
            
            if c2.button("⚠️ CLOSE ALL"):
                bot.close_all_positions()
                st.toast("Dumped positions.")

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

    while True:
        price, account, positions, candles = bot.get_market_data("ETHUSD")
        
        equity = account.get('equity', 0)
        available = account.get('available', 0)
        margin = account.get('margin', 0)
        pl = account.get('profitLoss', 0)
        
        # We relaxed the reserve logic to ensure it TRADES.
        # As long as we have $50, we trade.
        safe_to_trade = available > 50
        
        now = datetime.now()
        in_cooldown = st.session_state.cooldown_until and now < st.session_state.cooldown_until
        time_since = (now - st.session_state.last_ai_check).total_seconds()
        
        if st.session_state.active and not in_cooldown:
            # 10 SECOND LOOP FOR SPEED
            if time_since > 10:
                if safe_to_trade:
                    # Only allow 3 concurrent trades max to prevent explosion
                    if len(positions) < 3: 
                        decision, reason = ask_gemini_aggressive(bot, price, candles)
                        
                        if "429" in reason:
                            st.session_state.cooldown_until = now + timedelta(seconds=60)
                            st.toast("⚠️ Rate Limit - Cooling 60s")
                        else:
                            timestamp = now.strftime('%H:%M:%S')
                            log_entry = f"[{timestamp}] {decision}: {reason}"
                            st.session_state.ai_log.insert(0, log_entry)
                            st.session_state.last_ai_check = now
                            
                            # EXECUTE WITHOUT QUESTION
                            side = "BUY" if "BUY" in decision else "SELL"
                            size = calculate_trade_size(decision, equity, price)
                            
                            if size > 0:
                                success, msg = bot.place_order("ETHUSD", side, size)
                                if success:
                                    st.toast(f"⚡ {decision} {size} ETH", icon="🔥")
                                else:
                                    st.session_state.ai_log.insert(0, f"[{timestamp}] EXEC FAIL: {msg}")
                    else:
                        st.session_state.ai_log.insert(0, f"[{now.strftime('%H:%M:%S')}] Max Positions (3). Waiting.")
                        st.session_state.last_ai_check = now # Reset timer so we don't spam log
                else:
                    st.error(f"LOW FUNDS: ${available} < $50")

        # UI UPDATE
        with header_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"€{equity:,.2f}")
            c2.metric("Free Funds", f"€{available:,.2f}")
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

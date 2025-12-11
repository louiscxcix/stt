import streamlit as st
import requests
import base64
import time
import pandas as pd
from datetime import datetime
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

# ==========================================
# 1. CAPITAL.COM API CLIENT
# ==========================================
class CapitalTradingBot:
    def __init__(self, is_demo=True):
        try:
            self.api_key = st.secrets["capital_com"]["api_key"]
            self.login = st.secrets["capital_com"]["email"]
            self.password = st.secrets["capital_com"]["password"]
        except Exception:
            st.error("❌ Secrets not found! Check .streamlit/secrets.toml")
            st.stop()
        
        self.base_url = "https://demo-api-capital.backend-capital.com" if is_demo else "https://api-capital.backend-capital.com"
        self.env_name = "DEMO" if is_demo else "LIVE"
        self.session = requests.Session()
        self.cst = None
        self.x_security_token = None

    def _get_encryption_key(self):
        url = f"{self.base_url}/api/v1/session/encryptionKey"
        headers = {'X-CAP-API-KEY': self.api_key}
        resp = self.session.get(url, headers=headers)
        return resp.json()['encryptionKey'], int(resp.json()['timeStamp'])

    def _encrypt_password(self, encryption_key_b64, timestamp):
        input_str = f"{self.password}|{timestamp}"
        input_bytes = base64.b64encode(input_str.encode('utf-8'))
        key_bytes = base64.b64decode(encryption_key_b64)
        public_key = RSA.import_key(key_bytes)
        cipher = PKCS1_v1_5.new(public_key)
        encrypted_bytes = cipher.encrypt(input_bytes)
        return base64.b64encode(encrypted_bytes).decode('utf-8')

    def connect(self):
        try:
            enc_key, timestamp = self._get_encryption_key()
            encrypted_pw = self._encrypt_password(enc_key, timestamp)
            url = f"{self.base_url}/api/v1/session"
            payload = {"identifier": self.login, "password": encrypted_pw, "encryptedPassword": True}
            headers = {'X-CAP-API-KEY': self.api_key, 'Content-Type': 'application/json'}
            
            response = self.session.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                self.cst = response.headers.get('CST')
                self.x_security_token = response.headers.get('X-SECURITY-TOKEN')
                return True
            return False
        except Exception as e:
            st.error(f"Connection Error: {e}")
            return False

    def get_price(self, epic):
        if not self.cst: return None
        url = f"{self.base_url}/api/v1/markets/{epic}"
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json()['snapshot']['offer'] # Return the ASK price
        except:
            return None
        return None

    def place_order(self, epic, size, stop_loss, take_profit):
        url = f"{self.base_url}/api/v1/positions"
        headers = {
            'X-CAP-API-KEY': self.api_key,
            'CST': self.cst,
            'X-SECURITY-TOKEN': self.x_security_token,
            'Content-Type': 'application/json'
        }
        payload = {
            "epic": epic,
            "direction": "BUY",
            "size": size,
            "stopLevel": stop_loss,
            "profitLevel": take_profit
        }
        resp = self.session.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            return True, resp.json()['dealReference']
        else:
            return False, resp.text

# ==========================================
# 2. STRATEGY ENGINE
# ==========================================
def run_strategy_cycle(bot):
    epic = "ETHUSD"
    
    # 1. Fetch Price
    current_price = bot.get_price(epic)
    if not current_price:
        return "⚠️ Error fetching price"

    # 2. Initialize Reference Price (First Run)
    if st.session_state.reference_price is None:
        st.session_state.reference_price = current_price
        return f"🏁 Initialized: Starting Ref Price ${current_price}"

    # 3. Strategy Logic
    # Update "High Water Mark": If price goes UP, drag the reference up so we buy local dips
    if current_price > st.session_state.reference_price:
        st.session_state.reference_price = current_price
        return f"📈 Price rose to ${current_price}. Ref Price Updated."

    # Calculate Drop Target
    drop_threshold = st.session_state.reference_price * 0.995 # 0.5% drop
    
    msg = f"Current: ${current_price} | Target Buy: < ${drop_threshold:.2f}"

    # 4. Check Buy Trigger
    if current_price <= drop_threshold:
        # Check Max Investment ($500 limit)
        if st.session_state.total_invested >= 500:
            return "🛑 Max Investment ($500) Reached. Strategy Paused."

        # Calculate Size
        investment = 50
        leverage = 10
        # Formula: (Inv * Lev) / Price
        size = round((investment * leverage) / current_price, 2)
        
        # SL/TP
        sl = round(current_price * 0.90, 2) # -10%
        tp = round(current_price * 1.01, 2) # +1%

        # Execute
        success, info = bot.place_order(epic, size, sl, tp)
        
        if success:
            st.session_state.total_invested += investment
            st.session_state.trade_count += 1
            st.session_state.reference_price = current_price # Reset reference to entry price
            
            # Log Trade
            log_entry = {
                "Time": datetime.now().strftime("%H:%M:%S"),
                "Type": "BUY",
                "Price": current_price,
                "Size": size,
                "Invested": investment
            }
            st.session_state.trade_log.append(log_entry)
            
            return f"🚀 BOUGHT {size} ETH @ ${current_price}"
        else:
            return f"❌ Trade Failed: {info}"

    return msg

# ==========================================
# 3. STREAMLIT UI
# ==========================================
def main():
    st.set_page_config(page_title="ETH AutoBot", page_icon="⚡", layout="wide")
    
    # --- INITIALIZE STATE ---
    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalTradingBot(is_demo=True)
        st.session_state.connected = False
        st.session_state.active = False # Main On/Off Switch
        
        # Strategy Memory
        st.session_state.reference_price = None
        st.session_state.total_invested = 0
        st.session_state.trade_count = 0
        st.session_state.trade_log = []

    bot = st.session_state.bot

    # --- SIDEBAR: CONTROLS ---
    with st.sidebar:
        st.title("🎛️ Controls")
        
        # Connection
        if not st.session_state.connected:
            if st.button("🔌 Connect API", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.success("Connected!")
                    st.rerun()
        else:
            st.success(f"🟢 Connected ({bot.env_name})")
            
            st.divider()
            
            # MASTER SWITCH
            if st.session_state.active:
                if st.button("🛑 STOP BOT", type="primary"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if st.button("▶️ START BOT", type="primary"):
                    st.session_state.active = True
                    st.rerun()
            
            st.divider()
            if st.button("🗑️ Reset Strategy Data"):
                st.session_state.reference_price = None
                st.session_state.total_invested = 0
                st.session_state.trade_count = 0
                st.session_state.trade_log = []
                st.session_state.active = False
                st.rerun()

    # --- MAIN DASHBOARD ---
    st.title("⚡ ETH/USD Auto-Trader")

    if not st.session_state.connected:
        st.info("👈 Please connect using the sidebar button.")
        st.stop()

    # Layout: 3 Columns
    kpi1, kpi2, kpi3 = st.columns(3)
    
    kpi1.metric("Total Invested", f"${st.session_state.total_invested} / $500")
    kpi2.metric("Reference Price (High)", f"${st.session_state.reference_price if st.session_state.reference_price else 0:.2f}")
    kpi3.metric("Trades Executed", st.session_state.trade_count)

    # Status Window
    st.subheader("📡 Live Status")
    status_container = st.container(border=True)
    
    with status_container:
        if st.session_state.active:
            st.write("🟢 **Bot is RUNNING** | Scanning market...")
            
            # --- RUN CYCLE ---
            status_msg = run_strategy_cycle(bot)
            st.info(status_msg)
            
            # Progress bar visual to show "next check"
            st.caption("Auto-refreshing in 10 seconds...")
            time.sleep(10) 
            st.rerun()
            
        else:
            st.write("🔴 **Bot is PAUSED**")
            st.write("Click 'START BOT' in the sidebar to begin automation.")

    # Trade History Table
    st.subheader("📜 Execution Log")
    if st.session_state.trade_log:
        df = pd.DataFrame(st.session_state.trade_log)
        st.dataframe(df, use_container_width=True)
    else:
        st.caption("No trades executed yet.")

if __name__ == "__main__":
    main()

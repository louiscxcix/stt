import streamlit as st
import requests
import base64
import time
import pandas as pd
import plotly.graph_objects as go
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
                return resp.json()['snapshot']['offer']
        except:
            return None
        return None

    def get_candles(self, epic):
        # NOTE: Capital.com REST API minimum resolution is MINUTE.
        # To simulate faster updates, we refresh the chart every 3 seconds.
        url = f"{self.base_url}/api/v1/prices/{epic}?resolution=MINUTE&max=30"
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code == 200:
                prices = resp.json()['prices']
                data = []
                for p in prices:
                    data.append({
                        'Time': p['snapshotTime'],
                        'Open': p['openPrice']['bid'],
                        'High': p['highPrice']['bid'],
                        'Low': p['lowPrice']['bid'],
                        'Close': p['closePrice']['bid']
                    })
                return pd.DataFrame(data)
        except:
            return pd.DataFrame()
        return pd.DataFrame()

    def get_positions(self):
        url = f"{self.base_url}/api/v1/positions"
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json().get('positions', [])
        except:
            return []
        return []

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
def run_strategy_logic(bot, settings):
    epic = "ETHUSD"
    current_price = bot.get_price(epic)
    
    if not current_price: return "⚠️ Price Error"

    now = datetime.now()

    # --- A. INITIALIZATION ---
    if st.session_state.reference_price is None:
        st.session_state.reference_price = current_price
        st.session_state.last_ref_update = now
        return f"🏁 Init Ref Price: ${current_price}"

    # --- B. 10-MINUTE TIMER ---
    time_diff = (now - st.session_state.last_ref_update).total_seconds()
    minutes_left = max(0, (600 - time_diff) / 60)

    if time_diff >= 600: # 10 Minutes
        old_ref = st.session_state.reference_price
        st.session_state.reference_price = current_price
        st.session_state.last_ref_update = now
        st.toast(f"Ref Updated: {old_ref} -> {current_price}", icon="🔄")
        return "🔄 Ref Price Updated (Timer)"

    # --- C. CHECK BUY CONDITION ---
    # Retrieve user settings
    drop_pct = settings['drop_percent']
    drop_target = st.session_state.reference_price * (1 - (drop_pct / 100))
    
    if current_price <= drop_target:
        # Check Max Cap
        if st.session_state.total_invested >= settings['max_invest']:
            return "🛑 Max Investment Reached"
            
        # Calc Size
        invest_amount = settings['invest_per_trade']
        leverage = settings['leverage']
        
        # Size = (Invest * Lev) / Price
        size = round((invest_amount * leverage) / current_price, 2)
        
        # SL / TP Prices
        sl_pct = settings['sl_percent'] / 100
        tp_pct = settings['tp_percent'] / 100
        
        sl_price = round(current_price * (1 - sl_pct), 2)
        tp_price = round(current_price * (1 + tp_pct), 2)
        
        # Execute
        success, ref = bot.place_order(epic, size, sl_price, tp_price)
        if success:
            st.session_state.total_invested += invest_amount
            st.session_state.reference_price = current_price # Reset ref to avoid double buy
            st.session_state.last_ref_update = now
            st.toast(f"BOUGHT! SL: {sl_price} TP: {tp_price}", icon="🚀")
            return "🚀 Trade Executed"
    
    return f"Scanning... (Ref Update in {int(minutes_left)}m)"

# ==========================================
# 3. UI
# ==========================================
def main():
    st.set_page_config(page_title="ETH ProBot", page_icon="⚡", layout="wide")

    # Init State
    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalTradingBot(is_demo=True)
        st.session_state.connected = False
        st.session_state.active = False
        st.session_state.reference_price = None
        st.session_state.last_ref_update = datetime.now()
        st.session_state.total_invested = 0

    bot = st.session_state.bot

    # --- SIDEBAR: SETTINGS & CONTROLS ---
    with st.sidebar:
        st.title("🎛️ Bot Settings")
        
        # 1. CONNECTION
        if not st.session_state.connected:
            if st.button("🔌 Connect", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("🟢 Connected")
            
            # 2. STRATEGY CONFIG FORM
            st.subheader("⚙️ Strategy Config")
            with st.form("strategy_settings"):
                drop_percent = st.number_input("Trigger Drop %", value=0.3, step=0.1)
                st.caption(f"Buys when price drops {drop_percent}% below Reference.")
                
                c1, c2 = st.columns(2)
                sl_percent = c1.number_input("Stop Loss %", value=10.0, step=0.5)
                tp_percent = c2.number_input("Take Profit %", value=1.0, step=0.5)
                
                c3, c4 = st.columns(2)
                max_invest = c3.number_input("Max Total Cap ($)", value=500, step=50)
                invest_per_trade = c4.number_input("Amt Per Trade ($)", value=50, step=10)
                
                leverage = st.number_input("Leverage", value=10, step=1)
                
                apply_btn = st.form_submit_button("Update Settings")
            
            # Save settings to session state dictionary
            settings = {
                "drop_percent": drop_percent,
                "sl_percent": sl_percent,
                "tp_percent": tp_percent,
                "max_invest": max_invest,
                "invest_per_trade": invest_per_trade,
                "leverage": leverage
            }

            st.divider()
            
            # 3. CONTROLS
            if st.session_state.active:
                if st.button("🛑 STOP BOT", type="primary"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if st.button("▶️ START BOT", type="secondary"):
                    st.session_state.active = True
                    st.rerun()
            
            st.divider()
            if st.button("Reset Strategy"):
                st.session_state.reference_price = None
                st.session_state.total_invested = 0
                st.rerun()

    # --- MAIN DASHBOARD ---
    st.title("⚡ ETH/USD Pro-Trader")

    if not st.session_state.connected:
        st.info("👈 Connect via Sidebar to start.")
        st.stop()

    # FETCH DATA
    candles_df = bot.get_candles("ETHUSD")
    positions = bot.get_positions()
    total_pl = sum([p['profitAndLoss'] for p in positions])
    current_p = candles_df.iloc[-1]['Close'] if not candles_df.empty else 0

    # DISPLAY METRICS
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Live Price", f"${current_p}")
    
    if st.session_state.reference_price:
        ref = st.session_state.reference_price
        target = ref * (1 - (settings['drop_percent']/100))
        k2.metric(f"Ref / Buy < {settings['drop_percent']}%", f"${ref:.2f}", f"Target: ${target:.2f}")
    else:
        k2.metric("Ref Price", "Waiting...")

    k3.metric("Total Invested", f"${st.session_state.total_invested}", f"Cap: ${settings['max_invest']}")
    k4.metric("Open P/L", f"${total_pl:.2f}", delta=total_pl)

    # CHART
    st.subheader("📈 Live Chart")
    if not candles_df.empty:
        fig = go.Figure(data=[go.Candlestick(
            x=candles_df['Time'],
            open=candles_df['Open'], high=candles_df['High'],
            low=candles_df['Low'], close=candles_df['Close'],
            name="ETHUSD"
        )])
        
        # Draw Lines if Active
        if st.session_state.reference_price:
            fig.add_hline(y=st.session_state.reference_price, line_dash="dot", line_color="gray", annotation_text="Ref")
            
            target_p = st.session_state.reference_price * (1 - (settings['drop_percent']/100))
            fig.add_hline(y=target_p, line_dash="solid", line_color="green", annotation_text="BUY")

        fig.update_layout(height=450, margin=dict(l=0, r=0, t=0, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    # POSITIONS
    st.subheader(f"💼 Open Trades ({len(positions)})")
    if positions:
        pos_data = []
        for p in positions:
            pos_data.append({
                "Date": p['createdDate'],
                "Amount": p['size'],
                "Entry": p['openPrice'],
                "Current": p['marketPrice'],
                "P/L ($)": p['profitAndLoss']
            })
        st.dataframe(pd.DataFrame(pos_data), use_container_width=True)

    # AUTO LOOP
    if st.session_state.active:
        status_msg = run_strategy_logic(bot, settings)
        st.caption(f"🤖 Status: {status_msg} | Checked: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(3) # Check every 3 seconds for faster updates
        st.rerun()

if __name__ == "__main__":
    main()

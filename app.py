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

    def close_all_positions(self):
        positions = self.get_positions()
        if not positions: return "No positions."
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token, 'Content-Type': 'application/json'}
        count = 0
        for p in positions:
            deal_id = p.get('dealId')
            url = f"{self.base_url}/api/v1/positions/{deal_id}"
            resp = self.session.delete(url, headers=headers)
            if resp.status_code == 200: count += 1
        return f"Closed {count} positions."

# ==========================================
# 2. STRATEGY ENGINE
# ==========================================
def run_strategy_logic(bot, settings, current_price):
    if not current_price: return "Waiting for price..."
    
    now = datetime.now()

    # --- A. INITIALIZATION ---
    if st.session_state.reference_price is None:
        st.session_state.reference_price = current_price
        st.session_state.last_ref_update = now
        return f"🏁 Init Ref: ${current_price}"

    # --- B. 10-MINUTE TIMER ---
    time_diff = (now - st.session_state.last_ref_update).total_seconds()
    minutes_left = max(0, (600 - time_diff) / 60)

    if time_diff >= 600:
        old_ref = st.session_state.reference_price
        st.session_state.reference_price = current_price
        st.session_state.last_ref_update = now
        st.toast(f"Ref Updated: {old_ref} -> {current_price}", icon="🔄")
        return "🔄 Ref Price Updated (Timer)"

    # --- C. CHECK BUY ---
    drop_pct = settings['drop_percent']
    drop_target = st.session_state.reference_price * (1 - (drop_pct / 100))
    
    if current_price <= drop_target:
        if st.session_state.total_invested >= settings['max_invest']:
            return "🛑 Max Cap Reached"
            
        invest_amount = settings['invest_per_trade']
        leverage = settings['leverage']
        size = round((invest_amount * leverage) / current_price, 2)
        
        if size <= 0: return "❌ Size too small"

        # USD Risk Calc
        sl_dollar = settings['sl_amount']
        tp_dollar = settings['tp_amount']
        price_dist_sl = sl_dollar / size
        price_dist_tp = tp_dollar / size
        
        sl_price = round(current_price - price_dist_sl, 2)
        tp_price = round(current_price + price_dist_tp, 2)
        
        success, ref = bot.place_order("ETHUSD", size, sl_price, tp_price)
        if success:
            st.session_state.total_invested += invest_amount
            st.session_state.reference_price = current_price 
            st.session_state.last_ref_update = now
            st.toast(f"BOUGHT! SL: {sl_price} TP: {tp_price}", icon="🚀")
            return "🚀 Trade Executed"
    
    return f"Scanning... Ref Update: {int(minutes_left)}m"

# ==========================================
# 3. UI
# ==========================================
def main():
    st.set_page_config(page_title="ETH RealTime", page_icon="⚡", layout="wide")

    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalTradingBot(is_demo=True)
        st.session_state.connected = False
        st.session_state.active = False
        st.session_state.reference_price = None
        st.session_state.last_ref_update = datetime.now()
        st.session_state.total_invested = 0

    bot = st.session_state.bot

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🎛️ Settings")
        
        if not st.session_state.connected:
            if st.button("🔌 Connect", type="primary"):
                if bot.connect():
                    st.session_state.connected = True
                    st.rerun()
        else:
            st.success("🟢 Connected")
            
            # STRATEGY FORM
            with st.form("strategy_settings"):
                st.write("**Trigger**")
                drop_percent = st.number_input("Drop %", value=0.3, step=0.1)
                st.write("**Risk ($)**")
                c1, c2 = st.columns(2)
                sl_amount = c1.number_input("Max Loss", value=5.0)
                tp_amount = c2.number_input("Target Profit", value=5.0)
                st.write("**Capital**")
                c3, c4 = st.columns(2)
                max_invest = c3.number_input("Max Cap", value=500)
                invest_per_trade = c4.number_input("Amt/Trade", value=50)
                leverage = st.number_input("Leverage", value=10)
                st.form_submit_button("Update")
            
            settings = {
                "drop_percent": drop_percent, "sl_amount": sl_amount, "tp_amount": tp_amount,
                "max_invest": max_invest, "invest_per_trade": invest_per_trade, "leverage": leverage
            }

            st.divider()
            
            # CONTROLS
            if st.session_state.active:
                if st.button("🛑 STOP BOT", type="primary"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if st.button("▶️ START BOT", type="secondary"):
                    st.session_state.active = True
                    st.rerun()
            
            if st.button("🚨 CLOSE ALL TRADES", type="primary"):
                with st.spinner("Closing..."):
                    res = bot.close_all_positions()
                    st.session_state.total_invested = 0
                    st.warning(res)
                    time.sleep(1)
            
            if st.button("Reset Memory"):
                st.session_state.reference_price = None
                st.session_state.total_invested = 0
                st.rerun()

    # --- MAIN DISPLAY ---
    st.title("⚡ ETH/USD Live Monitor")

    if not st.session_state.connected:
        st.info("👈 Connect to start.")
        st.stop()

    # PLACEHOLDERS
    metrics_ph = st.empty()
    chart_ph = st.empty()
    table_ph = st.empty()

    # --- MAIN LOOP (Always runs if connected) ---
    while True:
        # 1. Fetch Data
        candles_df = bot.get_candles("ETHUSD")
        current_p = bot.get_price("ETHUSD")
        positions = bot.get_positions()
        
        # Patch Chart with Live Price
        if not candles_df.empty and current_p:
            candles_df.iloc[-1, candles_df.columns.get_loc('Close')] = current_p
            if current_p > candles_df.iloc[-1]['High']: candles_df.iloc[-1, candles_df.columns.get_loc('High')] = current_p
            if current_p < candles_df.iloc[-1]['Low']: candles_df.iloc[-1, candles_df.columns.get_loc('Low')] = current_p

        # 2. Strategy Logic (Only if Active)
        if st.session_state.active:
            status_msg = run_strategy_logic(bot, settings, current_p)
        else:
            status_msg = "Paused (Monitoring Only)"

        # 3. Calculate Real-Time P/L
        # We manually calculate P/L using current price to ensure it updates every second
        real_time_pl = 0
        pos_display_data = []
        
        for p in positions:
            entry = p.get('openPrice', 0)
            size = p.get('size', 0)
            # Basic P/L estimate: (Current - Entry) * Size
            # Note: This is an estimate. Broker P/L includes fees/swap.
            # We prefer broker P/L if available, but for visual speed, this helps.
            broker_pl = p.get('profitAndLoss', 0)
            
            # Add to list
            pos_display_data.append({
                "Date": p.get('createdDate'), 
                "Size": size, 
                "Entry": entry, 
                "Live Price": current_p,
                "P/L": broker_pl
            })
            real_time_pl += broker_pl

        # 4. Update Metrics
        with metrics_ph.container():
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Live Price", f"${current_p}")
            
            if st.session_state.reference_price:
                ref = st.session_state.reference_price
                target = ref * (1 - (settings['drop_percent']/100))
                k2.metric(f"Ref / Target", f"${ref:.2f}", f"Buy: ${target:.2f}")
            else:
                k2.metric("Ref Price", "Waiting...")

            k3.metric("Invested", f"${st.session_state.total_invested}", f"Limit: ${settings['max_invest']}")
            # Use delta to show P/L color (Green/Red)
            k4.metric("Open P/L", f"${real_time_pl:.2f}", delta=real_time_pl)
            st.caption(f"Status: {status_msg}")

        # 5. Update Chart
        if not candles_df.empty:
            fig = go.Figure(data=[go.Candlestick(
                x=candles_df['Time'],
                open=candles_df['Open'], high=candles_df['High'],
                low=candles_df['Low'], close=candles_df['Close'],
                name="ETHUSD"
            )])
            if st.session_state.reference_price:
                fig.add_hline(y=st.session_state.reference_price, line_dash="dot", line_color="gray")
                target_p = st.session_state.reference_price * (1 - (settings['drop_percent']/100))
                fig.add_hline(y=target_p, line_dash="solid", line_color="green")

            fig.update_layout(height=450, margin=dict(l=0, r=0, t=0, b=0), xaxis_rangeslider_visible=False)
            chart_ph.plotly_chart(fig, use_container_width=True, key=f"chart_{time.time()}")

        # 6. Update Table
        if pos_display_data:
            table_ph.dataframe(pd.DataFrame(pos_display_data), use_container_width=True)
        else:
            table_ph.info("No Open Trades")

        # 7. Sleep 1s
        time.sleep(1)

if __name__ == "__main__":
    main()

import streamlit as st
import requests
import base64
import time
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
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

    def get_working_orders(self):
        url = f"{self.base_url}/api/v1/workingorders"
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json().get('workingOrders', [])
        except:
            return []
        return []

    def place_limit_order(self, epic, size, level, stop_loss, take_profit):
        url = f"{self.base_url}/api/v1/workingorders"
        headers = {
            'X-CAP-API-KEY': self.api_key,
            'CST': self.cst,
            'X-SECURITY-TOKEN': self.x_security_token,
            'Content-Type': 'application/json'
        }
        payload = {
            "epic": epic,
            "direction": "BUY",
            "type": "LIMIT",
            "level": level,
            "size": size,
            "stopLevel": stop_loss,
            "profitLevel": take_profit
        }
        resp = self.session.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            return True, resp.json()['dealReference']
        else:
            return False, resp.text

    def delete_order(self, deal_id):
        url = f"{self.base_url}/api/v1/workingorders/{deal_id}"
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        self.session.delete(url, headers=headers)

    def close_all_positions(self):
        # 1. Close Positions
        positions = self.get_positions()
        count_pos = 0
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        for p in positions:
            url = f"{self.base_url}/api/v1/positions/{p.get('dealId')}"
            if self.session.delete(url, headers=headers).status_code == 200: count_pos += 1
            
        # 2. Cancel Pending Orders
        orders = self.get_working_orders()
        count_ord = 0
        for o in orders:
            url = f"{self.base_url}/api/v1/workingorders/{o.get('dealId')}"
            if self.session.delete(url, headers=headers).status_code == 200: count_ord += 1
            
        return f"Closed {count_pos} Positions & Canceled {count_ord} Orders."

# ==========================================
# 2. STRATEGY ENGINE (LIMIT + COOLDOWN)
# ==========================================
def run_strategy_logic(bot, settings, current_price):
    if not current_price: return "Waiting for price..."
    
    now = datetime.now()
    epic = "ETHUSD"

    # 1. INITIAL SETUP
    if st.session_state.reference_price is None:
        st.session_state.reference_price = current_price
        st.session_state.last_ref_update = now
        st.session_state.last_pos_count = len(bot.get_positions())
        st.session_state.last_fill_time = None
        return f"🏁 Init Ref: ${current_price}"

    # 2. DETECT ORDER FILL
    current_positions = bot.get_positions()
    if len(current_positions) > st.session_state.last_pos_count:
        # Trade detected!
        st.session_state.total_invested += settings['invest_per_trade']
        st.session_state.reference_price = current_price 
        st.session_state.last_ref_update = now
        st.session_state.last_pos_count = len(current_positions)
        
        # START COOLDOWN
        st.session_state.last_fill_time = now
        st.toast("🚀 LIMIT FILLED! Cooldown Started (10m)...", icon="❄️")
        return "💰 Filled! Entering Cooldown..."

    st.session_state.last_pos_count = len(current_positions)

    # 3. CHECK REFERENCE UPDATES
    time_diff = (now - st.session_state.last_ref_update).total_seconds()
    timer_hit = time_diff >= 600
    price_moved_up = current_price > st.session_state.reference_price

    needs_update = False
    if price_moved_up or timer_hit:
        st.session_state.reference_price = current_price
        st.session_state.last_ref_update = now
        needs_update = True

    # 4. ORDER MANAGEMENT
    orders = bot.get_working_orders()
    
    # FIX: Use .get() to prevent KeyError if 'epic' is missing
    has_eth_order = any(o.get('epic') == epic for o in orders)

    # --- CHECK COOLDOWN ---
    if st.session_state.last_fill_time:
        seconds_since_fill = (now - st.session_state.last_fill_time).total_seconds()
        if seconds_since_fill < 600: # 10 Minutes
            remaining = int(600 - seconds_since_fill)
            mins = remaining // 60
            secs = remaining % 60
            
            # Remove any lingering orders during cooldown
            if has_eth_order:
                for o in orders:
                    if o.get('epic') == epic: bot.delete_order(o['dealId'])
            
            return f"❄️ Cooldown Active: {mins}m {secs}s"
        else:
            # Cooldown over
            st.session_state.last_fill_time = None

    # --- PLACE/UPDATE ORDERS ---
    if needs_update or not has_eth_order:
        # Cancel old ones first
        for o in orders:
            if o.get('epic') == epic: bot.delete_order(o['dealId'])
        
        # Calculate new Limit
        drop_pct = settings['drop_percent']
        target_price = round(st.session_state.reference_price * (1 - (drop_pct / 100)), 2)
        
        invest_amount = settings['invest_per_trade']
        leverage = settings['leverage']
        size = round((invest_amount * leverage) / target_price, 2)
        
        if size > 0:
            sl_dollar = settings['sl_amount']
            tp_dollar = settings['tp_amount']
            price_dist_sl = sl_dollar / size
            price_dist_tp = tp_dollar / size
            
            sl_price = round(target_price - price_dist_sl, 2)
            tp_price = round(target_price + price_dist_tp, 2)
            
            if st.session_state.total_invested < settings['max_invest']:
                success, ref = bot.place_limit_order(epic, size, target_price, sl_price, tp_price)
                if success:
                    st.toast(f"✅ Limit Set @ ${target_price}", icon="🎯")
                    return f"🎯 Limit Set @ {target_price}"
            else:
                return "🛑 Max Cap Reached"

    minutes_left = max(0, (600 - time_diff) / 60)
    return f"Monitoring... (Ref Reset in {int(minutes_left)}m)"

# ==========================================
# 3. UI
# ==========================================
def main():
    st.set_page_config(page_title="ETH LimitBot", page_icon="⚡", layout="wide")

    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalTradingBot(is_demo=True)
        st.session_state.connected = False
        st.session_state.active = False
        st.session_state.reference_price = None
        st.session_state.last_ref_update = datetime.now()
        st.session_state.total_invested = 0
        st.session_state.last_pos_count = 0
        st.session_state.last_fill_time = None

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
            
            with st.form("strategy_settings"):
                st.write("**Trigger**")
                drop_percent = st.number_input("Target Drop %", value=0.3, step=0.1)
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
            
            if st.session_state.active:
                if st.button("🛑 STOP BOT", type="primary"):
                    st.session_state.active = False
                    st.rerun()
            else:
                if st.button("▶️ START BOT", type="secondary"):
                    st.session_state.active = True
                    st.rerun()
            
            if st.button("🚨 CLOSE ALL", type="primary"):
                with st.spinner("Cleaning up..."):
                    res = bot.close_all_positions()
                    st.session_state.total_invested = 0
                    st.warning(res)
                    time.sleep(1)
            
            if st.button("Reset Memory"):
                st.session_state.reference_price = None
                st.session_state.total_invested = 0
                st.session_state.last_fill_time = None
                st.rerun()

    # --- MAIN DASHBOARD ---
    st.title("⚡ ETH/USD Limit Order Bot")

    if not st.session_state.connected:
        st.info("👈 Connect to start.")
        st.stop()

    metrics_ph = st.empty()
    chart_ph = st.empty()
    table_ph = st.empty()

    # --- MAIN LOOP ---
    while True:
        # 1. Fetch Data
        candles_df = bot.get_candles("ETHUSD")
        current_p = bot.get_price("ETHUSD")
        positions = bot.get_positions()
        orders = bot.get_working_orders()
        
        # Patch Chart
        if not candles_df.empty and current_p:
            candles_df.iloc[-1, candles_df.columns.get_loc('Close')] = current_p
            if current_p > candles_df.iloc[-1]['High']: candles_df.iloc[-1, candles_df.columns.get_loc('High')] = current_p
            if current_p < candles_df.iloc[-1]['Low']: candles_df.iloc[-1, candles_df.columns.get_loc('Low')] = current_p

        # 2. Strategy Logic
        if st.session_state.active:
            status_msg = run_strategy_logic(bot, settings, current_p)
        else:
            status_msg = "Paused"

        # 3. Real-Time P/L
        real_time_pl_total = 0
        display_data = []

        # Process Active Positions
        for p in positions:
            entry = p.get('openPrice', 0)
            size = p.get('size', 0)
            if current_p and entry:
                trade_pl = (current_p - entry) * size
            else:
                trade_pl = 0
            
            real_time_pl_total += trade_pl
            
            display_data.append({
                "Type": "ACTIVE TRADE",
                "Level/Entry": entry, 
                "Size": size, 
                "P/L": f"${trade_pl:.2f}"
            })
        
        # Process Pending Orders (FIXED KEY ERROR)
        pending_price = 0
        # Use .get() safely
        eth_orders = [o for o in orders if o.get('epic') == 'ETHUSD']
        if eth_orders: pending_price = eth_orders[0].get('level', 0)

        for o in orders:
             display_data.append({
                "Type": "PENDING LIMIT",
                "Level/Entry": o.get('level'), 
                "Size": o.get('size'), 
                "P/L": "-"
            })

        # 4. Metrics Update
        with metrics_ph.container():
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Live Price", f"${current_p}")
            k2.metric("Target (Limit)", f"${pending_price if pending_price > 0 else 'None'}")
            k3.metric("Invested", f"${st.session_state.total_invested}", f"Limit: ${settings['max_invest']}")
            k4.metric("Open P/L", f"${real_time_pl_total:.2f}", delta=real_time_pl_total)
            st.caption(f"Status: {status_msg}")

        # 5. Chart Update
        if not candles_df.empty:
            fig = go.Figure(data=[go.Candlestick(
                x=candles_df['Time'],
                open=candles_df['Open'], high=candles_df['High'],
                low=candles_df['Low'], close=candles_df['Close'],
                name="ETHUSD"
            )])
            
            if pending_price > 0:
                fig.add_hline(y=pending_price, line_dash="solid", line_color="orange", annotation_text="PENDING ORDER")
            elif st.session_state.last_fill_time:
                fig.add_annotation(text="❄️ COOLDOWN", x=candles_df.iloc[-1]['Time'], y=current_p, showarrow=True, arrowhead=1)
            elif st.session_state.reference_price:
                 target_p = st.session_state.reference_price * (1 - (settings['drop_percent']/100))
                 fig.add_hline(y=target_p, line_dash="dot", line_color="gray", annotation_text="Next Target")

            fig.update_layout(height=450, margin=dict(l=0, r=0, t=0, b=0), xaxis_rangeslider_visible=False)
            chart_ph.plotly_chart(fig, use_container_width=True, key=f"chart_{time.time()}")

        # 6. Table Update
        if display_data:
            table_ph.dataframe(pd.DataFrame(display_data), use_container_width=True)
        else:
            table_ph.info("No Active Trades or Pending Orders")

        time.sleep(1)

if __name__ == "__main__":
    main()

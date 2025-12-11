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

    def get_account_info(self):
        url = f"{self.base_url}/api/v1/accounts"
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        try:
            resp = self.session.get(url, headers=headers)
            if resp.status_code == 200:
                accounts = resp.json().get('accounts', [])
                if accounts:
                    return accounts[0]
        except:
            return {}
        return {}

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

    # --- UPDATED CLOSE ALL FUNCTION ---
    def close_all_positions(self):
        headers = {'X-CAP-API-KEY': self.api_key, 'CST': self.cst, 'X-SECURITY-TOKEN': self.x_security_token}
        
        # 1. Close Open Trades
        positions = self.get_positions()
        count_pos = 0
        for p in positions:
            url = f"{self.base_url}/api/v1/positions/{p.get('dealId')}"
            if self.session.delete(url, headers=headers).status_code == 200:
                count_pos += 1
            time.sleep(0.1) # Buffer
            
        # 2. Cancel Pending Orders
        orders = self.get_working_orders()
        count_ord = 0
        for o in orders:
            url = f"{self.base_url}/api/v1/workingorders/{o.get('dealId')}"
            if self.session.delete(url, headers=headers).status_code == 200:
                count_ord += 1
            time.sleep(0.1) # Buffer
            
        return f"✅ Closed {count_pos} Positions & Canceled {count_ord} Orders."

# ==========================================
# 2. STRATEGY LOGIC (Triggered Only Every 10m)
# ==========================================
def execute_strategy_update(bot, settings, current_price, account_funds):
    epic = "ETHUSD"
    
    # 1. Funds Check
    if account_funds < 300:
        return "🛑 LOW FUNDS (<300)"

    # 2. Clean up Old Orders
    orders = bot.get_working_orders()
    deleted = False
    for o in orders:
        if o.get('epic') == epic:
            bot.delete_order(o['dealId'])
            deleted = True
    
    if deleted: 
        time.sleep(1) # Wait for deletion to register

    # 3. Set New Reference & Target
    st.session_state.reference_price = current_price
    drop_pct = settings['drop_percent']
    target_price = round(current_price * (1 - (drop_pct / 100)), 2)
    
    # 4. Calculate Size
    invest_amount = settings['invest_per_trade']
    leverage = settings['leverage']
    size = round((invest_amount * leverage) / target_price, 2)
    
    if size <= 0: return "❌ Size Error"

    # 5. Risk Calc
    sl_dollar = settings['sl_amount']
    tp_dollar = settings['tp_amount']
    price_dist_sl = sl_dollar / size
    price_dist_tp = tp_dollar / size
    
    sl_price = round(target_price - price_dist_sl, 2)
    tp_price = round(target_price + price_dist_tp, 2)

    # 6. Place New Order
    if st.session_state.total_invested < settings['max_invest']:
        success, ref = bot.place_limit_order(epic, size, target_price, sl_price, tp_price)
        if success:
            st.toast(f"✅ New Limit Set: ${target_price}", icon="🎯")
            return f"🎯 Limit Set: ${target_price}"
        else:
            return f"❌ Error: {ref}"
    else:
        return "🛑 Max Cap"

# ==========================================
# 3. UI
# ==========================================
def main():
    st.set_page_config(page_title="ETH LimitBot", page_icon="⚡", layout="wide")

    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalTradingBot(is_demo=True)
        st.session_state.connected = False
        st.session_state.active = False
        
        # Strategy State
        st.session_state.reference_price = None
        st.session_state.total_invested = 0
        st.session_state.last_pos_count = 0
        
        # TIME CONTROL
        st.session_state.next_update_time = None 
        st.session_state.status_msg = "Idle"

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
                    st.session_state.next_update_time = None
                    st.rerun()
            else:
                if st.button("▶️ START BOT", type="secondary"):
                    st.session_state.active = True
                    # Force update immediately on start
                    st.session_state.next_update_time = datetime.now()
                    st.rerun()
            
            # --- UPDATED CLOSE ALL BUTTON ---
            if st.button("🚨 CLOSE ALL (Trades + Orders)", type="primary"):
                with st.spinner("Cancelling everything..."):
                    res = bot.close_all_positions()
                    st.session_state.total_invested = 0
                    st.warning(res)
                    time.sleep(2) # Give it time to display
            
            if st.button("Reset Memory"):
                st.session_state.reference_price = None
                st.session_state.total_invested = 0
                st.session_state.next_update_time = None
                st.rerun()

    # --- MAIN DASHBOARD ---
    st.title("⚡ ETH/USD 10m-Cycle Bot")

    if not st.session_state.connected:
        st.info("👈 Connect to start.")
        st.stop()

    metrics_ph = st.empty()
    account_ph = st.empty()
    chart_ph = st.empty()
    tab1, tab2 = st.tabs(["🔴 Live Monitor", "📜 Trade History"])

    # --- MAIN LOOP (1 Second) ---
    while True:
        # 1. Fetch High-Speed Data (Every second)
        candles_df = bot.get_candles("ETHUSD")
        current_p = bot.get_price("ETHUSD")
        positions = bot.get_positions()
        orders = bot.get_working_orders()
        account_data = bot.get_account_info()
        
        # Account Parsing
        balance_obj = account_data.get('balance', {})
        equity = balance_obj.get('equity', 0)
        available = balance_obj.get('available', 0)
        total_pl_acc = balance_obj.get('profitLoss', 0)

        # Patch Chart with real-time tick
        if not candles_df.empty and current_p:
            candles_df.iloc[-1, candles_df.columns.get_loc('Close')] = current_p
            if current_p > candles_df.iloc[-1]['High']: candles_df.iloc[-1, candles_df.columns.get_loc('High')] = current_p
            if current_p < candles_df.iloc[-1]['Low']: candles_df.iloc[-1, candles_df.columns.get_loc('Low')] = current_p

        # ==========================================
        # CRITICAL: STRATEGY LOGIC (10 MINUTE CYCLE)
        # ==========================================
        if st.session_state.active and current_p:
            now = datetime.now()
            
            # CONDITION 1: Time to Update (Every 10 mins)
            time_hit = st.session_state.next_update_time and now >= st.session_state.next_update_time
            
            # CONDITION 2: Trade Filled (Positions increased)
            filled = len(positions) > st.session_state.last_pos_count
            
            if time_hit or filled:
                if filled: 
                    st.toast("💰 Trade Filled! Resetting Cycle...", icon="🚀")
                    st.session_state.total_invested += settings['invest_per_trade']
                
                # EXECUTE ORDER SWAP
                st.session_state.status_msg = execute_strategy_update(bot, settings, current_p, available)
                
                # SET NEXT UPDATE TIME (Now + 10 mins)
                st.session_state.next_update_time = now + timedelta(minutes=10)
                st.session_state.last_pos_count = len(positions)
            
            # Update Countdown Msg
            if st.session_state.next_update_time:
                remaining = (st.session_state.next_update_time - now).total_seconds()
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                countdown_msg = f"(Next Update: {mins}m {secs}s)"
            else:
                countdown_msg = "Starting..."
        else:
            countdown_msg = "Paused"

        # ==========================================
        # DISPLAY LOGIC (Every Second)
        # ==========================================
        
        # P/L Calc
        real_time_pl_total = 0
        active_trades_data = []

        for p in positions:
            entry = p.get('openPrice', 0)
            size = p.get('size', 0)
            if current_p and entry: trade_pl = (current_p - entry) * size
            else: trade_pl = 0
            real_time_pl_total += trade_pl
            active_trades_data.append({"Date": p.get('createdDate'), "Entry": entry, "Size": size, "Live P/L": f"${trade_pl:.2f}"})
        
        pending_price = 0
        eth_orders = [o for o in orders if o.get('epic') == 'ETHUSD']
        if eth_orders: pending_price = eth_orders[0].get('level', 0)

        for o in orders:
             active_trades_data.append({"Date": o.get('createdDate'), "Entry": f"LIMIT @ {o.get('level')}", "Size": o.get('size'), "Live P/L": "PENDING"})

        # Metrics
        with metrics_ph.container():
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Live Price", f"${current_p}")
            k2.metric("Pending Limit", f"${pending_price if pending_price > 0 else 'None'}")
            k3.metric("Invested", f"${st.session_state.total_invested}", f"Limit: ${settings['max_invest']}")
            k4.metric("Open P/L", f"${real_time_pl_total:.2f}", delta=real_time_pl_total)
            
        with account_ph.container():
            a1, a2, a3 = st.columns(3)
            a1.metric("Equity", f"€{equity:,.2f}")
            col = "normal" if available >= 300 else "inverse"
            a2.metric("Available Funds", f"€{available:,.2f}", delta_color=col)
            a3.metric("Account Status", f"{st.session_state.status_msg} {countdown_msg}")

        # Chart
        if not candles_df.empty:
            fig = go.Figure(data=[go.Candlestick(x=candles_df['Time'], open=candles_df['Open'], high=candles_df['High'], low=candles_df['Low'], close=candles_df['Close'], name="ETHUSD")])
            for p in positions:
                if p.get('openPrice'): fig.add_hline(y=p.get('openPrice'), line_dash="solid", line_color="blue", annotation_text="OPEN")
            
            # Show Target
            if st.session_state.reference_price:
                 target_p = st.session_state.reference_price * (1 - (settings['drop_percent']/100))
                 fig.add_hline(y=target_p, line_dash="dot", line_color="gray", annotation_text="Target")

            fig.update_layout(height=450, margin=dict(l=0, r=0, t=0, b=0), xaxis_rangeslider_visible=False)
            chart_ph.plotly_chart(fig, use_container_width=True, key=f"chart_{time.time()}")

        with tab1:
            if active_trades_data: st.dataframe(pd.DataFrame(active_trades_data), use_container_width=True)
            else: st.info("No Active Trades")
        
        with tab2: st.caption("Manual Refresh Required")

        time.sleep(1)

if __name__ == "__main__":
    main()

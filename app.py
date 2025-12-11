import streamlit as st
import requests
import base64
import pandas as pd
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

# ==========================================
# 1. CAPITAL.COM API CLIENT CLASS
# ==========================================
class CapitalTradingBot:
    def __init__(self, is_demo=True):
        # Load credentials safely from Streamlit Secrets
        try:
            self.api_key = st.secrets["capital_com"]["api_key"]
            self.login = st.secrets["capital_com"]["email"]
            self.password = st.secrets["capital_com"]["password"]
        except Exception as e:
            st.error("Missing secrets! Make sure .streamlit/secrets.toml exists.")
            st.stop()
        
        # Set Environment URL
        if is_demo:
            self.base_url = "https://demo-api-capital.backend-capital.com"
            self.env_name = "DEMO"
        else:
            self.base_url = "https://api-capital.backend-capital.com"
            self.env_name = "LIVE"
            
        self.session = requests.Session()
        # Auth tokens to be filled after login
        self.cst = None
        self.x_security_token = None
        # Account details
        self.active_account_id = None
        self.account_list = []

    def _get_encryption_key(self):
        """Step 1: Get API Encryption Key"""
        url = f"{self.base_url}/api/v1/session/encryptionKey"
        headers = {'X-CAP-API-KEY': self.api_key}
        resp = self.session.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data['encryptionKey'], int(data['timeStamp'])

    def _encrypt_password(self, encryption_key_b64, timestamp):
        """Step 2: Encrypt Password (RSA + Base64 Double Encoding)"""
        input_str = f"{self.password}|{timestamp}"
        input_bytes = base64.b64encode(input_str.encode('utf-8'))
        
        key_bytes = base64.b64decode(encryption_key_b64)
        public_key = RSA.import_key(key_bytes)
        
        cipher = PKCS1_v1_5.new(public_key)
        encrypted_bytes = cipher.encrypt(input_bytes)
        
        return base64.b64encode(encrypted_bytes).decode('utf-8')

    def connect(self):
        """Step 3: Log in and Select Account 1"""
        status = st.empty()
        status.info(f"Connecting to Capital.com [{self.env_name}]...")
        
        try:
            # A. Get Key
            enc_key, timestamp = self._get_encryption_key()
            
            # B. Encrypt
            encrypted_pw = self._encrypt_password(enc_key, timestamp)
            
            # C. Login Request
            url = f"{self.base_url}/api/v1/session"
            payload = {
                "identifier": self.login,
                "password": encrypted_pw,
                "encryptedPassword": True
            }
            headers = {'X-CAP-API-KEY': self.api_key, 'Content-Type': 'application/json'}
            
            response = self.session.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                # Capture Session Tokens
                self.cst = response.headers.get('CST')
                self.x_security_token = response.headers.get('X-SECURITY-TOKEN')
                
                # Capture Account Data
                data = response.json()
                self.active_account_id = data.get('currentAccountId')
                self.account_list = data.get('accounts', [])
                
                status.success("Login Successful!")
                return True
            else:
                status.error(f"Login Failed: {response.text}")
                return False

        except Exception as e:
            status.error(f"Connection Error: {e}")
            return False

    def get_account_details(self, account_index=0):
        """Retrieve details for a specific account index from the list"""
        if not self.account_list:
            return None
        
        # Grab 'Account 1' (Index 0)
        if len(self.account_list) > account_index:
            return self.account_list[account_index]
        return None

    def get_price_snapshot(self, epic):
        """Fetch current market price"""
        if not self.cst: return None
        
        url = f"{self.base_url}/api/v1/markets/{epic}"
        headers = {
            'X-CAP-API-KEY': self.api_key,
            'CST': self.cst,
            'X-SECURITY-TOKEN': self.x_security_token
        }
        
        resp = self.session.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('snapshot', {})
        return None

# ==========================================
# 2. STREAMLIT UI LAYOUT
# ==========================================
def main():
    st.set_page_config(page_title="CapBot", page_icon="📈")
    
    st.title("🤖 Capital.com Bot Manager")
    st.write("Target: **Demo Environment**")

    # Initialize Bot Logic (Using Secrets)
    # We use st.session_state to keep the bot alive across re-runs
    if 'bot' not in st.session_state:
        st.session_state.bot = CapitalTradingBot(is_demo=True)
        st.session_state.is_connected = False

    # CONNECT BUTTON
    if not st.session_state.is_connected:
        if st.button("🚀 Connect to Broker"):
            if st.session_state.bot.connect():
                st.session_state.is_connected = True
                st.rerun() # Refresh to show dashboard
    
    # DASHBOARD (Only shows after connection)
    else:
        bot = st.session_state.bot
        
        # --- SECTION: ACCOUNT INFO ---
        st.divider()
        st.subheader("🏦 Account Status: Account 1")
        
        # Get details for the first account (Index 0)
        account_data = bot.get_account_details(account_index=0)
        
        if account_data:
            c1, c2, c3 = st.columns(3)
            
            # Extract financial data
            balance = account_data.get('balance', {}).get('balance', 0)
            equity = account_data.get('balance', {}).get('equity', 0)
            pnl = account_data.get('balance', {}).get('profitLoss', 0)
            currency = account_data.get('currency', '$')
            name = account_data.get('accountName', 'Unknown')

            c1.metric("Account Name", name)
            c2.metric("Balance", f"{balance:,.2f} {currency}")
            c3.metric("Equity", f"{equity:,.2f} {currency}", delta=f"{pnl:,.2f}")
            
            with st.expander("View Full Raw Account Data"):
                st.json(account_data)
        else:
            st.warning("No accounts found in this profile.")

        # --- SECTION: MARKET WATCH ---
        st.divider()
        st.subheader("📊 Live Market Watch")
        
        # Define assets to watch
        assets = ["BTCUSD", "EURUSD", "US500"]
        
        cols = st.columns(len(assets))
        
        for idx, asset in enumerate(assets):
            snapshot = bot.get_price_snapshot(asset)
            if snapshot:
                bid = snapshot.get('bid')
                offer = snapshot.get('offer')
                spread = round(offer - bid, 2)
                
                with cols[idx]:
                    st.markdown(f"#### {asset}")
                    st.write(f"**Bid:** {bid}")
                    st.write(f"**Ask:** {offer}")
                    st.caption(f"Spread: {spread}")
            else:
                cols[idx].error(f"{asset} Error")

        # --- DISCONNECT ---
        st.divider()
        if st.button("Logout / Reset"):
            st.session_state.clear()
            st.rerun()

if __name__ == "__main__":
    main()

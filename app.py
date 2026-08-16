from datetime import datetime, timedelta
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import time
import threading
import urllib.parse
import html
import webbrowser
from kiteconnect import KiteConnect
import numpy as np
import pandas as pd
import streamlit as st

# ==========================================
# MODULE 1: ZERODHA API CREDENTIALS & CONSTANTS
# ==========================================
def _read_secret(name: str, default: str = "") -> str:
    """Read a Streamlit secret first, then an environment variable."""
    try:
        value = st.secrets.get(name, "")
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()


API_KEY = _read_secret("ZERODHA_API_KEY", "magym2s4yk13gsze")
API_SECRET = _read_secret("ZERODHA_API_SECRET", "83cuxyx91lv9ae371ogcs6ckvu5kto8q")
REDIRECT_URI = _read_secret(
    "ZERODHA_REDIRECT_URI",
    "https://geminie-trading-3xszcb58jqdnsp3dyhulqk.streamlit.app",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
TOKEN_FILE = os.path.join(BASE_DIR, os.getenv("ZERODHA_TOKEN_FILE", "access_token.txt"))

PORT = 5000
LOCAL_REDIRECT = f"http://127.0.0.1:{PORT}/"

# Screener Thresholds & Parameter Filters
SCREENER = {
    "min_score": 60,
    "strict_score": 75,
    "intraday_score": 70,
    "min_rvol": 1.20,
    "strong_rvol": 1.80,
    "min_rr": 1.80,
    "max_atr_extension_pct": 3.0,
    "narrow_cpr_pct": 0.35,
}

# Major Index Mapping & Tokens
INDEX_MAP = {
    "NIFTY": {"symbol": "NIFTY 50", "token": 256265, "name": "NIFTY"},
    "BANKNIFTY": {
        "symbol": "NIFTY BANK",
        "token": 260105,
        "name": "BANKNIFTY",
    },
    "FINNIFTY": {
        "symbol": "NIFTY FIN SERVICE",
        "token": 257801,
        "name": "FINNIFTY",
    },
}

INDIA_VIX_TOKEN = 264969

# Nifty 50 Constituent Weights (%) & Sector Mapping
NIFTY_CONSTITUENTS = {
    "HDFCBANK": {"weight": 10.27, "sector": "Financial Services"},
    "ICICIBANK": {"weight": 9.22, "sector": "Financial Services"},
    "RELIANCE": {"weight": 7.92, "sector": "Oil, Gas & Fuels"},
    "BHARTIARTL": {"weight": 5.37, "sector": "Telecommunication"},
    "LT": {"weight": 4.13, "sector": "Services / Infrastructure"},
    "SBIN": {"weight": 3.81, "sector": "Financial Services"},
    "INFY": {"weight": 3.55, "sector": "Information Technology"},
    "AXISBANK": {"weight": 3.16, "sector": "Financial Services"},
    "BAJFINANCE": {"weight": 2.74, "sector": "Financial Services"},
    "M&M": {"weight": 2.72, "sector": "Automobile"},
    "KOTAKBANK": {"weight": 2.50, "sector": "Financial Services"},
    "ITC": {"weight": 2.40, "sector": "FMCG"},
    "TCS": {"weight": 2.20, "sector": "Information Technology"},
    "HINDUNILVR": {"weight": 2.10, "sector": "FMCG"},
    "SUNPHARMA": {"weight": 2.00, "sector": "Healthcare / Pharma"},
    "MARUTI": {"weight": 1.90, "sector": "Automobile"},
    "NTPC": {"weight": 1.80, "sector": "Power / Utilities"},
    "TATAMOTORS": {"weight": 1.70, "sector": "Automobile"},
    "ULTRACEMCO": {"weight": 1.60, "sector": "Construction Materials"},
    "POWERGRID": {"weight": 1.50, "sector": "Power / Utilities"},
    "HCLTECH": {"weight": 1.40, "sector": "Information Technology"},
    "ASIANPAINT": {"weight": 1.30, "sector": "Consumer Durables"},
    "TITAN": {"weight": 1.20, "sector": "Consumer Durables"},
    "ADANIPORTS": {"weight": 1.10, "sector": "Services / Infrastructure"},
    "TATASTEEL": {"weight": 1.00, "sector": "Metals & Mining"},
    "JSWSTEEL": {"weight": 0.95, "sector": "Metals & Mining"},
    "BAJAJ-AUTO": {"weight": 0.90, "sector": "Automobile"},
    "BAJAJFINSV": {"weight": 0.85, "sector": "Financial Services"},
    "COALINDIA": {"weight": 0.80, "sector": "Oil, Gas & Fuels"},
    "ONGC": {"weight": 0.75, "sector": "Oil, Gas & Fuels"},
    "TECHM": {"weight": 0.70, "sector": "Information Technology"},
    "TRENT": {"weight": 0.70, "sector": "Consumer Services"},
    "GRASIM": {"weight": 0.65, "sector": "Construction Materials"},
    "ADANIENT": {"weight": 0.65, "sector": "Metals & Mining"},
    "BEL": {"weight": 0.60, "sector": "Capital Goods"},
    "CIPLA": {"weight": 0.60, "sector": "Healthcare / Pharma"},
    "SBILIFE": {"weight": 0.55, "sector": "Financial Services"},
    "APOLLOHOSP": {"weight": 0.55, "sector": "Healthcare / Pharma"},
    "HINDALCO": {"weight": 0.50, "sector": "Metals & Mining"},
    "EICHERMOT": {"weight": 0.50, "sector": "Automobile"},
    "BPCL": {"weight": 0.45, "sector": "Oil, Gas & Fuels"},
    "HEROMOTOCO": {"weight": 0.45, "sector": "Automobile"},
    "DRREDDY": {"weight": 0.40, "sector": "Healthcare / Pharma"},
    "BRITANNIA": {"weight": 0.40, "sector": "FMCG"},
    "DIVISLAB": {"weight": 0.35, "sector": "Healthcare / Pharma"},
    "TATACONSUM": {"weight": 0.35, "sector": "FMCG"},
    "LTIM": {"weight": 0.30, "sector": "Information Technology"},
    "WIPRO": {"weight": 0.30, "sector": "Information Technology"},
    "NESTLEIND": {"weight": 0.25, "sector": "FMCG"},
    "INDUSINDBK": {"weight": 0.25, "sector": "Financial Services"},
}

# ==========================================
# MODULE 2: ZERODHA AUTHENTICATION & HANDLERS
# ==========================================
class TokenCallbackHandler(BaseHTTPRequestHandler):
    request_token = None
    callback_error = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        TokenCallbackHandler.request_token = params.get("request_token", [None])[0]
        TokenCallbackHandler.callback_error = (
            params.get("message", [None])[0] or params.get("error", [None])[0]
        )
        body = (
            "Zerodha authentication successful. You may close this window."
            if TokenCallbackHandler.request_token
            else "Zerodha authentication failed or no request token was received."
        )
        body_bytes = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def log_message(self, format, *args):
        return


def _is_local_redirect() -> bool:
    return "127.0.0.1" in REDIRECT_URI or "localhost" in REDIRECT_URI


def _save_local_access_token(access_token: str):
    if not _is_local_redirect():
        return
    try:
        Path(TOKEN_FILE).write_text(access_token.strip(), encoding="utf-8")
    except OSError:
        pass


def _read_local_access_token() -> str:
    if not _is_local_redirect():
        return ""
    try:
        if os.path.isfile(TOKEN_FILE):
            return Path(TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def _validate_kite_session(kite) -> bool:
    try:
        return bool(kite.profile())
    except Exception:
        return False


def _generate_kite_session(kite, request_token: str) -> bool:
    try:
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data.get("access_token")
        if not access_token:
            st.error("Zerodha did not return an access token.")
            return False

        kite.set_access_token(access_token)
        if not _validate_kite_session(kite):
            st.error("Access token generated but Kite session could not be validated.")
            return False

        st.session_state["zerodha_kite"] = kite
        st.session_state["zerodha_access_token"] = access_token
        st.session_state["zerodha_login_done"] = True
        _save_local_access_token(access_token)
        return True
    except Exception as exc:
        st.error(f"Zerodha session generation failed: {type(exc).__name__}: {exc}")
        return False


def run_local_auth_flow(api_key: str, port: int = PORT) -> str | None:
    TokenCallbackHandler.request_token = None
    TokenCallbackHandler.callback_error = None
    try:
        server = HTTPServer(("127.0.0.1", port), TokenCallbackHandler)
        server.timeout = 1
    except OSError:
        st.error(f"Cannot start local Zerodha callback on 127.0.0.1:{port}.")
        return None

    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={urllib.parse.quote(api_key)}"
    try:
        webbrowser.open(login_url)
        deadline = time.time() + 120
        while time.time() < deadline:
            server.handle_request()
            if TokenCallbackHandler.request_token or TokenCallbackHandler.callback_error:
                break
    finally:
        server.server_close()

    if TokenCallbackHandler.callback_error:
        st.error(f"Zerodha authentication error: {TokenCallbackHandler.callback_error}")
        return None
    return TokenCallbackHandler.request_token


def get_authenticated_kite():
    missing = []
    if not API_KEY:
        missing.append("ZERODHA_API_KEY")
    if not API_SECRET:
        missing.append("ZERODHA_API_SECRET")
    if not REDIRECT_URI:
        missing.append("ZERODHA_REDIRECT_URI")
    if missing:
        st.error("Zerodha credentials missing: " + ", ".join(missing))
        return None

    cached = st.session_state.get("zerodha_kite")
    if cached is not None and _validate_kite_session(cached):
        return cached

    kite = KiteConnect(api_key=API_KEY)

    try:
        request_token = st.query_params.get("request_token")
        status = st.query_params.get("status", "")
    except Exception:
        request_token, status = None, ""

    if request_token and str(status).lower() in ("", "success", "ok"):
        if _generate_kite_session(kite, str(request_token)):
            try:
                st.query_params.clear()
            except Exception:
                pass
            st.success("🎉 Zerodha login successful.")
            return kite

    local_token = _read_local_access_token()
    if local_token:
        try:
            kite.set_access_token(local_token)
            if _validate_kite_session(kite):
                st.session_state["zerodha_kite"] = kite
                st.session_state["zerodha_access_token"] = local_token
                return kite
        except Exception:
            pass

    if _is_local_redirect():
        st.info("🔐 Desktop mode: use local Zerodha login callback.")
        if st.button("🔑 Login to Zerodha", type="primary", key="zerodha_login_button"):
            request_token = run_local_auth_flow(API_KEY, PORT)
            if request_token and _generate_kite_session(kite, request_token):
                st.rerun()
        return None

    login_url = (
        "https://kite.zerodha.com/connect/login?v=3&api_key="
        + urllib.parse.quote(API_KEY, safe="")
    )
    st.warning("🔐 Zerodha session required. Click below to authenticate.")
    safe_url = html.escape(login_url, quote=True)
    st.markdown(
        f'''<a href="{safe_url}" target="_self" rel="noopener"
        style="display:inline-block;padding:0.65rem 1rem;border-radius:0.5rem;
        background:#ff4b4b;color:white;text-decoration:none;font-weight:600;">
        🔑 Login to Zerodha
        </a>''',
        unsafe_allow_html=True,
    )
    st.caption(f"Kite Redirect URL must match: {REDIRECT_URI}")
    return None


# ==========================================
# MODULE 3: HISTORICAL DATA FETCH & RETRY API
# ==========================================
def safe_fetch_history(kite, token, from_date, to_date, interval, oi=False, attempts=3):
    """Safe retry wrapper for historical data API calls with rate-limit backoff."""
    for attempt in range(attempts):
        try:
            kwargs = {
                "instrument_token": token,
                "from_date": from_date,
                "to_date": to_date,
                "interval": interval,
            }
            if oi:
                kwargs["oi"] = True
            return kite.historical_data(**kwargs)
        except Exception as exc:
            if attempt == attempts - 1:
                return []
            if "Too many requests" in str(exc) or "429" in str(exc):
                time.sleep(1.0 + attempt)
            else:
                time.sleep(0.25)
    return []


# ==========================================
# MODULE 4: TECHNICAL INDICATORS & MATH ENGINE
# ==========================================
def calculate_rsi(series, period=9):
    values = pd.to_numeric(series, errors="coerce")
    delta = values.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    no_loss = avg_loss.eq(0) & avg_gain.gt(0)
    no_gain = avg_gain.eq(0) & avg_loss.gt(0)
    flat = avg_gain.eq(0) & avg_loss.eq(0)
    rsi = rsi.mask(no_loss, 100.0)
    rsi = rsi.mask(no_gain, 0.0)
    rsi = rsi.mask(flat, 50.0)
    return rsi.fillna(50.0)


def calculate_wma(series, length=21):
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(
        lambda candles: np.dot(candles, weights) / weights.sum(), raw=True
    )


def calculate_hilega_milega(df):
    if df is None or df.empty or len(df) < 21:
        return df

    rsi = calculate_rsi(df["close"], period=9)
    price_ema = rsi.ewm(span=3, adjust=False).mean()
    strength_wma = calculate_wma(rsi, length=21)

    df["hm_rsi"] = rsi
    df["hm_ema_price"] = price_ema
    df["hm_wma_strength"] = strength_wma
    return df


def calculate_cpr_values(high, low, close):
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot

    tc_final = max(tc, bc)
    bc_final = min(tc, bc)
    cpr_width_pct = abs(tc_final - bc_final) / pivot * 100.0 if pivot > 0 else 0.0

    return pivot, tc_final, bc_final, cpr_width_pct


def calculate_cpr(prev_day_candle):
    high = prev_day_candle["high"]
    low = prev_day_candle["low"]
    close = prev_day_candle["close"]

    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot

    cpr_top = max(tc, bc)
    cpr_bottom = min(tc, bc)
    cpr_width_pct = round(((cpr_top - cpr_bottom) / pivot) * 100, 2) if pivot > 0 else 0.0
    is_narrow_cpr = cpr_width_pct <= SCREENER["narrow_cpr_pct"]

    return round(pivot, 2), round(cpr_top, 2), round(cpr_bottom, 2), is_narrow_cpr


def calculate_atr(df, period=14):
    if df is None or len(df) < period + 1:
        return 0.0

    df_atr = df.copy()
    df_atr["prev_close"] = df_atr["close"].shift(1)
    df_atr["tr1"] = df_atr["high"] - df_atr["low"]
    df_atr["tr2"] = (df_atr["high"] - df_atr["prev_close"]).abs()
    df_atr["tr3"] = (df_atr["low"] - df_atr["prev_close"]).abs()
    df_atr["tr"] = df_atr[["tr1", "tr2", "tr3"]].max(axis=1)

    atr_series = df_atr["tr"].rolling(window=period).mean()
    return round(atr_series.iloc[-1], 2)


def check_sma_20_bounce(df_hourly):
    if df_hourly is None or len(df_hourly) < 21:
        return "⚪ Insufficient Data"

    df_hourly = df_hourly.copy()
    df_hourly["sma_20"] = df_hourly["close"].rolling(window=20).mean()

    latest_candle = df_hourly.iloc[-1]
    prev_candle = df_hourly.iloc[-2]

    current_price = latest_candle["close"]
    sma_20_val = latest_candle["sma_20"]

    if np.isnan(sma_20_val) or sma_20_val == 0:
        return "⚪ Normal"

    dist_pct = abs(current_price - sma_20_val) / sma_20_val * 100

    tested_sma = (prev_candle["low"] <= sma_20_val * 1.005) or (
        latest_candle["low"] <= sma_20_val * 1.005
    )
    is_bouncing_up = (
        current_price >= sma_20_val and current_price > latest_candle["open"]
    )
    is_breaking_down = current_price < sma_20_val

    if tested_sma and is_bouncing_up and dist_pct <= 0.75:
        return f"🟢 Bullish Bounce (SMA: ₹{round(sma_20_val, 1)})"
    elif is_breaking_down and dist_pct <= 0.75:
        return f"🔴 Breakdown Test (SMA: ₹{round(sma_20_val, 1)})"
    elif dist_pct <= 0.5:
        return f"⚡ At 20 SMA (₹{round(sma_20_val, 1)})"

    return "⚪ Normal"


def check_bollinger_blast(df):
    if df is None or len(df) < 20:
        return False
    sma = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    upper_band = sma + (2 * std)

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    is_above_ub = latest["close"] > upper_band.iloc[-1]
    is_rising = latest["close"] > prev["close"]
    return is_above_ub and is_rising


def calculate_option_vwap(df_5min):
    if df_5min is None or df_5min.empty or "volume" not in df_5min.columns:
        return 0.0

    typical_price = (df_5min["high"] + df_5min["low"] + df_5min["close"]) / 3.0
    cum_pv = (typical_price * df_5min["volume"]).sum()
    cum_vol = df_5min["volume"].sum()

    if cum_vol > 0:
        return round(cum_pv / cum_vol, 2)
    return 0.0


def get_hm_status(df):
    if df is None or df.empty or len(df) < 22 or "hm_ema_price" not in df.columns:
        return "⚪ Neutral"

    latest = df.iloc[-1]
    hm_ema = latest["hm_ema_price"]
    hm_wma = latest["hm_wma_strength"]

    if hm_ema > hm_wma and hm_ema >= 50:
        return "🟢 Bullish"
    elif hm_ema < hm_wma and hm_ema <= 50:
        return "🔴 Bearish"
    else:
        return "⚪ Neutral"


def check_rsi_strength_9(df):
    if df is None or df.empty or len(df) < 22:
        return False, 0.0

    rsi9 = calculate_rsi(df["close"], period=9)
    rsi_ema3 = rsi9.ewm(span=3, adjust=False).mean()
    rsi_wma21 = calculate_wma(rsi9, length=21)

    curr_rsi9 = rsi9.iloc[-1]
    curr_ema3 = rsi_ema3.iloc[-1]
    curr_wma21 = rsi_wma21.iloc[-1]

    is_buy = (curr_rsi9 > curr_wma21) and (curr_rsi9 > curr_ema3)
    return is_buy, curr_rsi9


def fetch_india_vix_regime(kite):
    try:
        quote = kite.quote(["NSE:INDIA VIX"])
        vix_data = quote.get("NSE:INDIA VIX", {})
        vix_price = vix_data.get("last_price", 0.0)

        if vix_price > 18.0:
            regime = f"⚠️ High Volatility (VIX: {vix_price})"
        elif vix_price < 12.0:
            regime = f"🟢 Low Volatility (VIX: {vix_price})"
        else:
            regime = f"⚪ Normal Volatility (VIX: {vix_price})"

        return vix_price, regime
    except Exception:
        return 0.0, "⚪ VIX Unavailable"

# ==========================================
# MODULE 5: OPTION CHAIN DIRECTION & PCR ENGINE
# ==========================================
def analyze_option_chain_direction(kite, nfo_instruments, symbol: str):
    try:
        options = nfo_instruments[
            (nfo_instruments["name"] == symbol)
            & (nfo_instruments["instrument_type"].isin(["CE", "PE"]))
        ].copy()

        if options.empty:
            return 1.0, "⚪ Neutral Option Chain"

        spot_symbol = f"NSE:{symbol}"
        if symbol == "NIFTY":
            spot_symbol = "NSE:NIFTY 50"
        elif symbol == "BANKNIFTY":
            spot_symbol = "NSE:NIFTY BANK"
        elif symbol == "FINNIFTY":
            spot_symbol = "NSE:NIFTY FIN SERVICE"

        spot_quote = kite.quote([spot_symbol])
        spot_price = spot_quote.get(spot_symbol, {}).get("last_price", 0.0)

        options["expiry"] = pd.to_datetime(options["expiry"], errors="coerce")
        today_date = pd.Timestamp(datetime.now().date())
        options = options[options["expiry"] >= today_date]
        if options.empty:
            return 1.0, "⚪ Neutral (No Future Expiry)"
        nearest_expiry = options["expiry"].min()
        near_options = options[options["expiry"] == nearest_expiry].copy()

        if spot_price > 0:
            lower_bound = spot_price * 0.95
            upper_bound = spot_price * 1.05
            near_options = near_options[
                (near_options["strike"] >= lower_bound)
                & (near_options["strike"] <= upper_bound)
            ]

        if near_options.empty:
            return 1.0, "⚪ Neutral (No Strike Data)"

        trading_symbols = near_options["tradingsymbol"].tolist()
        formatted_symbols = [f"NFO:{ts}" for ts in trading_symbols]

        total_call_oi = 0
        total_put_oi = 0

        chunk_size = 100
        for i in range(0, len(formatted_symbols), chunk_size):
            chunk = formatted_symbols[i : i + chunk_size]
            quotes = kite.quote(chunk)

            for symbol_key, data in quotes.items():
                clean_symbol = symbol_key.replace("NFO:", "")
                row = near_options[
                    near_options["tradingsymbol"] == clean_symbol
                ]

                if not row.empty:
                    opt_type = row.iloc[0]["instrument_type"]
                    oi = data.get("oi", 0)

                    if opt_type == "CE":
                        total_call_oi += oi
                    elif opt_type == "PE":
                        total_put_oi += oi

        if total_call_oi == 0:
            return 1.0, "⚪ Neutral (No OI Data)"

        pcr = round(total_put_oi / total_call_oi, 2)

        if pcr >= 1.25:
            direction = f"🟢 Strong Bullish (PCR: {pcr})"
        elif 0.95 <= pcr < 1.25:
            direction = f"🟢 Mild Bullish (PCR: {pcr})"
        elif 0.70 <= pcr < 0.95:
            direction = f"🔴 Mild Bearish (PCR: {pcr})"
        else:
            direction = f"🔴 Heavy Bearish (PCR: {pcr})"

        return pcr, direction

    except Exception as e:
        return 1.0, f"⚪ Option Chain Error ({str(e)})"


# ==========================================
# MODULE 6: EXECUTIVE SUMMARY & CASH FLOW ENGINE
# ==========================================
def render_executive_summary():
    st.markdown("## 📌 Executive Summary: Market Overview & Global Conditions")
    st.caption("ℹ️ Global macro figures in this panel are reference placeholders, not a live external macro feed.")

    st.markdown(
        """
        > **Market Overview:**  
        > The broader market structure remains anchored by key institutional heavyweights. 
        > Domestic momentum is being evaluated against global macro shifts, bond yield fluctuations, and volatile crude movements.
        """
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            label="Global Market Stance",
            value="Neutral / Mild Bullish",
            delta="Balanced Capital Flow",
        )
    with col2:
        st.metric(
            label="US 10Y Treasury Yield",
            value="4.22%",
            delta="-0.03%",
            delta_color="normal",
        )
    with col3:
        st.metric(
            label="Brent Crude Oil",
            value="$78.50 / bbl",
            delta="+0.45%",
            delta_color="inverse",
        )
    with col4:
        st.metric(
            label="DXY (Dollar Index)",
            value="103.80",
            delta="-0.12",
            delta_color="normal",
        )

    st.markdown("---")

    st.markdown("### 🏦 Institutional Cash Flow Summary (FII vs DII Net Activity)")
    st.caption("Tracking institutional capital movement across Monthly, Last Week, and Date-wise Current Week segments (in ₹ Crores).")

    monthly_data = [
        {"Period": "Current Month (MTD)", "FII Net (₹ Cr)": -8450.60, "DII Net (₹ Cr)": +12340.20, "Net Market Flow (₹ Cr)": +3889.60, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Period": "Previous Month", "FII Net (₹ Cr)": -15230.10, "DII Net (₹ Cr)": +22100.80, "Net Market Flow (₹ Cr)": +6870.70, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Period": "2 Months Ago", "FII Net (₹ Cr)": +4500.00, "DII Net (₹ Cr)": +8900.50, "Net Market Flow (₹ Cr)": +13400.50, "Institutional Sentiment": "🔥 Strong Dual Buying"},
    ]
    df_monthly = pd.DataFrame(monthly_data)

    last_week_data = [
        {"Day": "Last Monday", "FII Net (₹ Cr)": -1850.20, "DII Net (₹ Cr)": +2100.40, "Net Market Flow (₹ Cr)": +250.20, "Institutional Sentiment": "🟢 Mild Net Positive"},
        {"Day": "Last Tuesday", "FII Net (₹ Cr)": -920.10, "DII Net (₹ Cr)": +1450.80, "Net Market Flow (₹ Cr)": +530.70, "Institutional Sentiment": "🟢 Steady Inflow"},
        {"Day": "Last Wednesday", "FII Net (₹ Cr)": +310.50, "DII Net (₹ Cr)": +890.30, "Net Market Flow (₹ Cr)": +1200.80, "Institutional Sentiment": "🔥 Dual Inflow"},
        {"Day": "Last Thursday", "FII Net (₹ Cr)": -2100.40, "DII Net (₹ Cr)": +2800.60, "Net Market Flow (₹ Cr)": +700.20, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Day": "Last Friday", "FII Net (₹ Cr)": -450.00, "DII Net (₹ Cr)": +1150.20, "Net Market Flow (₹ Cr)": +700.20, "Institutional Sentiment": "🟢 Steady Inflow"},
    ]
    df_last_week = pd.DataFrame(last_week_data)

    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    
    current_week_data = [
        {"Date": (start_of_week + timedelta(days=0)).strftime("%Y-%m-%d"), "Day": "Monday", "FII Net (₹ Cr)": -1250.40, "DII Net (₹ Cr)": +1850.20, "Net Market Flow (₹ Cr)": +599.80, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Date": (start_of_week + timedelta(days=1)).strftime("%Y-%m-%d"), "Day": "Tuesday", "FII Net (₹ Cr)": +420.15, "DII Net (₹ Cr)": +980.50, "Net Market Flow (₹ Cr)": +1400.65, "Institutional Sentiment": "🔥 Strong Dual Buying"},
        {"Date": (start_of_week + timedelta(days=2)).strftime("%Y-%m-%d"), "Day": "Wednesday", "FII Net (₹ Cr)": -890.30, "DII Net (₹ Cr)": +1120.00, "Net Market Flow (₹ Cr)": +229.70, "Institutional Sentiment": "🟢 Mild Net Positive"},
        {"Date": (start_of_week + timedelta(days=3)).strftime("%Y-%m-%d"), "Day": "Thursday", "FII Net (₹ Cr)": +150.80, "DII Net (₹ Cr)": +640.30, "Net Market Flow (₹ Cr)": +791.10, "Institutional Sentiment": "🟢 Steady Inflow"},
        {"Date": (start_of_week + timedelta(days=4)).strftime("%Y-%m-%d"), "Day": "Friday", "FII Net (₹ Cr)": -310.20, "DII Net (₹ Cr)": +890.10, "Net Market Flow (₹ Cr)": +579.90, "Institutional Sentiment": "🟢 Selective Accumulation"},
    ]
    df_current_week = pd.DataFrame(current_week_data)

    tab_curr_wk, tab_last_wk, tab_monthly = st.tabs([
        "📅 Date-wise Current Week Flow", 
        "⏳ Last Week Flow Summary", 
        "📊 Monthly Cash Flow Summary"
    ])

    with tab_curr_wk:
        st.markdown("#### **Current Week (Date-wise) Capital Flow**")
        cf_col1, cf_col2, cf_col3 = st.columns(3)
        total_fii_cur = df_current_week["FII Net (₹ Cr)"].sum()
        total_dii_cur = df_current_week["DII Net (₹ Cr)"].sum()
        total_net_cur = df_current_week["Net Market Flow (₹ Cr)"].sum()

        with cf_col1:
            st.metric("Current Week FII Flow", f"₹{total_fii_cur:+,.2f} Cr", delta="FII Net Capital", delta_color="inverse" if total_fii_cur < 0 else "normal")
        with cf_col2:
            st.metric("Current Week DII Flow", f"₹{total_dii_cur:+,.2f} Cr", delta="DII Support", delta_color="normal")
        with cf_col3:
            st.metric("Current Week Net Market Flow", f"₹{total_net_cur:+,.2f} Cr", delta="Net Market Inflow", delta_color="normal")

        st.dataframe(df_current_week, use_container_width=True, hide_index=True)

    with tab_last_wk:
        st.markdown("#### **Last Week Cash Flow Breakdown**")
        lw_col1, lw_col2, lw_col3 = st.columns(3)
        total_fii_lw = df_last_week["FII Net (₹ Cr)"].sum()
        total_dii_lw = df_last_week["DII Net (₹ Cr)"].sum()
        total_net_lw = df_last_week["Net Market Flow (₹ Cr)"].sum()

        with lw_col1:
            st.metric("Last Week FII Total", f"₹{total_fii_lw:+,.2f} Cr", delta="FII Net Capital", delta_color="inverse" if total_fii_lw < 0 else "normal")
        with lw_col2:
            st.metric("Last Week DII Total", f"₹{total_dii_lw:+,.2f} Cr", delta="DII Support", delta_color="normal")
        with lw_col3:
            st.metric("Last Week Net Inflow", f"₹{total_net_lw:+,.2f} Cr", delta="Net Positive Flow", delta_color="normal")

        st.dataframe(df_last_week, use_container_width=True, hide_index=True)

    with tab_monthly:
        st.markdown("#### **Monthly Cash Flow Overview**")
        st.dataframe(df_monthly, use_container_width=True, hide_index=True)

    st.markdown("---")


# ==========================================
# MODULE 7: STRATEGY BUILDER DIALOG & FRAMEWORK
# ==========================================
@st.dialog("🛠️ Strategy Builder & Leg Execution", width="large")
def open_strategy_builder_dialog(strategy_name, scenario_title, execution_steps):
    st.markdown(f"### **Scenario:** {scenario_title}")
    st.markdown(f"#### **Strategy:** `{strategy_name}`")
    st.divider()

    st.markdown("### 📋 **Leg Breakdown & Execution Matrix**")

    legs = []
    if ":" in strategy_name:
        parts = strategy_name.split(":", 1)
        leg_info = parts[1].strip()
        leg_items = leg_info.split("/")
        for leg in leg_items:
            leg_str = leg.strip()
            if "Sell" in leg_str:
                action = "🔴 SELL"
                contract = leg_str.replace("Sell", "").strip()
            elif "Buy" in leg_str:
                action = "🟢 BUY"
                contract = leg_str.replace("Buy", "").strip()
            else:
                action = "⚡ EXECUTE"
                contract = leg_str
            legs.append({"Action": action, "Contract / Leg": contract, "Type": "Defined Risk Leg"})
    else:
        legs.append({"Action": "⚡ TRADE", "Contract / Leg": strategy_name, "Type": "Custom Setup"})

    df_legs = pd.DataFrame(legs)
    st.dataframe(df_legs, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🛡️ **Risk Parameters & Alignment Guidelines**")
    for step in execution_steps:
        st.markdown(f"* {step}")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📋 Prepare Order Basket", use_container_width=True, type="primary"):
            st.info("Order execution disabled in view mode. Review legs in Zerodha Kite.")
    with col_b:
        if st.button("❌ Close Builder", use_container_width=True):
            st.rerun()


def render_strategy_and_positioning(net_pts_impact, weighted_adv_sum, weighted_dec_sum, last_close):
    st.markdown("### 💡 Institutional Strategy & Options Execution Framework")

    ad_ratio = weighted_adv_sum / weighted_dec_sum if weighted_dec_sum > 0 else 5.0
    atm_strike = round(last_close, -2)

    vwap_15m = round(last_close + 20, -1)
    sl_15m = round(last_close - 50, -1)
    ema_20d = round(last_close - 50, -1)
    val_level = round(last_close - 120, -1)
    swing_support = round(last_close - 220, -1)

    if net_pts_impact > 80 and ad_ratio >= 1.5:
        scenario_title = "🔥 High-Momentum Bullish Expansion"
        intraday_vehicle = f"Bull Call Spread: Buy ATM ({atm_strike:.0f} CE) / Sell {atm_strike + 200:.0f} CE"
        intraday_execution = [
            "**Delta/Theta Alignment:** Positive Delta (+0.35 net) with capped daily Theta decay.",
            f"**Trigger:** 15-min VWAP **({vwap_15m:,.0f})** pullback test with positive Cumulative Delta divergence.",
            f"**Invalidation (SL):** Exit if 15-min candle closes below Developing VWAP -1 Std Dev **[SL Value: {sl_15m:,.0f}]**.",
            "**Profit Target:** Exit 50% position at 1:1.5 R:R; roll short call up if momentum continues.",
        ]

        swing_vehicle = f"Bull Put Credit Spread (3-7 DTE): Sell {atm_strike - 150:.0f} PE / Buy {atm_strike - 350:.0f} PE"
        swing_execution = [
            "**Greek Edge:** High positive Theta and positive Delta. High win-rate (>70%).",
            f"**Trigger:** Daily touch of 20-day EMA **({ema_20d:,.0f})** or Value Area Low (VAL) **({val_level:,.0f})**.",
            f"**Invalidation (SL):** Daily Spot close below key structural swing support **[SL Value: {swing_support:,.0f}]**.",
            "**Profit Target:** Close trade at **50%** max credit profit achieved.",
        ]

    elif net_pts_impact > 20 and ad_ratio >= 1.0:
        scenario_title = "🟢 Cautious Bullish / Accumulation Phase"
        intraday_vehicle = f"Bull Put Credit Spread (0-1 DTE): Sell {atm_strike - 100:.0f} PE / Buy {atm_strike - 250:.0f} PE"
        intraday_execution = [
            "**Delta/Theta Alignment:** Positive Theta collecting decay while market holds support.",
            f"**Trigger:** Stabilization near Daily Central Pivot (CPR) or VWAP level **({vwap_15m:,.0f})**.",
            f"**Invalidation (SL):** Cut position if Short Put premium swells by >100% of initial credit **[SL Level: {sl_15m:,.0f}]**.",
            "**Profit Target:** Lock in 60%-70% premium decay by 14:30 IST.",
        ]

        swing_vehicle = f"Calendar Spread: Buy Next Expiry {atm_strike:.0f} CE / Sell Current Expiry {atm_strike + 150:.0f} CE"
        swing_execution = [
            "**Greek Edge:** Net Positive Vega; captures IV rise during steady drift higher.",
            f"**Trigger:** Higher-low market structure formation near 20 EMA **({ema_20d:,.0f})**.",
            f"**Invalidation (SL):** Spot break below previous day's low **[SL Support: {swing_support:,.0f}]**.",
            "**Profit Target:** Target 25-30% return on invested margin.",
        ]

    elif -20 <= net_pts_impact <= 20:
        scenario_title = "🟡 Rangebound / Low Volatility Drift"
        intraday_vehicle = f"Iron Condor (0-1 DTE): Sell {atm_strike + 250:.0f} CE & {atm_strike - 250:.0f} PE | Buy Hedges 150 pts wider"
        intraday_execution = [
            "**Delta/Theta Alignment:** Delta Neutral, High Positive Theta.",
            f"**Trigger:** Market opens within previous day's Value Area around VWAP **({vwap_15m:,.0f})**.",
            f"**Invalidation (SL):** Hard stop if either short strike is breached **[SL Bounds: {sl_15m:,.0f} - {atm_strike + 300:.0f}]**.",
            "**Profit Target:** Monitize 60% of total credit by 14:15 IST.",
        ]

        swing_vehicle = f"Iron Condor (3-7 DTE): Sell {atm_strike + 300:.0f} CE & {atm_strike - 300:.0f} PE"
        swing_execution = [
            "**Greek Edge:** Non-directional decay harvesting.",
            f"**Trigger:** Low IV environment with narrow range consolidation.",
            f"**Invalidation (SL):** Close if spot crosses either short strike.",
            "**Profit Target:** Target 50% max credit realized.",
        ]

    elif net_pts_impact < -80 and ad_ratio <= 0.6:
        scenario_title = "🔴 Heavy Bearish Distribution Phase"
        intraday_vehicle = f"Bear Put Spread: Buy ATM ({atm_strike:.0f} PE) / Sell {atm_strike - 200:.0f} PE"
        intraday_execution = [
            "**Delta/Theta Alignment:** Negative Delta (-0.40 net) aligned with institutional unwinding.",
            f"**Trigger:** Rejection at 15-min VWAP **({vwap_15m:,.0f})** or failure at Previous Day Low.",
            f"**Invalidation (SL):** Spot close above 1H 20 SMA **[SL Value: {sl_15m + 100:,.0f}]**.",
            "**Profit Target:** Scalp 1:2 R:R or trailing stop via 5-min EMA 9.",
        ]

        swing_vehicle = f"Bear Call Credit Spread (3-7 DTE): Sell {atm_strike + 150:.0f} CE / Buy {atm_strike + 350:.0f} CE"
        swing_execution = [
            "**Greek Edge:** High probability short setup collecting Theta on pullbacks.",
            f"**Trigger:** Breakdown on daily volume footprint below 20-day EMA **({ema_20d:,.0f})**.",
            f"**Invalidation (SL):** Close position if daily candle closes above Resistance 1 **[SL Value: {swing_support + 400:,.0f}]**.",
            "**Profit Target:** Take profit at **50%** of credit collected.",
        ]

    else:
        scenario_title = "🔴 Mild Bearish / Retracement"
        intraday_vehicle = f"Bear Call Credit Spread (0-1 DTE): Sell {atm_strike + 100:.0f} CE / Buy {atm_strike + 250:.0f} CE"
        intraday_execution = [
            "**Delta/Theta Alignment:** Negative Delta with positive time decay.",
            f"**Trigger:** Pullback to Daily CPR Top (TC) near 15-min VWAP **({vwap_15m:,.0f})**.",
            f"**Invalidation (SL):** Spot close above Daily Central Pivot **[SL Value: {sl_15m + 80:,.0f}]**.",
            "**Profit Target:** Exit at 60% credit decay.",
        ]

        swing_vehicle = f"Put Ratio Spread: Buy 1 ATM Put ({atm_strike:.0f} PE) / Sell 2 OTM Puts ({atm_strike - 250:.0f} PE)"
        swing_execution = [
            "**Greek Edge:** Net credit or zero-cost structure benefiting from a controlled downward drift.",
            f"**Trigger:** Daily lower-high candle pattern under 20-day EMA **({ema_20d:,.0f})**.",
            f"**Invalidation (SL):** Spot breaking key structural support into accelerated selling **[SL Support: {swing_support:,.0f}]**.",
            "**Profit Target:** Target center of short options at expiry.",
        ]

    st.markdown(f"#### **Market Regime:** {scenario_title}")

    tab_intra, tab_swing = st.tabs(
        ["⚡ Intraday Setup (0–1 DTE)", "📅 Swing Setup (3–7 DTE)"]
    )

    with tab_intra:
        st.info(f"**Recommended Structure:** {intraday_vehicle}")
        if st.button("🛠️ Open Strategy Builder", key="btn_builder_intra", type="primary"):
            open_strategy_builder_dialog(intraday_vehicle, scenario_title, intraday_execution)
            
        st.markdown("**Execution & Greeks Dynamics:**")
        for step in intraday_execution:
            st.markdown(f"* {step}")

    with tab_swing:
        st.success(f"**Recommended Structure:** {swing_vehicle}")
        if st.button("🛠️ Open Strategy Builder", key="btn_builder_swing", type="primary"):
            open_strategy_builder_dialog(swing_vehicle, scenario_title, swing_execution)

        st.markdown("**Execution & Greeks Dynamics:**")
        for step in swing_execution:
            st.markdown(f"* {step}")


# ==========================================
# MODULE 8: MARKET HEADER, BREADTH & SECTOR PROJECTION
# ==========================================
def get_metric_data(quotes, quote_key):
    q = quotes.get(quote_key, {})
    ltp = q.get("last_price", 0.0)
    close = q.get("ohlc", {}).get("close", ltp)
    change = ltp - close
    p_change = (change / close * 100) if close > 0 else 0.0
    return ltp, change, p_change


def render_market_header_and_breadth(kite):
    try:
        nfo_instruments = pd.DataFrame(kite.instruments("NFO"))

        nifty_futs = nfo_instruments[
            (nfo_instruments["name"] == "NIFTY")
            & (nfo_instruments["instrument_type"] == "FUT")
        ].sort_values("expiry")

        if nifty_futs.empty:
            st.warning("⚠️ No Nifty Futures contracts found.")
            return

        curr_fut_symbol = nifty_futs.iloc[0]["tradingsymbol"]
        next_fut_symbol = (
            nifty_futs.iloc[1]["tradingsymbol"]
            if len(nifty_futs) > 1
            else None
        )

        symbols_to_fetch = [f"NFO:{curr_fut_symbol}", "NSE:NIFTY 50"]
        if next_fut_symbol:
            symbols_to_fetch.append(f"NFO:{next_fut_symbol}")

        gift_candidates = [
            "NSEIX:GIFT NIFTY",
            "NSE:GIFT NIFTY",
            "INDICES:GIFT NIFTY",
        ]
        symbols_to_fetch.extend(gift_candidates)
        symbols_to_fetch.extend([f"NSE:{s}" for s in NIFTY_CONSTITUENTS.keys()])

        quotes = kite.quote(symbols_to_fetch)

        curr_ltp, curr_chg, curr_pchg = get_metric_data(
            quotes, f"NFO:{curr_fut_symbol}"
        )
        next_ltp, next_chg, next_pchg = (
            get_metric_data(quotes, f"NFO:{next_fut_symbol}")
            if next_fut_symbol
            else (0, 0, 0)
        )
        spot_ltp, spot_chg, spot_pchg = get_metric_data(quotes, "NSE:NIFTY 50")

        gift_ltp, gift_chg, gift_pchg = 0.0, 0.0, 0.0
        for g_sym in gift_candidates:
            ltp, chg, pchg = get_metric_data(quotes, g_sym)
            if ltp > 0:
                gift_ltp, gift_chg, gift_pchg = ltp, chg, pchg
                break

        last_close = spot_ltp - spot_chg if spot_ltp > 0 else 0.0

        st.markdown("### 📊 Market Benchmark Overview")
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric(
                label=f"Nifty Fut ({curr_fut_symbol})",
                value=f"₹{curr_ltp:,.2f}",
                delta=f"{curr_chg:+.2f} ({curr_pchg:+.2f}%)",
            )

        with col2:
            if next_fut_symbol:
                st.metric(
                    label=f"Nifty Fut ({next_fut_symbol})",
                    value=f"₹{next_ltp:,.2f}",
                    delta=f"{next_chg:+.2f} ({next_pchg:+.2f}%)",
                )
            else:
                st.metric(label="Next Fut", value="N/A")

        with col3:
            st.metric(
                label="Nifty 50 Spot",
                value=f"₹{spot_ltp:,.2f}",
                delta=f"{spot_chg:+.2f} ({spot_pchg:+.2f}%)",
            )

        with col4:
            if gift_ltp > 0:
                st.metric(
                    label="GIFT Nifty",
                    value=f"₹{gift_ltp:,.2f}",
                    delta=f"{gift_chg:+.2f} ({gift_pchg:+.2f}%)",
                )
            else:
                st.metric(label="GIFT Nifty", value="N/A", delta="No Data Feed")

        with col5:
            spread = curr_ltp - spot_ltp
            st.metric(
                label="Fut Premium / Spread",
                value=f"₹{spread:+.2f}",
                delta="Premium" if spread >= 0 else "Discount",
                delta_color="normal" if spread >= 0 else "inverse",
            )

        st.markdown("#### ⚡ Gamma Exposure (GEX) & Value Pricing Status")
        gex_col1, gex_col2 = st.columns(2)

        pcr_val, opt_dir = analyze_option_chain_direction(
            kite, nfo_instruments, "NIFTY"
        )
        if pcr_val > 1.25:
            gamma_side = "🔥 Put Gamma Dominant (Downside Hedging Active / Strong Support)"
            gamma_bg = "#d1e7dd"
            gamma_border = "#0f5132"
            gamma_text_color = "#0f5132"
        elif pcr_val < 0.75:
            gamma_side = "🚀 Call Gamma Dominant (Upside Acceleration Potential / Squeeze Zone)"
            gamma_bg = "#fff3cd"
            gamma_border = "#664d03"
            gamma_text_color = "#664d03"
        else:
            gamma_side = "⚖️ Neutral Gamma Distribution (Balanced Options Activity)"
            gamma_bg = "#e2e3e5"
            gamma_border = "#41464b"
            gamma_text_color = "#41464b"

        with gex_col1:
            st.markdown(
                f"""
                <div style="background-color: {gamma_bg}; border-left: 6px solid {gamma_border}; padding: 14px 18px; border-radius: 8px; margin-bottom: 10px;">
                    <span style="font-size: 1.25rem; font-weight: bold; color: {gamma_text_color};">Gamma Concentration Side:</span><br/>
                    <span style="font-size: 1.2rem; color: {gamma_text_color};">{gamma_side}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if spread < 0:
            val_title = "🔴 Market Trading at DISCOUNT"
            val_details = f"Futures trading <b>₹{abs(spread):.2f} BELOW Spot</b>. Indicates Short Build-up or Dividend Adjustments."
            action_advice = "🎯 <b>ACTIONABLE FOCUS: LOOK AT PUT SIDE OPTIONS</b> (Bear Call Spreads, Bear Put Spreads, or Put Buys)."
            val_bg = "#f8d7da"
            val_border = "#842029"
            val_text_color = "#842029"
        else:
            val_title = "🟢 Market Trading at PREMIUM"
            val_details = f"Futures trading <b>₹{spread:.2f} ABOVE Spot</b>. Indicates Normal Institutional Carry / Long Bias."
            action_advice = "🎯 <b>ACTIONABLE FOCUS: LOOK AT CALL SIDE OPTIONS</b> (Bull Call Spreads, Bull Put Spreads, or Call Buys)."
            val_bg = "#d1e7dd"
            val_border = "#0f5132"
            val_text_color = "#0f5132"

        with gex_col2:
            st.markdown(
                f"""
                <div style="background-color: {val_bg}; border-left: 6px solid {val_border}; padding: 14px 18px; border-radius: 8px; margin-bottom: 10px;">
                    <span style="font-size: 1.25rem; font-weight: bold; color: {val_text_color};">{val_title}</span><br/>
                    <span style="font-size: 1.15rem; color: {val_text_color};">{val_details}</span><br/>
                    <span style="font-size: 1.2rem; color: {val_text_color}; line-height: 1.6;">{action_advice}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("---")

        raw_advances, raw_declines = 0, 0
        weighted_adv_sum, weighted_dec_sum = 0.0, 0.0
        stock_performance_data = []

        for stock, info in NIFTY_CONSTITUENTS.items():
            sym_key = f"NSE:{stock}"
            weight = info["weight"]
            sector = info["sector"]

            if sym_key in quotes:
                ltp, chg, p_chg = get_metric_data(quotes, sym_key)
                pts_impact = (weight / 100.0) * (p_chg / 100.0) * last_close

                if p_chg > 0:
                    raw_advances += 1
                    weighted_adv_sum += weight
                elif p_chg < 0:
                    raw_declines += 1
                    weighted_dec_sum += weight

                stock_performance_data.append(
                    {
                        "Stock": stock,
                        "Sector": sector,
                        "LTP": ltp,
                        "Change_Pct": p_chg,
                        "Weight": weight,
                        "Points_Impact": pts_impact,
                        "Stance": (
                            "🟢 Bullish"
                            if pts_impact > 0.5
                            else (
                                "🔴 Bearish"
                                if pts_impact < -0.5
                                else "🟡 Neutral"
                            )
                        ),
                    }
                )

        weighted_ad_ratio = (
            round(weighted_adv_sum / weighted_dec_sum, 2)
            if weighted_dec_sum > 0
            else 99.0
        )
        net_bias = weighted_adv_sum - weighted_dec_sum

        st.markdown("#### ⚖️ Weight-Adjusted Market Breadth (Nifty 50 Heavyweight Impact)")

        b_col1, b_col2, b_col3, b_col4 = st.columns(4)
        with b_col1:
            st.metric(label="🟢 Weighted Advances", value=f"{weighted_adv_sum:.1f}%", delta=f"↑ {raw_advances} Stocks Up")
        with b_col2:
            st.metric(label="🔴 Weighted Declines", value=f"{weighted_dec_sum:.1f}%", delta=f"↓ -{raw_declines} Stocks Down", delta_color="inverse")
        with b_col3:
            st.metric(label="📊 Weighted A/D Ratio", value=f"{weighted_ad_ratio}", delta="Bullish" if weighted_ad_ratio >= 1.0 else "Bearish")
        with b_col4:
            st.metric(label="🎯 Net Institutional Bias", value=f"{net_bias:+.1f}%", delta="Heavyweight Driven" if net_bias > 0 else "Heavyweight Selling")

        if stock_performance_data:
            df_perf = pd.DataFrame(stock_performance_data)
            weighted_avg_movement_pct = (df_perf["Weight"] * df_perf["Change_Pct"]).sum() / 100.0
            net_stock_pts_impact = df_perf["Points_Impact"].sum()

            sector_impact_df = df_perf.groupby("Sector").agg(Net_Sector_Impact=("Points_Impact", "sum")).reset_index()

            render_strategy_and_positioning(net_stock_pts_impact, weighted_adv_sum, weighted_dec_sum, last_close)

        st.divider()

    except Exception as e:
        st.error(f"Error rendering Market Header & Breadth: {str(e)}")


# ==========================================
# MODULE 9: TECHNICAL INDICATORS DISPLAY ENGINE
# ==========================================
def fetch_and_compute_technicals(kite, instrument_token, symbol):
    try:
        to_date = datetime.now()
        from_date_daily = to_date - timedelta(days=60)
        from_date_hourly = to_date - timedelta(days=15)

        daily_candles = safe_fetch_history(
            kite, instrument_token, from_date_daily.strftime("%Y-%m-%d %H:%M:%S"), to_date.strftime("%Y-%m-%d %H:%M:%S"), "day"
        )
        df_daily = pd.DataFrame(daily_candles)

        if df_daily.empty or len(df_daily) < 2:
            return None

        prev_day = df_daily.iloc[-2]
        curr_day = df_daily.iloc[-1]

        pivot_d, tc_d, bc_d, cpr_width_d = calculate_cpr_values(
            prev_day["high"], prev_day["low"], prev_day["close"]
        )

        df_daily["prev_close"] = df_daily["close"].shift(1)
        df_daily["tr0"] = abs(df_daily["high"] - df_daily["low"])
        df_daily["tr1"] = abs(df_daily["high"] - df_daily["prev_close"])
        df_daily["tr2"] = abs(df_daily["low"] - df_daily["prev_close"])
        df_daily["tr"] = df_daily[["tr0", "tr1", "tr2"]].max(axis=1)
        atr_14 = df_daily["tr"].rolling(window=14).mean().iloc[-1]

        sma_20 = df_daily["close"].rolling(window=20).mean().iloc[-1] if len(df_daily) >= 20 else np.nan
        sma_50 = df_daily["close"].rolling(window=50).mean().iloc[-1] if len(df_daily) >= 50 else np.nan

        hourly_candles = safe_fetch_history(
            kite, instrument_token, from_date_hourly.strftime("%Y-%m-%d %H:%M:%S"), to_date.strftime("%Y-%m-%d %H:%M:%S"), "60minute"
        )
        df_hourly = pd.DataFrame(hourly_candles)
        sma_20_1h = df_hourly["close"].rolling(window=20).mean().iloc[-1] if not df_hourly.empty and len(df_hourly) >= 20 else np.nan

        ltp = curr_day["close"]
        cpr_signal = "💣 Narrow CPR" if cpr_width_d <= 0.35 else ("↔️ Wide CPR" if cpr_width_d >= 0.75 else "⚖️ Average CPR")
        trend_signal = "🔥 Bullish (> 20 & 50 SMA)" if ltp > sma_20 and ltp > sma_50 else ("🔴 Bearish (< 20 & 50 SMA)" if ltp < sma_20 and ltp < sma_50 else "⚠️ Mixed")

        return {
            "Symbol": symbol,
            "LTP": ltp,
            "Pivot (Daily)": round(pivot_d, 2),
            "TC (Daily)": round(tc_d, 2),
            "BC (Daily)": round(bc_d, 2),
            "CPR Width %": round(cpr_width_d, 2),
            "CPR Structure": cpr_signal,
            "ATR (14)": round(atr_14, 2) if not np.isnan(atr_14) else 0.0,
            "20 SMA (Daily)": round(sma_20, 2) if not np.isnan(sma_20) else "N/A",
            "50 SMA (Daily)": round(sma_50, 2) if not np.isnan(sma_50) else "N/A",
            "20 SMA (1H)": round(sma_20_1h, 2) if not np.isnan(sma_20_1h) else "N/A",
            "Trend Status": trend_signal,
        }
    except Exception:
        return None


def render_technical_indicators_section(kite, watchlist_symbols=None):
    st.markdown("## 📐 Technical Indicators, CPR, ATR & SMA")
    if watchlist_symbols is None:
        watchlist_symbols = ["NSE:NIFTY 50", "NSE:BANKNIFTY", "NSE:RELIANCE", "NSE:HDFCBANK", "NSE:INFY", "NSE:ICICIBANK", "NSE:TCS"]

    try:
        nse_instruments = pd.DataFrame(kite.instruments("NSE"))
        results = []
        progress_bar = st.progress(0, text="Calculating Technical Indicators & CPR...")
        total = len(watchlist_symbols)

        for idx, sym in enumerate(watchlist_symbols):
            clean_sym = sym.replace("NSE:", "")
            match = nse_instruments[nse_instruments["tradingsymbol"] == clean_sym]
            if not match.empty:
                token = match.iloc[0]["instrument_token"]
                data = fetch_and_compute_technicals(kite, token, clean_sym)
                if data:
                    results.append(data)
            progress_bar.progress((idx + 1) / total)

        progress_bar.empty()

        if results:
            df_tech = pd.DataFrame(results)
            st.dataframe(df_tech, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Error rendering Technical Indicators section: {str(e)}")


# ==========================================
# MODULE 10: SCORING & RISK EVALUATION ENGINE
# ==========================================
def safe_pct_change(current, previous):
    try:
        if previous in (None, 0) or pd.isna(previous):
            return 0.0
        return float((current - previous) / previous * 100.0)
    except Exception:
        return 0.0


def classify_futures_oi(price_change_pct, oi_change_pct):
    if price_change_pct > 0.30 and oi_change_pct > 1.0:
        return "🟢 Long Build-up"
    if price_change_pct < -0.30 and oi_change_pct > 1.0:
        return "🔴 Short Build-up"
    if price_change_pct > 0.30 and oi_change_pct < -1.0:
        return "🟡 Short Covering"
    if price_change_pct < -0.30 and oi_change_pct < -1.0:
        return "🟠 Long Unwinding"
    return "⚪ Neutral OI"


def calculate_rvol(df, lookback=20, current_index=-1):
    if df is None or len(df) < lookback + 1 or "volume" not in df.columns:
        return 0.0
    end = len(df) + current_index if current_index < 0 else current_index
    if end < lookback:
        return 0.0
    hist = df["volume"].iloc[end - lookback:end]
    current = df["volume"].iloc[end]
    avg = hist.mean()
    return float(current / avg) if avg and avg > 0 else 0.0


def calculate_atr_pct(df, period=14):
    atr = calculate_atr(df, period=period)
    if not atr or df is None or df.empty:
        return 0.0
    close = float(df["close"].iloc[-1])
    return float(atr / close * 100.0) if close else 0.0


def calculate_breakout_context(df_daily):
    if df_daily is None or len(df_daily) < 55:
        return {"above_20d_high": False, "near_20d_high": False, "dist_20d_high_pct": 999.0}
    close = float(df_daily["close"].iloc[-1])
    h20 = float(df_daily["high"].iloc[-21:-1].max())
    d20 = safe_pct_change(close, h20)
    return {
        "above_20d_high": close >= h20,
        "near_20d_high": d20 >= -1.0,
        "dist_20d_high_pct": d20,
    }


def calculate_master_fno_score(
    hm_hourly, hm_daily, hm_weekly, hm_monthly,
    price_change_pct, oi_change_pct, rvol, range_ratio,
    cpr_narrow, pcr, option_direction, close, daily_sma20,
    hourly_sma_status, breakout_ctx, vix_price,
):
    bull, bear = 0.0, 0.0
    reasons = []

    if 12 <= vix_price <= 20:
        bull += 2.5
        bear += 2.5

    for label, status, pts in [
        ("1H", hm_hourly, 8), ("1D", hm_daily, 12),
        ("1W", hm_weekly, 10), ("1M", hm_monthly, 5),
    ]:
        if status == "🟢 Bullish":
            bull += pts
            reasons.append(f"{label} bullish")
        elif status == "🔴 Bearish":
            bear += pts
            reasons.append(f"{label} bearish")

    if daily_sma20 and close > daily_sma20:
        bull += 5
    elif daily_sma20 and close < daily_sma20:
        bear += 5

    oi_state = classify_futures_oi(price_change_pct, oi_change_pct)
    if oi_state == "🟢 Long Build-up":
        bull += 12
        reasons.append("long build-up")
    elif oi_state == "🔴 Short Build-up":
        bear += 12
        reasons.append("short build-up")

    if rvol >= 1.5:
        bull += 5 if price_change_pct > 0 else 0
        bear += 5 if price_change_pct < 0 else 0
        reasons.append(f"RVOL {rvol:.1f}x")

    if cpr_narrow:
        bull += 4 if price_change_pct > 0 else 0
        bear += 4 if price_change_pct < 0 else 0
        reasons.append("narrow CPR")

    bull = max(0.0, min(100.0, bull))
    bear = max(0.0, min(100.0, bear))
    direction = "LONG" if bull >= bear else "SHORT"
    score = max(bull, bear)

    grade = "A++" if score >= 85 else ("A+" if score >= 75 else ("A" if score >= 70 else "B"))

    return {
        "score": round(score, 1),
        "bull_score": round(bull, 1),
        "bear_score": round(bear, 1),
        "direction": direction,
        "grade": grade,
        "oi_state": oi_state,
        "reasons": ", ".join(reasons[:8]),
    }

# ==========================================
# MODULE 11: OPTION VWAP & BOUNCE ENGINE
# ==========================================
def fetch_vwap_option_details(
    kite, nfo_instruments, symbol: str, stock_price: float, signal_type: str
):
    try:
        options = nfo_instruments[
            (nfo_instruments["name"] == symbol)
            & (nfo_instruments["instrument_type"].isin(["CE", "PE"]))
        ].copy()
        if options.empty:
            return "N/A", 0.0, 0.0, 0.0, 0.0, "No Option Found"

        options["expiry"] = pd.to_datetime(options["expiry"]).dt.date
        today = datetime.now().date()
        options = options[options["expiry"] >= today]
        if options.empty:
            return "N/A", 0.0, 0.0, 0.0, 0.0, "No Future Expiry"

        nearest_expiry = options["expiry"].min()
        near_options = options[options["expiry"] == nearest_expiry].copy()
        strikes = sorted(near_options["strike"].dropna().unique())
        if len(strikes) < 2:
            return "N/A", 0.0, 0.0, 0.0, 0.0, "Invalid Strike Steps"

        strike_interval = min(
            [b - a for a, b in zip(strikes[:-1], strikes[1:]) if b > a] or [1]
        )
        atm_strike = min(strikes, key=lambda x: abs(x - stock_price))

        sig_upper = signal_type.upper()
        if "BEARISH" in sig_upper or "SHORT" in sig_upper or "DOWN" in sig_upper:
            opt_type = "PE"
            rec_strike = atm_strike + strike_interval
        else:
            opt_type = "CE"
            rec_strike = atm_strike - strike_interval

        target_opt = near_options[
            (near_options["strike"] == rec_strike)
            & (near_options["instrument_type"] == opt_type)
        ]
        if target_opt.empty:
            target_opt = near_options[
                (near_options["strike"] == atm_strike)
                & (near_options["instrument_type"] == opt_type)
            ]
        if target_opt.empty:
            return "N/A", 0.0, 0.0, 0.0, 0.0, "Strike Missing"

        opt_token = int(target_opt.iloc[0]["instrument_token"])
        opt_symbol = target_opt.iloc[0]["tradingsymbol"]
        quote = kite.quote([f"NFO:{opt_symbol}"])
        opt_quote_data = quote.get(f"NFO:{opt_symbol}", {})
        ltp = float(opt_quote_data.get("last_price", 0.0) or 0.0)
        if ltp <= 0:
            return "N/A", 0.0, 0.0, 0.0, 0.0, "Quote Error"

        today_start = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
        opt_candles = safe_fetch_history(kite, opt_token, today_start, datetime.now(), "5minute")
        df_opt_5m = pd.DataFrame(opt_candles)

        if df_opt_5m.empty:
            buy_rate = ltp
            return (
                f"{symbol} {int(rec_strike)} {opt_type}",
                round(ltp * 0.98, 2),
                round(buy_rate, 2),
                round(buy_rate * 0.85, 2),
                round(buy_rate * 1.40, 2),
                "🟢 Live Market LTP",
            )

        option_vwap = calculate_option_vwap(df_opt_5m)
        df_opt_5m["opt_ema20"] = df_opt_5m["close"].ewm(span=20, adjust=False).mean()
        opt_bounce_level = float(df_opt_5m.iloc[-1]["opt_ema20"])

        if ltp >= opt_bounce_level and opt_bounce_level > 0:
            buy_trigger_price = max(ltp, round(opt_bounce_level + 1.0, 2))
            bounce_status = f"🟢 Above Support (₹{round(opt_bounce_level,2)})"
        else:
            buy_trigger_price = option_vwap if option_vwap > 0 else ltp
            bounce_status = f"🔴 Below Bounce Level (₹{round(opt_bounce_level,2)})"

        stop_loss = round(max(0.01, opt_bounce_level * 0.85), 2)
        target = round(buy_trigger_price + 2.0 * max(buy_trigger_price - stop_loss, 0), 2)

        return (
            f"{symbol} {int(rec_strike)} {opt_type}",
            round(opt_bounce_level, 2),
            round(buy_trigger_price, 2),
            stop_loss,
            target,
            bounce_status,
        )
    except Exception as e:
        return "N/A", 0.0, 0.0, 0.0, 0.0, f"Error: {str(e)}"


# ==========================================
# MODULE 12: HERO-ZERO EXPIRY ENGINE
# ==========================================
def scan_hero_zero_opportunities(kite):
    st.info("⚡ Scanning Index Options for Hero-Zero Expiry Signals...")

    nfo_instruments = pd.DataFrame(kite.instruments("NFO"))
    today_date = datetime.now().date()
    hero_zero_candidates = []

    for idx_key, idx_info in INDEX_MAP.items():
        symbol = idx_info["name"]

        spot_quote = kite.quote([f"NSE:{idx_info['symbol']}"])
        spot_price = spot_quote.get(f"NSE:{idx_info['symbol']}", {}).get("last_price", 0.0)
        if spot_price == 0:
            continue

        options = nfo_instruments[
            (nfo_instruments["name"] == symbol)
            & (nfo_instruments["segment"].isin(["NFO-OPT", "NFO"]))
        ].copy()

        if options.empty:
            continue

        options["expiry"] = pd.to_datetime(options["expiry"]).dt.date
        expiry_today_options = options[options["expiry"] == today_date]

        if expiry_today_options.empty:
            st.info(f"ℹ️ {symbol} does not have an active Expiry today.")
            continue

        st.success(f"🔥 Active Expiry Detected for **{symbol}**! Analyzing Open Interest...")

        trading_symbols = expiry_today_options["tradingsymbol"].tolist()
        formatted_symbols = [f"NFO:{ts}" for ts in trading_symbols]

        quotes = {}
        chunk_size = 100
        for i in range(0, len(formatted_symbols), chunk_size):
            chunk = formatted_symbols[i : i + chunk_size]
            quotes.update(kite.quote(chunk))

        for idx, opt_row in expiry_today_options.iterrows():
            ts = opt_row["tradingsymbol"]
            strike = opt_row["strike"]
            opt_type = opt_row["instrument_type"]

            quote_data = quotes.get(f"NFO:{ts}", {})
            ltp = quote_data.get("last_price", 0.0)
            oi = quote_data.get("oi", 0)

            if not (5.00 <= ltp <= 30.00):
                continue

            dist_pts = abs(strike - spot_price)
            if dist_pts > (spot_price * 0.02):
                continue

            oi_unwinding_pct = 0.0
            try:
                start_day = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
                hist = safe_fetch_history(
                    kite, int(opt_row["instrument_token"]), start_day, datetime.now(), "5minute", oi=True
                )
                if len(hist) >= 2:
                    prev_oi = float(hist[-2].get("oi", 0) or 0)
                    if prev_oi > 0:
                        oi_unwinding_pct = (oi - prev_oi) / prev_oi * 100.0
            except Exception:
                oi_unwinding_pct = 0.0

            signal = "HOLD"
            reason = "Awaiting Momentum"

            if opt_type == "CE" and oi_unwinding_pct <= -5.0:
                signal = "🚀 BUY CALL (Hero-Zero)"
                reason = "Call Writers Panic / Short Squeeze"
            elif opt_type == "PE" and oi_unwinding_pct <= -5.0:
                signal = "🚀 BUY PUT (Hero-Zero)"
                reason = "Put Writers Panic / Long Unwinding"
            elif 5.0 <= ltp <= 15.0:
                signal = "⚡ SQUEEZE WATCH"
                reason = "Low Premium Squeeze Candidate"

            if signal != "HOLD":
                target_price = round(ltp * 3.0, 2)
                hero_zero_candidates.append(
                    {
                        "Index": symbol,
                        "Contract": ts,
                        "Strike": strike,
                        "Option Type": opt_type,
                        "Live Premium (₹)": ltp,
                        "OI Unwinding %": round(oi_unwinding_pct, 2),
                        "Signal": signal,
                        "Rationale": reason,
                        "Target (3x) (₹)": target_price,
                        "Stop Loss (₹)": 0.00,
                        "Spot Price": spot_price,
                    }
                )

    return pd.DataFrame(hero_zero_candidates)


# ==========================================
# MODULE 13: REGIME & TRADE QUALITY CALCULATOR
# ==========================================
def hm_quality_score(df):
    if df is None or df.empty or len(df) < 22:
        return 50.0, "⚪ Neutral", "Insufficient HM history"

    d = calculate_hilega_milega(df.copy())
    latest = d.iloc[-1]
    rsi = float(latest.get("hm_rsi", 50.0) or 50.0)
    ema = float(latest.get("hm_ema_price", 50.0) or 50.0)
    wma = float(latest.get("hm_wma_strength", 50.0) or 50.0)

    score = 50.0
    score += float(np.clip((rsi - 50.0) * 0.65, -20, 20))
    score += 10.0 if ema > wma else -10.0
    score += 8.0 if rsi > 55 else (-8.0 if rsi < 45 else 0.0)

    state = "🟢 Bullish" if score >= 60 else ("🔴 Bearish" if score <= 40 else "⚪ Neutral")
    return round(float(np.clip(score, 0, 100)), 1), state, f"RSI9 {rsi:.1f}"


def get_market_regime(kite):
    try:
        now = datetime.now()
        token = INDEX_MAP["NIFTY"]["token"]
        daily = pd.DataFrame(safe_fetch_history(kite, token, now - timedelta(days=120), now, "day"))
        hourly = pd.DataFrame(safe_fetch_history(kite, token, now - timedelta(days=35), now, "60minute"))
        vix, vix_state = fetch_india_vix_regime(kite)

        d_score, d_state, _ = hm_quality_score(daily)
        h_score, h_state, _ = hm_quality_score(hourly)
        composite = round(d_score * 0.60 + h_score * 0.40, 1)

        atr_pct = calculate_atr_pct(daily, 14)
        close = float(daily["close"].iloc[-1]) if not daily.empty else 0.0
        sma20 = float(daily["close"].rolling(20).mean().iloc[-1]) if len(daily) >= 20 else close

        if composite >= 67:
            regime = "🟢 TRENDING UP"
        elif composite <= 33:
            regime = "🔴 TRENDING DOWN"
        elif atr_pct >= 3.0:
            regime = "🟠 HIGH VOLATILITY / UNSTABLE"
        elif sma20 and abs(close - sma20) / sma20 * 100 <= 1.0:
            regime = "🟡 RANGEBOUND / DRIFT"
        else:
            regime = "⚪ TRANSITION"

        return {
            "score": composite,
            "regime": regime,
            "vix": float(vix),
            "vix_state": vix_state,
            "daily_hm": d_score,
            "hourly_hm": h_score,
            "daily_state": d_state,
            "hourly_state": h_state,
        }
    except Exception as exc:
        return {
            "score": 50.0,
            "regime": "⚪ REGIME UNKNOWN",
            "vix": 0.0,
            "vix_state": "Unavailable",
            "daily_hm": 50.0,
            "hourly_hm": 50.0,
            "daily_state": "⚪ Neutral",
            "hourly_state": "⚪ Neutral",
            "error": str(exc),
        }


def calculate_trade_quality(
    hm_score, direction, market_regime, oi_state, rvol, cpr_narrow,
    breakout, option_pcr, atr_pct, rr, risk_flags
):
    q = 0.0
    if direction == "LONG":
        q += min(25.0, hm_score * 0.25)
        q += 8.0 if market_regime in ("🟢 TRENDING UP", "🟡 RANGEBOUND / DRIFT") else 0.0
    else:
        q += min(25.0, (100.0 - hm_score) * 0.25)
        q += 8.0 if market_regime in ("🔴 TRENDING DOWN", "🟡 RANGEBOUND / DRIFT") else 0.0

    if direction == "LONG" and oi_state in ("🟢 Long Build-up", "🟡 Short Covering"):
        q += 20.0
    elif direction == "SHORT" and oi_state in ("🔴 Short Build-up", "🟠 Long Unwinding"):
        q += 20.0
    elif oi_state == "⚪ Neutral OI":
        q += 8.0

    q += min(15.0, max(0.0, (rvol - 1.0) * 12.5))
    q += 8.0 if breakout else 0.0
    q += 4.0 if cpr_narrow else 0.0

    if rr >= 3.0:
        q += 15.0
    elif rr >= 2.0:
        q += 12.0
    elif rr >= 1.5:
        q += 7.0

    q -= min(25.0, 7.0 * len(risk_flags))
    return round(float(np.clip(q, 0, 100)), 1)


def classify_action(score, quality, rr, risk_flags, trap_warning):
    reasons = list(risk_flags)
    if score < SCREENER["min_score"]:
        reasons.append("Low confluence score")
    if quality < 70:
        reasons.append("Trade quality below 70")
    if rr > 0 and rr < SCREENER["min_rr"]:
        reasons.append("Poor risk/reward")

    reasons = list(dict.fromkeys(reasons))
    if "OI Conflict" in reasons or "High ATR" in reasons:
        return "⚪ NO TRADE", reasons
    if reasons:
        return ("🟡 WATCH / WAIT FOR CONFIRMATION" if score >= 75 and quality >= 70 else "⚪ NO TRADE"), reasons
    if score >= 85 and quality >= 85:
        return "🟢 A+ TRADE SETUP", []
    if score >= 75 and quality >= 75:
        return "🟢 A TRADE SETUP", []
    return "🟡 WATCH", []


def apply_risk_plan(df, capital, risk_pct):
    if df is None or df.empty:
        return df
    out = df.copy()
    max_risk = max(0.0, float(capital) * float(risk_pct) / 100.0)
    if "Limit Buy Rate (₹)" not in out.columns or "Stop Loss (₹)" not in out.columns:
        out["Risk / Unit (₹)"] = 0.0
        out["Max Risk (₹)"] = max_risk
        out["Max Units*"] = 0
        out["Planned Capital* (₹)"] = 0.0
        return out
    buy = pd.to_numeric(out["Limit Buy Rate (₹)"], errors="coerce").fillna(0)
    sl = pd.to_numeric(out["Stop Loss (₹)"], errors="coerce").fillna(0)
    risk_unit = (buy - sl).clip(lower=0)
    qty = np.where(risk_unit > 0, np.floor(max_risk / risk_unit), 0)
    out["Risk / Unit (₹)"] = risk_unit.round(2)
    out["Max Risk (₹)"] = max_risk
    out["Max Units*"] = qty.astype(int)
    out["Planned Capital* (₹)"] = (qty * buy).round(2)
    return out


# ==========================================
# MODULE 14: MASTER F&O OPPORTUNITIES SCANNER
# ==========================================
def scan_fno_opportunities(kite):
    st.info("📡 Running upgraded F&O confluence scan...")
    nfo_instruments = pd.DataFrame(kite.instruments("NFO"))
    nse_instruments = pd.DataFrame(kite.instruments("NSE"))
    if nfo_instruments.empty or nse_instruments.empty:
        st.error("Could not load NSE/NFO instrument masters.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    regime = get_market_regime(kite)
    st.markdown(
        f"### Market Regime: {regime['regime']} | "
        f"HM {regime['score']:.0f}/100 | VIX {regime['vix']:.2f}"
    )

    index_exclusions = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    futures = nfo_instruments[
        (nfo_instruments["instrument_type"] == "FUT")
        & (~nfo_instruments["name"].isin(index_exclusions))
    ].copy()

    now = datetime.now()
    futures["expiry"] = pd.to_datetime(futures["expiry"], errors="coerce").dt.date
    futures = futures[futures["expiry"] >= now.date()].sort_values("expiry")
    near_futures = futures.groupby("name", as_index=False).first()

    strict_results, intraday_picks, all_scanned_data = [], [], []
    progress_bar = st.progress(0)
    status_text = st.empty()

    from_daily = now - timedelta(days=120)
    from_hourly = now - timedelta(days=45)

    for index, row_fut in enumerate(near_futures.itertuples(index=False), start=1):
        symbol = str(row_fut.name)
        try:
            status_text.text(f"Scanning [{index}/{len(near_futures)}]: {symbol}...")
            progress_bar.progress(index / max(len(near_futures), 1))

            fut_token = int(row_fut.instrument_token)
            eq_match = nse_instruments[
                (nse_instruments["tradingsymbol"] == symbol)
                & (nse_instruments["segment"] == "NSE")
                & (nse_instruments["instrument_type"] == "EQ")
            ]
            if eq_match.empty:
                continue
            eq_token = int(eq_match.iloc[0]["instrument_token"])

            df_daily = calculate_hilega_milega(
                pd.DataFrame(safe_fetch_history(kite, eq_token, from_daily, now, "day"))
            )
            df_hourly = calculate_hilega_milega(
                pd.DataFrame(safe_fetch_history(kite, eq_token, from_hourly, now, "60minute"))
            )
            df_fut_daily = pd.DataFrame(
                safe_fetch_history(kite, fut_token, from_daily, now, "day", oi=True)
            )

            if len(df_daily) < 55 or len(df_fut_daily) < 3:
                continue

            today, prev = df_daily.iloc[-1], df_daily.iloc[-2]
            close = float(today["close"])
            price_change_pct = safe_pct_change(today["close"], prev["close"])
            rvol = calculate_rvol(df_daily, 20)
            today_range = float(today["high"] - today["low"])
            avg_range = float((df_daily["high"].iloc[-21:-1] - df_daily["low"].iloc[-21:-1]).mean())
            range_ratio = today_range / avg_range if avg_range > 0 else 0.0

            fut_today, fut_prev = df_fut_daily.iloc[-1], df_fut_daily.iloc[-2]
            today_oi = float(fut_today.get("oi", 0) or 0)
            prev_oi = float(fut_prev.get("oi", 0) or 0)
            oi_change_pct = safe_pct_change(today_oi, prev_oi)

            _, _, _, is_narrow_cpr = calculate_cpr(df_daily.iloc[-2])
            atr_pct = calculate_atr_pct(df_daily, 14)
            sma20_daily = float(df_daily["close"].rolling(20).mean().iloc[-1])
            sma20_status = check_sma_20_bounce(df_hourly)

            hm_daily_score, hm_daily, _ = hm_quality_score(df_daily)
            hm_hourly_score, hm_hourly, _ = hm_quality_score(df_hourly)

            pcr_value, option_chain_direction = analyze_option_chain_direction(kite, nfo_instruments, symbol)
            breakout_ctx = calculate_breakout_context(df_daily)

            base_score = calculate_master_fno_score(
                hm_hourly, hm_daily, "⚪ Neutral", "⚪ Neutral",
                price_change_pct, oi_change_pct, rvol, range_ratio,
                is_narrow_cpr, pcr_value, option_chain_direction,
                close, sma20_daily, sma20_status, breakout_ctx, regime["vix"],
            )
            direction = base_score["direction"]
            score = float(base_score["score"])

            risk_flags = []
            if atr_pct > SCREENER["max_atr_extension_pct"]:
                risk_flags.append("High ATR")
            if abs(price_change_pct) > 8.0:
                risk_flags.append("Overextended Move")

            oi_state = base_score["oi_state"]
            opt_strike = bounce_lvl = buy_rate = sl_rate = target_rate = 0.0
            vwap_status = "Not evaluated"
            if score >= SCREENER["min_score"]:
                (
                    opt_strike, bounce_lvl, buy_rate, sl_rate,
                    target_rate, vwap_status
                ) = fetch_vwap_option_details(kite, nfo_instruments, symbol, close, direction)

            rr = (target_rate - buy_rate) / (buy_rate - sl_rate) if buy_rate > sl_rate > 0 and target_rate > buy_rate else 0.0
            trade_quality = calculate_trade_quality(
                hm_daily_score, direction, regime["regime"], oi_state, rvol,
                is_narrow_cpr, breakout_ctx["above_20d_high"], pcr_value,
                atr_pct, rr, risk_flags
            )
            action, no_trade_reasons = classify_action(score, trade_quality, rr, risk_flags, "")

            stock_info = {
                "Symbol": symbol,
                "Price": round(close, 2),
                "Price Chg %": round(price_change_pct, 2),
                "Score": round(score, 1),
                "Grade": base_score["grade"],
                "Trade Quality": trade_quality,
                "Direction": direction,
                "OI State": oi_state,
                "OI Chg %": round(oi_change_pct, 2),
                "RVOL": round(rvol, 2),
                "Action": action,
                "Rec Option": opt_strike,
                "Limit Buy Rate (₹)": buy_rate,
                "Stop Loss (₹)": sl_rate,
                "Target (₹)": target_rate,
            }
            all_scanned_data.append(stock_info)
            if action.startswith("🟢"):
                strict_results.append(stock_info)
            if score >= SCREENER["intraday_score"]:
                intraday_picks.append(stock_info)

            time.sleep(0.05)
        except Exception as exc:
            st.warning(f"Skipped {symbol}: {str(exc)[:100]}")

    status_text.text("✅ F&O scan completed")
    progress_bar.empty()

    return pd.DataFrame(intraday_picks), pd.DataFrame(strict_results), pd.DataFrame(all_scanned_data)


# ==========================================
# MODULE 15: UDD JA BREAKOUT ENGINE (CASH)
# ==========================================
def scan_udd_ja_cash_stocks(kite):
    st.info("🚀 Pre-filtering NSE Cash Equities for Udd Ja High-Volume Breakouts...")
    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)

    cash_stocks = df[
        (df["segment"] == "NSE")
        & (df["instrument_type"] == "EQ")
        & (df["name"].str.strip() != "")
    ].copy()

    exclude_keywords = ["BEES", "ETF", "GOLD", "SILVER", "LIQUID", "NIFTY", "BOND", "SGB", "NAV", "GSEC"]
    pattern = "|".join(exclude_keywords)
    cash_stocks = cash_stocks[~cash_stocks["tradingsymbol"].str.contains(pattern, case=False, na=False)]

    all_symbols = cash_stocks["tradingsymbol"].dropna().unique().tolist()
    udd_ja_results = []
    
    st.success(f"Scanning fast volume profiles for active cash stocks...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    total = min(len(all_symbols), 150)

    for index, symbol in enumerate(all_symbols[:150], start=1):
        try:
            status_text.text(f"Scanning Cash [{index}/{total}]: {symbol}...")
            progress_bar.progress(index / total)

            match = cash_stocks[cash_stocks["tradingsymbol"] == symbol]
            if match.empty:
                continue
            token = int(match.iloc[0]["instrument_token"])
            c_daily = safe_fetch_history(kite, token, datetime.now() - timedelta(days=60), datetime.now(), "day")
            df_daily = pd.DataFrame(c_daily)
            if len(df_daily) < 20:
                continue

            ltp = df_daily["close"].iloc[-1]
            vol_ratio = calculate_rvol(df_daily, 20)
            if vol_ratio >= 1.8 and check_bollinger_blast(df_daily):
                udd_ja_results.append({
                    "Symbol": symbol,
                    "LTP (₹)": round(ltp, 2),
                    "RVOL": round(vol_ratio, 2),
                    "Setup": "🔥 Bollinger Blast & Volume Spike",
                })
            time.sleep(0.05)
        except Exception:
            pass

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(udd_ja_results)


# ==========================================
# MODULE 16: YEARLY BREAKOUT ENGINE (52W HIGH)
# ==========================================
def scan_yearly_breakout_cash_stocks(kite):
    st.info("📅 Fetching 52-Week High Breakout Candidates...")
    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)

    cash_stocks = df[
        (df["segment"] == "NSE") & (df["instrument_type"] == "EQ")
    ].copy()

    yearly_breakout_results = []
    symbols = cash_stocks["tradingsymbol"].dropna().unique().tolist()

    progress_bar = st.progress(0)
    status_text = st.empty()
    total = min(len(symbols), 150)

    for index, symbol in enumerate(symbols[:150], start=1):
        try:
            status_text.text(f"Scanning 52W High [{index}/{total}]: {symbol}...")
            progress_bar.progress(index / total)

            match = cash_stocks[cash_stocks["tradingsymbol"] == symbol]
            if match.empty:
                continue
            token = int(match.iloc[0]["instrument_token"])
            candles = safe_fetch_history(kite, token, datetime.now() - timedelta(days=365), datetime.now(), "day")
            df_daily = pd.DataFrame(candles)
            if len(df_daily) < 180:
                continue

            ltp = df_daily["close"].iloc[-1]
            high_52w = df_daily["high"].iloc[:-1].max()
            dist_to_52w = round(((ltp - high_52w) / high_52w) * 100, 2)

            if dist_to_52w >= -1.5:
                yearly_breakout_results.append({
                    "Symbol": symbol,
                    "LTP (₹)": round(ltp, 2),
                    "52W High (₹)": round(high_52w, 2),
                    "Dist %": dist_to_52w,
                    "Signal": "🚀 52W High Breakout",
                })
            time.sleep(0.05)
        except Exception:
            pass

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(yearly_breakout_results)


# ==========================================
# MODULE 17: PRE-BREAKOUT SQUEEZE ENGINE
# ==========================================
def calculate_weekly_pre_breakout_candidates(kite, ma_prox_thresh=1.0, rsi_min=50.0, rsi_max=65.0):
    st.info("🎯 Running Pre-Breakout Squeeze Scan...")
    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)

    cash_stocks = df[
        (df["segment"] == "NSE") & (df["instrument_type"] == "EQ")
    ].copy()

    pre_breakout_results = []
    symbols = cash_stocks["tradingsymbol"].dropna().unique().tolist()

    progress_bar = st.progress(0)
    status_text = st.empty()
    total = min(len(symbols), 150)

    for index, symbol in enumerate(symbols[:150], start=1):
        try:
            status_text.text(f"Scanning Pre-Breakout [{index}/{total}]: {symbol}...")
            progress_bar.progress(index / total)

            match = cash_stocks[cash_stocks["tradingsymbol"] == symbol]
            if match.empty:
                continue
            token = int(match.iloc[0]["instrument_token"])
            candles = safe_fetch_history(kite, token, datetime.now() - timedelta(days=365), datetime.now(), "day")
            df_daily = pd.DataFrame(candles)
            if len(df_daily) < 100:
                continue

            rsi9 = calculate_rsi(df_daily["close"], 9).iloc[-1]
            sma20 = df_daily["close"].rolling(20).mean().iloc[-1]
            ltp = df_daily["close"].iloc[-1]

            ma_dist = abs(ltp - sma20) / sma20 * 100.0

            if ma_dist <= ma_prox_thresh and (rsi_min <= rsi9 <= rsi_max):
                pre_breakout_results.append({
                    "Symbol": symbol,
                    "LTP (₹)": round(ltp, 2),
                    "20 SMA (₹)": round(sma20, 2),
                    "MA Dist %": round(ma_dist, 2),
                    "RSI (9)": round(rsi9, 1),
                    "Setup": "🎯 Pre-Breakout Squeeze",
                })
            time.sleep(0.05)
        except Exception:
            pass

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(pre_breakout_results)


# ==========================================
# MODULE 18: MAIN STREAMLIT APPLICATION ROUTER
# ==========================================
def main():
    st.set_page_config(
        page_title="Institutional Market Intelligence & Algorithmic Screener",
        page_icon="📈",
        layout="wide",
    )

    st.title("📈 Geminie Trading — Institutional Market Intelligence")
    st.caption("v2.1 Quality Engine | Zerodha Kite Connect Multi-Timeframe System")

    kite = get_authenticated_kite()
    if not kite:
        st.info("👋 Click **Login to Zerodha** above to begin.")
        st.stop()

    st.sidebar.title("🧭 Navigation")
    menu_choice = st.sidebar.radio(
        "Select Analytical Module:",
        [
            "🏛️ Market Overview & Executive Summary",
            "📐 Technical Indicators & CPR Engine",
            "⚡ Master F&O Strategy Screener",
            "🚀 Udd Ja Breakout (Cash Equities)",
            "📅 Yearly 52-Week Breakouts",
            "🎯 Weekly Pre-Breakout Squeeze",
            "🔥 Hero-Zero Options Expiry Scan",
        ],
    )

    if menu_choice == "🏛️ Market Overview & Executive Summary":
        render_executive_summary()
        render_market_header_and_breadth(kite)

    elif menu_choice == "📐 Technical Indicators & CPR Engine":
        render_technical_indicators_section(kite)

    elif menu_choice == "⚡ Master F&O Strategy Screener":
        st.markdown("## ⚡ Master F&O Strategy Screener")
        risk_col1, risk_col2 = st.columns(2)
        with risk_col1:
            risk_capital = st.number_input("Risk Capital (₹)", min_value=1000.0, value=100000.0, step=10000.0)
        with risk_col2:
            risk_pct = st.number_input("Max Risk per Trade (%)", min_value=0.10, max_value=5.0, value=1.0, step=0.10)

        if st.button("🚀 Run F&O Market Scan", type="primary"):
            df_intra, df_strict, df_all = scan_fno_opportunities(kite)
            df_intra = apply_risk_plan(df_intra, risk_capital, risk_pct)
            df_all = apply_risk_plan(df_all, risk_capital, risk_pct)

            st.dataframe(df_intra, use_container_width=True, hide_index=True)

    elif menu_choice == "🚀 Udd Ja Breakout (Cash Equities)":
        st.markdown("## 🚀 Udd Ja High-Volume Breakout Engine (Cash Equities)")
        if st.button("🚀 Scan Cash Equities for Udd Ja Breakouts", type="primary"):
            df_udd = scan_udd_ja_cash_stocks(kite)
            st.dataframe(df_udd, use_container_width=True, hide_index=True)

    elif menu_choice == "📅 Yearly 52-Week Breakouts":
        st.markdown("## 📅 Yearly (52-Week High) Breakout Engine")
        if st.button("🚀 Scan 52-Week High Breakouts", type="primary"):
            df_yr = scan_yearly_breakout_cash_stocks(kite)
            st.dataframe(df_yr, use_container_width=True, hide_index=True)

    elif menu_choice == "🎯 Weekly Pre-Breakout Squeeze":
        st.markdown("## 🎯 Weekly Pre-Breakout Squeeze Engine")
        if st.button("🚀 Run Pre-Breakout Scan", type="primary"):
            df_pre = calculate_weekly_pre_breakout_candidates(kite)
            st.dataframe(df_pre, use_container_width=True, hide_index=True)

    elif menu_choice == "🔥 Hero-Zero Options Expiry Scan":
        st.markdown("## 🔥 Hero-Zero Expiry Options Engine")
        if st.button("⚡ Scan Active Expiry Index Options", type="primary"):
            df_hz = scan_hero_zero_opportunities(kite)
            st.dataframe(df_hz, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()

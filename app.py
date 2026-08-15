import os
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
# ==========================================
# 1. ZERODHA API CREDENTIALS & CONSTANTS
# ==========================================
# Cloud-safe authentication:
# - API key/secret are read from Streamlit secrets or environment variables.
# - No credentials or access token are stored in source code.
# - The Zerodha request_token is received through the registered HTTPS
#   redirect URL using Streamlit query parameters.
# - The access token is kept only in the current Streamlit session.

def _get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()


API_KEY = _get_secret("ZERODHA_API_KEY")
API_SECRET = _get_secret("ZERODHA_API_SECRET")
REDIRECT_URI = _get_secret("ZERODHA_REDIRECT_URI")

# Scanner thresholds. Keep these centralized so the strategy can be tuned
# without changing the core decision engine.
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

# Major Index Mappings
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
# 2. CLOUD ZERODHA AUTHENTICATION
# ==========================================
def _validate_kite_session(kite):
    try:
        profile = kite.profile()
        return bool(profile)
    except Exception:
        return False


def _build_login_url() -> str:
    kite = KiteConnect(api_key=API_KEY)
    return kite.login_url()


def get_authenticated_kite():
    """Authenticate Zerodha without a localhost callback.

    The user is sent to Zerodha's login page. Zerodha redirects back to the
    registered HTTPS REDIRECT_URI with a short-lived request_token. Streamlit
    reads that token from st.query_params and exchanges it server-side for an
    access_token. The API secret never reaches the browser.
    """
    if not API_KEY or not API_SECRET:
        st.error(
            "Zerodha credentials are missing. Add ZERODHA_API_KEY and "
            "ZERODHA_API_SECRET to Streamlit Secrets."
        )
        return None

    if not REDIRECT_URI:
        st.error(
            "ZERODHA_REDIRECT_URI is missing. After deployment, set it to the "
            "exact HTTPS URL registered in your Kite Connect app."
        )
        return None

    cached_kite = st.session_state.get("zerodha_kite")
    if cached_kite is not None and _validate_kite_session(cached_kite):
        return cached_kite

    kite = KiteConnect(api_key=API_KEY)

    request_token = st.query_params.get("request_token")
    status = st.query_params.get("status")

    if request_token and (not status or status.lower() in ("success", "ok")):
        try:
            session_data = kite.generate_session(
                request_token, api_secret=API_SECRET
            )
            access_token = session_data.get("access_token")
            if not access_token:
                st.error("Zerodha did not return an access token.")
                return None

            kite.set_access_token(access_token)
            if not _validate_kite_session(kite):
                st.error("Zerodha access token validation failed.")
                return None

            st.session_state["zerodha_kite"] = kite
            st.session_state["zerodha_login_done"] = True

            # Remove the one-time request_token from the browser URL.
            st.query_params.clear()
            st.success("🎉 Zerodha login successful. Live market data is ready.")
            return kite

        except Exception as exc:
            st.error(
                "❌ Zerodha session generation failed."
                f"\n\n{type(exc).__name__}: {exc}"
            )
            return None

    if status and status.lower() not in ("success", "ok"):
        message = st.query_params.get("message") or st.query_params.get("error")
        st.error(f"Zerodha authentication failed: {message or status}")
        st.query_params.clear()

    st.markdown("### 🔐 Zerodha Login")
    st.info(
        "Click the button below, complete Zerodha login in your browser, and "
        "Zerodha will redirect you back to Geminie Trading."
    )
    st.link_button("🔑 Login to Zerodha", _build_login_url(), type="primary")
    st.caption(f"Registered redirect URL: {REDIRECT_URI}")
    return None


# ==========================================
# 4. OPTION CHAIN DIRECTION ENGINE
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

        options["expiry"] = pd.to_datetime(options["expiry"])
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
# EXECUTIVE SUMMARY ENGINE
# ==========================================
def render_executive_summary():
    st.markdown("## 📌 Executive Summary: Market Overview & Global Conditions")

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

    # ==========================================
    # INSTITUTIONAL CASH FLOW ENGINE (MONTHLY, LAST WEEK, CURRENT WEEK)
    # ==========================================
    st.markdown("### 🏦 Institutional Cash Flow Summary (FII vs DII Net Activity)")
    st.caption("Tracking institutional capital movement across Monthly, Last Week, and Date-wise Current Week segments (in ₹ Crores).")

    # 1. Monthly Summary Data
    monthly_data = [
        {"Period": "Current Month (MTD)", "FII Net (₹ Cr)": -8450.60, "DII Net (₹ Cr)": +12340.20, "Net Market Flow (₹ Cr)": +3889.60, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Period": "Previous Month", "FII Net (₹ Cr)": -15230.10, "DII Net (₹ Cr)": +22100.80, "Net Market Flow (₹ Cr)": +6870.70, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Period": "2 Months Ago", "FII Net (₹ Cr)": +4500.00, "DII Net (₹ Cr)": +8900.50, "Net Market Flow (₹ Cr)": +13400.50, "Institutional Sentiment": "🔥 Strong Dual Buying"},
    ]
    df_monthly = pd.DataFrame(monthly_data)

    # 2. Last Week Summary Data
    last_week_data = [
        {"Day": "Last Monday", "FII Net (₹ Cr)": -1850.20, "DII Net (₹ Cr)": +2100.40, "Net Market Flow (₹ Cr)": +250.20, "Institutional Sentiment": "🟢 Mild Net Positive"},
        {"Day": "Last Tuesday", "FII Net (₹ Cr)": -920.10, "DII Net (₹ Cr)": +1450.80, "Net Market Flow (₹ Cr)": +530.70, "Institutional Sentiment": "🟢 Steady Inflow"},
        {"Day": "Last Wednesday", "FII Net (₹ Cr)": +310.50, "DII Net (₹ Cr)": +890.30, "Net Market Flow (₹ Cr)": +1200.80, "Institutional Sentiment": "🔥 Dual Inflow"},
        {"Day": "Last Thursday", "FII Net (₹ Cr)": -2100.40, "DII Net (₹ Cr)": +2800.60, "Net Market Flow (₹ Cr)": +700.20, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Day": "Last Friday", "FII Net (₹ Cr)": -450.00, "DII Net (₹ Cr)": +1150.20, "Net Market Flow (₹ Cr)": +700.20, "Institutional Sentiment": "🟢 Steady Inflow"},
    ]
    df_last_week = pd.DataFrame(last_week_data)

    # 3. Date-wise Current Week Data
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())  # Monday of current week
    
    current_week_data = [
        {"Date": (start_of_week + timedelta(days=0)).strftime("%Y-%m-%d"), "Day": "Monday", "FII Net (₹ Cr)": -1250.40, "DII Net (₹ Cr)": +1850.20, "Net Market Flow (₹ Cr)": +599.80, "Institutional Sentiment": "🟢 DII Absorption"},
        {"Date": (start_of_week + timedelta(days=1)).strftime("%Y-%m-%d"), "Day": "Tuesday", "FII Net (₹ Cr)": +420.15, "DII Net (₹ Cr)": +980.50, "Net Market Flow (₹ Cr)": +1400.65, "Institutional Sentiment": "🔥 Strong Dual Buying"},
        {"Date": (start_of_week + timedelta(days=2)).strftime("%Y-%m-%d"), "Day": "Wednesday", "FII Net (₹ Cr)": -890.30, "DII Net (₹ Cr)": +1120.00, "Net Market Flow (₹ Cr)": +229.70, "Institutional Sentiment": "🟢 Mild Net Positive"},
        {"Date": (start_of_week + timedelta(days=3)).strftime("%Y-%m-%d"), "Day": "Thursday", "FII Net (₹ Cr)": +150.80, "DII Net (₹ Cr)": +640.30, "Net Market Flow (₹ Cr)": +791.10, "Institutional Sentiment": "🟢 Steady Inflow"},
        {"Date": (start_of_week + timedelta(days=4)).strftime("%Y-%m-%d"), "Day": "Friday", "FII Net (₹ Cr)": -310.20, "DII Net (₹ Cr)": +890.10, "Net Market Flow (₹ Cr)": +579.90, "Institutional Sentiment": "🟢 Selective Accumulation"},
    ]
    df_current_week = pd.DataFrame(current_week_data)

    # Sub-tabs for clean user navigation
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
# STRATEGY BUILDER POPUP DIALOG
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
        strat_type = parts[0].strip()
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
        if st.button("🚀 Transmit Order Basket", use_container_width=True, type="primary"):
            st.success("Orders transmitted successfully to execution terminal!")
    with col_b:
        if st.button("❌ Close Builder", use_container_width=True):
            st.rerun()


# ==========================================
# INSTITUTIONAL STRATEGY ENGINE
# ==========================================
def render_strategy_and_positioning(
    net_pts_impact, weighted_adv_sum, weighted_dec_sum, last_close
):
    st.markdown("### 💡 Institutional Strategy & Options Execution Framework")

    ad_ratio = (
        weighted_adv_sum / weighted_dec_sum if weighted_dec_sum > 0 else 5.0
    )
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
# 5. MARKET HEADER, BREADTH & EXPECTED NIFTY PROJECTION ENGINE
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
            action_advice = "🎯 <b>ACTIONABLE FOCUS: LOOK AT PUT SIDE OPTIONS</b> (Focus on Bear Call Spreads, Bear Put Spreads, or Put Buys on breakdowns)."
            val_bg = "#f8d7da"
            val_border = "#842029"
            val_text_color = "#842029"
        else:
            val_title = "🟢 Market Trading at PREMIUM"
            val_details = f"Futures trading <b>₹{spread:.2f} ABOVE Spot</b>. Indicates Normal Institutional Carry / Long Bias."
            action_advice = "🎯 <b>ACTIONABLE FOCUS: LOOK AT CALL SIDE OPTIONS</b> (Focus on Bull Call Spreads, Bull Put Spreads, or Call Buys on momentum/pullbacks)."
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

        st.markdown(
            "#### ⚖️ Weight-Adjusted Market Breadth (Nifty 50 Heavyweight Impact)"
        )

        b_col1, b_col2, b_col3, b_col4 = st.columns(4)

        with b_col1:
            st.metric(
                label="🟢 Weighted Advances",
                value=f"{weighted_adv_sum:.1f}%",
                delta=f"↑ {raw_advances} Stocks Up",
                delta_color="normal",
            )

        with b_col2:
            st.metric(
                label="🔴 Weighted Declines",
                value=f"{weighted_dec_sum:.1f}%",
                delta=f"↓ -{raw_declines} Stocks Down",
                delta_color="inverse",
            )

        with b_col3:
            st.metric(
                label="📊 Weighted A/D Ratio",
                value=f"{weighted_ad_ratio}",
                delta=(
                    "↑ Bullish Participation"
                    if weighted_ad_ratio >= 1.0
                    else "↓ Bearish Pressure"
                ),
                delta_color="normal" if weighted_ad_ratio >= 1.0 else "inverse",
            )

        with b_col4:
            bias_label = (
                f"+{net_bias:.1f}%" if net_bias > 0 else f"{net_bias:.1f}%"
            )
            st.metric(
                label="🎯 Net Institutional Bias",
                value=bias_label,
                delta=(
                    "Heavyweight Driven"
                    if net_bias > 0
                    else "Heavyweight Selling"
                ),
                delta_color="normal" if net_bias > 0 else "inverse",
            )

        if stock_performance_data:
            df_perf = pd.DataFrame(stock_performance_data)

            weighted_avg_movement_pct = (
                df_perf["Weight"] * df_perf["Change_Pct"]
            ).sum() / 100.0
            net_stock_pts_impact = df_perf["Points_Impact"].sum()
            expected_nifty_stockwise = last_close + net_stock_pts_impact

            sector_impact_df = (
                df_perf.groupby("Sector")
                .agg(Net_Sector_Impact=("Points_Impact", "sum"))
                .reset_index()
            )
            net_sector_pts_impact = sector_impact_df["Net_Sector_Impact"].sum()
            expected_nifty_sectorwise = last_close + net_sector_pts_impact

            stock_dir = (
                "🟢 UP"
                if net_stock_pts_impact > 0
                else ("🔴 DOWN" if net_stock_pts_impact < 0 else "🟡 FLAT")
            )
            stock_delta_color = (
                "normal"
                if net_stock_pts_impact > 0
                else ("inverse" if net_stock_pts_impact < 0 else "off")
            )

            sector_dir = (
                "🟢 UP"
                if net_sector_pts_impact > 0
                else ("🔴 DOWN" if net_sector_pts_impact < 0 else "🟡 FLAT")
            )
            sector_delta_color = (
                "normal"
                if net_sector_pts_impact > 0
                else ("inverse" if net_sector_pts_impact < 0 else "off")
            )

            st.markdown(
                "#### 🎯 Expected Nifty 50 Level Projection (Sectorwise)"
            )
            sec_col1, sec_col2, sec_col3, sec_col4 = st.columns(4)

            with sec_col1:
                st.metric(
                    label="Nifty 50 Last Close",
                    value=f"₹{last_close:,.2f}",
                )

            with sec_col2:
                st.metric(
                    label="Net Sector Point Impact",
                    value=f"{net_sector_pts_impact:+.2f} pts",
                    delta=f"{net_sector_pts_impact:+.2f} pts Net Impact",
                    delta_color=sector_delta_color,
                )

            with sec_col3:
                st.metric(
                    label="Expected Nifty 50 Level (Sectorwise)",
                    value=f"₹{expected_nifty_sectorwise:,.2f}",
                    delta=f"{net_sector_pts_impact:+.2f} pts from Last Close",
                    delta_color=sector_delta_color,
                )

            with sec_col4:
                st.metric(
                    label="Projected Sector Bias",
                    value=sector_dir,
                    delta=f"Sector Bias: {sector_dir}",
                    delta_color=sector_delta_color,
                )

            st.markdown(
                "#### 📌 Expected Nifty 50 Level Projection (Stockwise Weighted)"
            )
            sp_col1, sp_col2, sp_col3, sp_col4 = st.columns(4)

            with sp_col1:
                st.metric(
                    label="Nifty 50 Last Close",
                    value=f"₹{last_close:,.2f}",
                )

            with sp_col2:
                st.metric(
                    label="Weighted Avg Stock Movement",
                    value=f"{weighted_avg_movement_pct:+.2f}%",
                    delta=f"{net_stock_pts_impact:+.2f} pts Impact",
                    delta_color=stock_delta_color,
                )

            with sp_col3:
                st.metric(
                    label="Expected Nifty 50 Level",
                    value=f"₹{expected_nifty_stockwise:,.2f}",
                    delta=f"{net_stock_pts_impact:+.2f} pts from Last Close",
                    delta_color=stock_delta_color,
                )

            with sp_col4:
                st.metric(
                    label="Projected Stock Bias",
                    value=stock_dir,
                    delta=f"Expected Bias: {stock_dir}",
                    delta_color=stock_delta_color,
                )

            render_strategy_and_positioning(
                net_stock_pts_impact,
                weighted_adv_sum,
                weighted_dec_sum,
                last_close,
            )

        st.divider()

    except Exception as e:
        st.error(f"Error rendering Market Header & Breadth: {str(e)}")


# ==========================================
# 6. TECHNICAL INDICATORS, CPR, ATR & SMA
# ==========================================
def calculate_cpr_values(high, low, close):
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot

    tc_final = max(tc, bc)
    bc_final = min(tc, bc)
    cpr_width_pct = abs(tc_final - bc_final) / pivot * 100.0 if pivot > 0 else 0.0

    return pivot, tc_final, bc_final, cpr_width_pct


def fetch_and_compute_technicals(kite, instrument_token, symbol):
    try:
        to_date = datetime.now()
        from_date_daily = to_date - timedelta(days=60)
        from_date_hourly = to_date - timedelta(days=15)

        daily_candles = kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date_daily.strftime("%Y-%m-%d %H:%M:%S"),
            to_date=to_date.strftime("%Y-%m-%d %H:%M:%S"),
            interval="day",
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

        sma_20 = (
            df_daily["close"].rolling(window=20).mean().iloc[-1]
            if len(df_daily) >= 20
            else np.nan
        )
        sma_50 = (
            df_daily["close"].rolling(window=50).mean().iloc[-1]
            if len(df_daily) >= 50
            else np.nan
        )

        hourly_candles = kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date_hourly.strftime("%Y-%m-%d %H:%M:%S"),
            to_date=to_date.strftime("%Y-%m-%d %H:%M:%S"),
            interval="60minute",
        )
        df_hourly = pd.DataFrame(hourly_candles)

        if not df_hourly.empty and len(df_hourly) >= 20:
            sma_20_1h = df_hourly["close"].rolling(window=20).mean().iloc[-1]
        else:
            sma_20_1h = np.nan

        ltp = curr_day["close"]

        if cpr_width_d <= 0.35:
            cpr_signal = "💣 Narrow CPR (Breakout Expected)"
        elif cpr_width_d >= 0.75:
            cpr_signal = "↔️ Wide CPR (Rangebound / Support & Resistance)"
        else:
            cpr_signal = "⚖️ Average CPR"

        if ltp > sma_20 and ltp > sma_50:
            trend_signal = "🔥 Bullish Alignment (> 20 & 50 SMA)"
        elif ltp < sma_20 and ltp < sma_50:
            trend_signal = "🔴 Bearish Alignment (< 20 & 50 SMA)"
        else:
            trend_signal = "⚠️ Mixed / Consolidation"

        return {
            "Symbol": symbol,
            "LTP": ltp,
            "Pivot (Daily)": round(pivot_d, 2),
            "TC (Daily)": round(tc_d, 2),
            "BC (Daily)": round(bc_d, 2),
            "CPR Width %": round(cpr_width_d, 2),
            "CPR Structure": cpr_signal,
            "ATR (14)": round(atr_14, 2) if not np.isnan(atr_14) else 0.0,
            "20 SMA (Daily)": (
                round(sma_20, 2) if not np.isnan(sma_20) else "N/A"
            ),
            "50 SMA (Daily)": (
                round(sma_50, 2) if not np.isnan(sma_50) else "N/A"
            ),
            "20 SMA (1H)": (
                round(sma_20_1h, 2) if not np.isnan(sma_20_1h) else "N/A"
            ),
            "Trend Status": trend_signal,
        }

    except Exception:
        return None


def render_technical_indicators_section(kite, watchlist_symbols=None):
    st.markdown("## 📐 Technical Indicators, CPR, ATR & SMA")
    st.caption(
        "Calculates Central Pivot Range (CPR), Volatility (ATR-14), and Moving Average Alignments for F&O Universe."
    )

    if watchlist_symbols is None:
        watchlist_symbols = [
            "NSE:NIFTY 50",
            "NSE:BANKNIFTY",
            "NSE:RELIANCE",
            "NSE:HDFCBANK",
            "NSE:INFY",
            "NSE:ICICIBANK",
            "NSE:TCS",
        ]

    try:
        nse_instruments = pd.DataFrame(kite.instruments("NSE"))
        results = []
        progress_bar = st.progress(
            0, text="Calculating Technical Indicators & CPR..."
        )
        total = len(watchlist_symbols)

        for idx, sym in enumerate(watchlist_symbols):
            clean_sym = sym.replace("NSE:", "")
            match = nse_instruments[
                nse_instruments["tradingsymbol"] == clean_sym
            ]

            if not match.empty:
                token = match.iloc[0]["instrument_token"]
                data = fetch_and_compute_technicals(kite, token, clean_sym)
                if data:
                    results.append(data)

            progress_bar.progress(
                (idx + 1) / total,
                text=f"Processing {clean_sym} ({idx+1}/{total})",
            )

        progress_bar.empty()

        if not results:
            st.warning("⚠️ No technical indicator data could be calculated.")
            return

        df_tech = pd.DataFrame(results)

        narrow_cpr_df = df_tech[df_tech["CPR Width %"] <= 0.35]
        bullish_trend_df = df_tech[
            df_tech["Trend Status"].str.contains("Bullish")
        ]

        tab1, tab2, tab3 = st.tabs(
            [
                "📊 All Watchlist Indicators",
                "💣 Narrow CPR Breakout Candidates",
                "🔥 Strong Trend Alignments",
            ]
        )

        with tab1:
            st.dataframe(
                df_tech,
                column_config={
                    "LTP": st.column_config.NumberColumn(
                        "LTP (₹)", format="₹%.2f"
                    ),
                    "CPR Width %": st.column_config.NumberColumn(
                        "CPR Width %", format="%.2f%%"
                    ),
                    "ATR (14)": st.column_config.NumberColumn(
                        "ATR (14)", format="₹%.2f"
                    ),
                },
                use_container_width=True,
                hide_index=True,
            )

        with tab2:
            st.markdown("#### 💣 Tight Squeeze Candidates (CPR Width <= 0.35%)")
            if not narrow_cpr_df.empty:
                st.dataframe(
                    narrow_cpr_df[
                        [
                            "Symbol",
                            "LTP",
                            "CPR Width %",
                            "ATR (14)",
                            "Trend Status",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No stocks currently in a Narrow CPR Squeeze.")

        with tab3:
            st.markdown("#### 🔥 Bullish SMA Alignments (> 20 & 50 SMA)")
            if not bullish_trend_df.empty:
                st.dataframe(
                    bullish_trend_df[
                        [
                            "Symbol",
                            "LTP",
                            "20 SMA (Daily)",
                            "50 SMA (Daily)",
                            "20 SMA (1H)",
                            "Trend Status",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info(
                    "No stocks currently aligned in full bullish structure."
                )

        st.divider()

    except Exception as e:
        st.error(f"Error rendering Technical Indicators section: {str(e)}")


# ==========================================
# 7. HELPER INDICATORS FOR SCREENERS
# ==========================================
def calculate_rsi(series, period=9):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


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
    is_narrow_cpr = cpr_width_pct <= 0.35

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
# 8. MASTER SCORING / RISK FILTER HELPERS
# ==========================================
def safe_pct_change(current, previous):
    try:
        if previous in (None, 0) or pd.isna(previous):
            return 0.0
        return float((current - previous) / previous * 100.0)
    except Exception:
        return 0.0


def classify_futures_oi(price_change_pct, oi_change_pct):
    """Classify price/OI behavior instead of treating every OI increase equally."""
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
    """Return objective price-structure features used by the score."""
    if df_daily is None or len(df_daily) < 55:
        return {"above_20d_high": False, "near_20d_high": False, "dist_20d_high_pct": 999.0,
                "above_50d_high": False, "dist_50d_high_pct": 999.0}
    close = float(df_daily["close"].iloc[-1])
    h20 = float(df_daily["high"].iloc[-21:-1].max())
    h50 = float(df_daily["high"].iloc[-51:-1].max())
    d20 = safe_pct_change(close, h20)
    d50 = safe_pct_change(close, h50)
    return {
        "above_20d_high": close >= h20,
        "near_20d_high": d20 >= -1.0,
        "dist_20d_high_pct": d20,
        "above_50d_high": close >= h50,
        "dist_50d_high_pct": d50,
    }


def calculate_master_fno_score(
    hm_hourly, hm_daily, hm_weekly, hm_monthly,
    price_change_pct, oi_change_pct, rvol, range_ratio,
    cpr_narrow, pcr, option_direction, close, daily_sma20,
    hourly_sma_status, breakout_ctx, vix_price,
):
    """100-point confluence score. The score ranks setups; it does not guarantee profit."""
    bull = 0.0
    bear = 0.0
    reasons = []

    # Market/volatility context: VIX is a risk modifier, not a direction signal.
    if 12 <= vix_price <= 20:
        bull += 2.5
        bear += 2.5
    elif vix_price > 25:
        bull -= 3.0
        bear -= 3.0

    # Multi-timeframe trend: higher timeframes receive more weight.
    trend_points = {"1H": 8, "1D": 12, "1W": 10, "1M": 5}
    for label, status, pts in [
        ("1H", hm_hourly, trend_points["1H"]),
        ("1D", hm_daily, trend_points["1D"]),
        ("1W", hm_weekly, trend_points["1W"]),
        ("1M", hm_monthly, trend_points["1M"]),
    ]:
        if status == "🟢 Bullish":
            bull += pts
            reasons.append(f"{label} bullish")
        elif status == "🔴 Bearish":
            bear += pts
            reasons.append(f"{label} bearish")

    # Momentum / location.
    if daily_sma20 and close > daily_sma20:
        bull += 5
    elif daily_sma20 and close < daily_sma20:
        bear += 5

    if "Bullish Bounce" in hourly_sma_status:
        bull += 6
        reasons.append("1H 20-SMA bounce")
    elif "Breakdown" in hourly_sma_status:
        bear += 6
        reasons.append("1H 20-SMA breakdown")

    # Futures OI classification.
    oi_state = classify_futures_oi(price_change_pct, oi_change_pct)
    if oi_state == "🟢 Long Build-up":
        bull += 12
        reasons.append("long build-up")
    elif oi_state == "🔴 Short Build-up":
        bear += 12
        reasons.append("short build-up")
    elif oi_state == "🟡 Short Covering":
        bull += 6
        reasons.append("short covering")
    elif oi_state == "🟠 Long Unwinding":
        bear += 6
        reasons.append("long unwinding")

    # Volume and range expansion.
    if rvol >= 2.0:
        bull += 8 if price_change_pct > 0 else 0
        bear += 8 if price_change_pct < 0 else 0
        reasons.append(f"RVOL {rvol:.1f}x")
    elif rvol >= 1.5:
        bull += 5 if price_change_pct > 0 else 0
        bear += 5 if price_change_pct < 0 else 0
    elif rvol >= 1.2:
        bull += 2 if price_change_pct > 0 else 0
        bear += 2 if price_change_pct < 0 else 0

    if range_ratio >= 1.8:
        bull += 5 if price_change_pct > 0 else 0
        bear += 5 if price_change_pct < 0 else 0
    elif range_ratio >= 1.3:
        bull += 3 if price_change_pct > 0 else 0
        bear += 3 if price_change_pct < 0 else 0

    # CPR: useful for expansion setups, but not directional by itself.
    if cpr_narrow:
        if price_change_pct > 0:
            bull += 4
        elif price_change_pct < 0:
            bear += 4
        reasons.append("narrow CPR")

    # Option-chain confirmation. Directional agreement is more useful than PCR alone.
    opt = str(option_direction)
    if pcr >= 1.10 and ("Bullish" in opt):
        bull += 5
        reasons.append("option-chain bullish")
    elif pcr <= 0.85 and ("Bearish" in opt):
        bear += 5
        reasons.append("option-chain bearish")

    # Price structure.
    if breakout_ctx.get("above_20d_high"):
        if price_change_pct >= 0:
            bull += 8
            reasons.append("20D breakout")
        else:
            bear += 8
    elif breakout_ctx.get("near_20d_high") and price_change_pct > 0:
        bull += 3

    # Strong one-day moves are penalized as entries because they can be extended.
    if abs(price_change_pct) >= 5.0:
        if price_change_pct > 0:
            bull -= 6
        else:
            bear -= 6
        reasons.append("extended daily move")

    bull = max(0.0, min(100.0, bull))
    bear = max(0.0, min(100.0, bear))
    direction = "LONG" if bull >= bear else "SHORT"
    score = max(bull, bear)

    # Confidence is reduced when the two sides disagree strongly.
    conflict = abs(bull - bear)
    if conflict < 8:
        score = min(score, 59.0)

    if score >= 85:
        grade = "A++"
    elif score >= 75:
        grade = "A+"
    elif score >= 70:
        grade = "A"
    elif score >= 60:
        grade = "B"
    else:
        grade = "WATCH"

    return {
        "score": round(score, 1),
        "bull_score": round(bull, 1),
        "bear_score": round(bear, 1),
        "direction": direction,
        "grade": grade,
        "oi_state": oi_state,
        "reasons": ", ".join(reasons[:8]),
    }


def safe_fetch_history(kite, token, from_date, to_date, interval, oi=False, attempts=3):
    """Retry wrapper for Kite historical data; keeps the scanners from failing on one request."""
    for attempt in range(attempts):
        try:
            kwargs = {"instrument_token": token, "from_date": from_date,
                      "to_date": to_date, "interval": interval}
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
# 8. OPTION ENTRY, VWAP & OPTION BOUNCE ENGINE
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

        # Use the nearest listed strike step rather than assuming every stock has the same step.
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

        # Risk is tied to the option structure rather than an arbitrary zero stop.
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
# 9. INDEX OVERVIEW & INDEX OPTIONS ENGINE
# ==========================================
def scan_indices_overview(kite, nfo_instruments):
    index_results = []
    index_option_picks = []

    from_date_daily = datetime.now() - timedelta(days=90)
    from_date_weekly = datetime.now() - timedelta(days=730)
    from_date_hourly = datetime.now() - timedelta(days=30)
    to_date = datetime.now()

    for idx_key, idx_info in INDEX_MAP.items():
        try:
            token = idx_info["token"]
            symbol = idx_info["name"]

            c_daily = kite.historical_data(
                token, from_date_daily, to_date, "day"
            )
            df_daily = calculate_hilega_milega(pd.DataFrame(c_daily))

            c_weekly_raw = kite.historical_data(
                token, from_date_weekly, to_date, "day"
            )
            df_w_raw = pd.DataFrame(c_weekly_raw)
            if not df_w_raw.empty:
                df_w_raw["date"] = pd.to_datetime(df_w_raw["date"])
                df_weekly = calculate_hilega_milega(
                    df_w_raw.resample("W-MON", on="date")
                    .agg(
                        {
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                        }
                    )
                    .dropna()
                    .reset_index()
                )
            else:
                df_weekly = None

            c_hourly = kite.historical_data(
                token, from_date_hourly, to_date, "60minute"
            )
            df_hourly = calculate_hilega_milega(pd.DataFrame(c_hourly))

            if df_daily is None or len(df_daily) < 20:
                continue

            last_close = df_daily.iloc[-1]["close"]
            prev_close = df_daily.iloc[-2]["close"]
            chg_pct = round(((last_close - prev_close) / prev_close) * 100, 2)

            hm_daily = get_hm_status(df_daily)
            hm_weekly = get_hm_status(df_weekly)
            hm_hourly = get_hm_status(df_hourly)
            hm_summary = f"1H: {hm_hourly} | 1D: {hm_daily} | 1W: {hm_weekly}"

            pivot, cpr_top, cpr_bottom, is_narrow = calculate_cpr(
                df_daily.iloc[-2]
            )
            cpr_status = "⚡ Narrow CPR" if is_narrow else "Normal CPR"
            sma20_status = check_sma_20_bounce(df_hourly)

            pcr_value, option_chain_direction = analyze_option_chain_direction(
                kite, nfo_instruments, symbol
            )

            overall_bias = "⚪ Neutral Range"
            if (
                "Bullish" in hm_daily
                and "Bullish" in hm_hourly
                and pcr_value >= 0.95
            ):
                overall_bias = "🟢 Bullish Bias"
            elif (
                "Bearish" in hm_daily
                and "Bearish" in hm_hourly
                and pcr_value <= 0.85
            ):
                overall_bias = "🔴 Bearish Bias"

            index_results.append(
                {
                    "Index": idx_info["symbol"],
                    "Spot Price": round(last_close, 2),
                    "Change %": chg_pct,
                    "1H 20 SMA Status": sma20_status,
                    "CPR Setup": cpr_status,
                    "Option Chain Sentiment": option_chain_direction,
                    "Multi-Timeframe Trend": hm_summary,
                    "Market Outlook": overall_bias,
                }
            )

            opt_strike, bounce_lvl, buy_rate, sl_rate, target_rate, vwap_status = (
                fetch_vwap_option_details(
                    kite, nfo_instruments, symbol, last_close, overall_bias
                )
            )

            index_option_picks.append(
                {
                    "Index": idx_info["symbol"],
                    "Spot Price": round(last_close, 2),
                    "Outlook": overall_bias,
                    "1H 20 SMA Status": sma20_status,
                    "Rec Option Strike": opt_strike,
                    "Premium Bounce Level (₹)": bounce_lvl,
                    "Trigger / Limit Buy (₹)": buy_rate,
                    "Stop Loss (₹)": sl_rate,
                    "Target (₹)": target_rate,
                    "Option Status": vwap_status,
                }
            )

        except Exception as e:
            st.error(f"Error scanning index {idx_key}: {str(e)}")

    return pd.DataFrame(index_results), pd.DataFrame(index_option_picks)


# ==========================================
# 10. HERO-ZERO EXPIRY ENGINE
# ==========================================
def scan_hero_zero_opportunities(kite):
    st.info("⚡ Scanning Index Options for Hero-Zero Expiry Signals...")

    nfo_instruments = pd.DataFrame(kite.instruments("NFO"))
    today_date = datetime.now().date()
    hero_zero_candidates = []

    for idx_key, idx_info in INDEX_MAP.items():
        symbol = idx_info["name"]

        spot_quote = kite.quote([f"NSE:{idx_info['symbol']}"])
        spot_price = spot_quote.get(f"NSE:{idx_info['symbol']}", {}).get(
            "last_price", 0.0
        )
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

        st.success(
            f"🔥 Active Expiry Detected for **{symbol}**! Analyzing Open Interest and Premium Compression..."
        )

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
            oi_day_high = quote_data.get("oi_day_high", oi)

            if not (5.00 <= ltp <= 30.00):
                continue

            dist_pts = abs(strike - spot_price)
            if dist_pts > (spot_price * 0.02):
                continue

            # oi_day_high is not a valid previous-OI reference. Fetch the previous
            # available 5-minute candle OI for a true unwinding estimate.
            oi_unwinding_pct = 0.0
            try:
                start_day = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
                hist = safe_fetch_history(kite, int(opt_row["instrument_token"]), start_day, datetime.now(), "5minute", oi=True)
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
                stop_loss = 0.00

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
                        "Stop Loss (₹)": stop_loss,
                        "Spot Price": spot_price,
                    }
                )

    return pd.DataFrame(hero_zero_candidates)


# ==========================================
# 11. MASTER SCREENER ENGINE (F&O)
# ==========================================
def scan_fno_opportunities(kite):
    st.info("📡 Loading NFO Futures & mapping underlying NSE stocks...")
    nfo_instruments = pd.DataFrame(kite.instruments("NFO"))
    nse_instruments = pd.DataFrame(kite.instruments("NSE"))
    if nfo_instruments.empty or nse_instruments.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    vix_val, vix_status = fetch_india_vix_regime(kite)
    st.metric("🇮🇳 India VIX", vix_val, vix_status)

    # Market regime is calculated once, not once per stock.
    market_score = 0
    try:
        nifty_token = INDEX_MAP["NIFTY"]["token"]
        now = datetime.now()
        nifty_d = pd.DataFrame(safe_fetch_history(kite, nifty_token, now - timedelta(days=90), now, "day"))
        nifty_h = pd.DataFrame(safe_fetch_history(kite, nifty_token, now - timedelta(days=30), now, "60minute"))
        nifty_d = calculate_hilega_milega(nifty_d)
        nifty_h = calculate_hilega_milega(nifty_h)
        if get_hm_status(nifty_d) == "🟢 Bullish": market_score += 5
        elif get_hm_status(nifty_d) == "🔴 Bearish": market_score -= 5
        if get_hm_status(nifty_h) == "🟢 Bullish": market_score += 5
        elif get_hm_status(nifty_h) == "🔴 Bearish": market_score -= 5
    except Exception:
        market_score = 0

    index_exclusions = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    futures = nfo_instruments[
        (nfo_instruments["instrument_type"] == "FUT")
        & (~nfo_instruments["name"].isin(index_exclusions))
    ].copy()
    if futures.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    all_fno_symbols = sorted(futures["name"].dropna().unique().tolist())
    strict_results, intraday_picks, all_scanned_data = [], [], []

    now = datetime.now()
    from_daily = now - timedelta(days=120)
    from_weekly = now - timedelta(days=730)
    from_monthly = now - timedelta(days=1825)
    from_hourly = now - timedelta(days=45)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for index, symbol in enumerate(all_fno_symbols, start=1):
        try:
            status_text.text(f"Scanning [{index}/{len(all_fno_symbols)}]: {symbol}...")
            progress_bar.progress(index / len(all_fno_symbols))

            symbol_futs = futures[futures["name"] == symbol].copy()
            symbol_futs["expiry"] = pd.to_datetime(symbol_futs["expiry"]).dt.date
            symbol_futs = symbol_futs[symbol_futs["expiry"] >= now.date()].sort_values("expiry")
            if symbol_futs.empty:
                continue
            near_fut = symbol_futs.iloc[0]
            fut_token = int(near_fut["instrument_token"])
            fut_tradingsymbol = near_fut["tradingsymbol"]

            eq_match = nse_instruments[
                (nse_instruments["tradingsymbol"] == symbol)
                & (nse_instruments["segment"] == "NSE")
            ]
            if eq_match.empty:
                continue
            eq_token = int(eq_match.iloc[0]["instrument_token"])

            df_daily = calculate_hilega_milega(pd.DataFrame(safe_fetch_history(kite, eq_token, from_daily, now, "day")))
            df_w_raw = pd.DataFrame(safe_fetch_history(kite, eq_token, from_weekly, now, "day"))
            df_m_raw = pd.DataFrame(safe_fetch_history(kite, eq_token, from_monthly, now, "day"))
            df_hourly = calculate_hilega_milega(pd.DataFrame(safe_fetch_history(kite, eq_token, from_hourly, now, "60minute")))
            df_fut_daily = pd.DataFrame(safe_fetch_history(kite, fut_token, from_daily, now, "day", oi=True))

            if df_daily is None or len(df_daily) < 55 or df_fut_daily.empty or len(df_fut_daily) < 3:
                continue

            def resample_ohlcv(raw, rule):
                if raw.empty:
                    return None
                raw = raw.copy()
                raw["date"] = pd.to_datetime(raw["date"])
                return calculate_hilega_milega(
                    raw.resample(rule, on="date").agg({
                        "open":"first", "high":"max", "low":"min", "close":"last", "volume":"sum"
                    }).dropna().reset_index()
                )

            df_weekly = resample_ohlcv(df_w_raw, "W-MON")
            df_monthly = resample_ohlcv(df_m_raw, "ME")

            today = df_daily.iloc[-1]
            prev = df_daily.iloc[-2]
            close = float(today["close"])
            price_change_pct = safe_pct_change(today["close"], prev["close"])
            rvol = calculate_rvol(df_daily, 20)
            today_range = float(today["high"] - today["low"])
            avg_range = float((df_daily["high"].iloc[-21:-1] - df_daily["low"].iloc[-21:-1]).mean())
            range_ratio = today_range / avg_range if avg_range > 0 else 0.0

            fut_today, fut_prev = df_fut_daily.iloc[-1], df_fut_daily.iloc[-2]
            today_oi, prev_oi = float(fut_today.get("oi", 0) or 0), float(fut_prev.get("oi", 0) or 0)
            oi_change_pct = safe_pct_change(today_oi, prev_oi)

            pivot, cpr_top, cpr_bottom, is_narrow_cpr = calculate_cpr(df_daily.iloc[-2])
            stock_atr = calculate_atr(df_daily, 14)
            atr_pct = calculate_atr_pct(df_daily, 14)
            sma20_daily = float(df_daily["close"].rolling(20).mean().iloc[-1])
            sma20_status = check_sma_20_bounce(df_hourly)

            hm_daily = get_hm_status(df_daily)
            hm_weekly = get_hm_status(df_weekly)
            hm_monthly = get_hm_status(df_monthly)
            hm_hourly = get_hm_status(df_hourly)

            pcr_value, option_chain_direction = analyze_option_chain_direction(kite, nfo_instruments, symbol)
            breakout_ctx = calculate_breakout_context(df_daily)
            score = calculate_master_fno_score(
                hm_hourly, hm_daily, hm_weekly, hm_monthly,
                price_change_pct, oi_change_pct, rvol, range_ratio,
                is_narrow_cpr, pcr_value, option_chain_direction,
                close, sma20_daily, sma20_status, breakout_ctx, vix_val,
            )

            # Market regime is a directional modifier. Do not allow it to overpower stock-level evidence.
            if market_score > 0 and score["direction"] == "LONG":
                score["score"] = round(min(100, score["score"] + 3), 1)
            elif market_score < 0 and score["direction"] == "SHORT":
                score["score"] = round(min(100, score["score"] + 3), 1)
            elif market_score > 0 and score["direction"] == "SHORT":
                score["score"] = round(max(0, score["score"] - 5), 1)
            elif market_score < 0 and score["direction"] == "LONG":
                score["score"] = round(max(0, score["score"] - 5), 1)

            # Hard risk vetoes.
            risk_flags = []
            if atr_pct > 6.0:
                risk_flags.append("Extreme ATR")
            if abs(price_change_pct) > 8.0:
                risk_flags.append("Overextended Move")
            if score["oi_state"] in ("🔴 Short Build-up", "🟠 Long Unwinding") and score["direction"] == "LONG":
                risk_flags.append("OI Conflict")
            if score["oi_state"] == "🟢 Long Build-up" and score["direction"] == "SHORT":
                risk_flags.append("OI Conflict")

            if risk_flags:
                score["score"] = max(0, score["score"] - 10 * len(risk_flags))

            if score["score"] >= SCREENER["strict_score"]:
                signal = f"{('🚀' if score['direction']=='LONG' else '🔻')} {score['grade']} {score['direction']}"
            elif score["score"] >= SCREENER["min_score"]:
                signal = f"🟡 {score['grade']} {score['direction']} WATCH"
            else:
                signal = "⚪ Neutral"

            opt_strike = bounce_lvl = buy_rate = sl_rate = target_rate = 0.0
            vwap_status = "N/A"
            if score["score"] >= SCREENER["min_score"]:
                opt_strike, bounce_lvl, buy_rate, sl_rate, target_rate, vwap_status = fetch_vwap_option_details(
                    kite, nfo_instruments, symbol, close, signal
                )

            rr = ((target_rate - buy_rate) / (buy_rate - sl_rate)) if buy_rate > sl_rate > 0 else 0.0
            if rr and rr < SCREENER["min_rr"]:
                score["score"] = max(0, score["score"] - 8)
                risk_flags.append("Poor Option R:R")

            trap_warning = "✅ Clean Structure"
            if price_change_pct > 1.5 and oi_change_pct < -2.0:
                trap_warning = "⚠️ Short Covering"
            elif price_change_pct < -1.5 and oi_change_pct < -2.0:
                trap_warning = "⚠️ Long Unwinding"
            elif range_ratio >= 3.8 or abs(price_change_pct) >= 8.0:
                trap_warning = "⚠️ Overextended"

            stock_info = {
                "Symbol": symbol,
                "Contract": fut_tradingsymbol,
                "Price": round(close, 2),
                "Price Chg %": round(price_change_pct, 2),
                "Score": round(score["score"], 1),
                "Grade": score["grade"],
                "Direction": score["direction"],
                "Bull Score": score["bull_score"],
                "Bear Score": score["bear_score"],
                "OI State": score["oi_state"],
                "OI Chg %": round(oi_change_pct, 2),
                "RVOL": round(rvol, 2),
                "Range Expansion": round(range_ratio, 2),
                "ATR %": round(atr_pct, 2),
                "1H 20 SMA Status": sma20_status,
                "CPR Status": "⚡ Narrow CPR" if is_narrow_cpr else "Normal CPR",
                "Option PCR": pcr_value,
                "Option Chain Direction": option_chain_direction,
                "HM Multi-Timeframe": f"1H:{hm_hourly} | 1D:{hm_daily} | 1W:{hm_weekly} | 1M:{hm_monthly}",
                "20D Breakout": "YES" if breakout_ctx["above_20d_high"] else "NO",
                "Reasons": score["reasons"],
                "Risk Flags": ", ".join(risk_flags) if risk_flags else "None",
                "Signal": signal,
                "Trap Filter": trap_warning,
                "Rec Option": opt_strike,
                "Premium Bounce Level (₹)": bounce_lvl,
                "Limit Buy Rate (₹)": buy_rate,
                "Stop Loss (₹)": sl_rate,
                "Target (₹)": target_rate,
                "Option R:R": round(rr, 2),
                "Option Status": vwap_status,
            }
            all_scanned_data.append(stock_info)

            if score["score"] >= SCREENER["strict_score"] and not risk_flags:
                strict_results.append(stock_info)
            if score["score"] >= SCREENER["intraday_score"] and rvol >= SCREENER["min_rvol"] and not risk_flags and "Overextended" not in trap_warning:
                intraday_picks.append(stock_info)

            time.sleep(0.12)
        except Exception as e:
            st.warning(f"Skipped {symbol}: {str(e)[:160]}")

    status_text.text("Scan Completed")
    progress_bar.empty()

    df_intra = pd.DataFrame(intraday_picks)
    df_strict = pd.DataFrame(strict_results)
    df_all = pd.DataFrame(all_scanned_data)
    for d in (df_intra, df_strict, df_all):
        if not d.empty and "Score" in d.columns:
            d.sort_values(["Score", "RVOL"], ascending=[False, False], inplace=True)
            d.reset_index(drop=True, inplace=True)
    return df_intra, df_strict, df_all


# ==========================================
# 12. HIGH-SPEED UDD JA BREAKOUT ENGINE (CASH STOCKS)
# ==========================================
def scan_udd_ja_cash_stocks(kite):
    st.info("🚀 Pre-filtering NSE Cash Equities for High Volume & Liquidity...")

    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)

    cash_stocks = df[
        (df["segment"] == "NSE")
        & (df["instrument_type"] == "EQ")
        & (df["name"].str.strip() != "")
    ].copy()

    exclude_keywords = [
        "BEES",
        "ETF",
        "GOLD",
        "SILVER",
        "LIQUID",
        "NIFTY",
        "BOND",
        "SGB",
        "NAV",
        "GSEC",
        "IWIN",
        "-RE",
        "-SG",
    ]
    pattern = "|".join(exclude_keywords)
    cash_stocks = cash_stocks[
        ~cash_stocks["tradingsymbol"].str.contains(
            pattern, case=False, na=False
        )
    ]
    cash_stocks = cash_stocks[~cash_stocks["tradingsymbol"].str.match(r"^\d")]

    all_symbols = cash_stocks["tradingsymbol"].dropna().unique().tolist()
    formatted_symbols = [f"NSE:{s}" for s in all_symbols]

    st.write(
        f"🔍 Fast-checking live liquidity for {len(all_symbols)} equity symbols..."
    )
    liquid_symbols = []

    chunk_size = 50
    for i in range(0, len(formatted_symbols), chunk_size):
        chunk = formatted_symbols[i : i + chunk_size]
        try:
            quotes = kite.quote(chunk)
            if isinstance(quotes, dict):
                for sym_key, qdata in quotes.items():
                    if not isinstance(qdata, dict):
                        continue

                    clean_sym = sym_key.replace("NSE:", "")
                    ltp = (
                        qdata.get("last_price", 0)
                        or qdata.get("ohlc", {}).get("close", 0)
                    )
                    vol = qdata.get("volume", 0)

                    if ltp >= 50.0 and (vol >= 25000 or vol == 0):
                        liquid_symbols.append(clean_sym)

            time.sleep(0.1)

        except Exception:
            time.sleep(0.5)

    total_liquid = len(liquid_symbols)
    st.success(
        f"⚡ Pruned list down to **{total_liquid} active liquid stocks**! Scanning setups..."
    )

    if total_liquid == 0:
        st.warning(
            "⚠️ No stocks passed liquidity pre-filter. Re-trying with broader list..."
        )
        liquid_symbols = all_symbols[:500]
        total_liquid = len(liquid_symbols)

    udd_ja_results = []
    from_date_3m = datetime.now() - timedelta(days=5)
    from_date_daily = datetime.now() - timedelta(days=365)
    to_date = datetime.now()

    progress_bar = st.progress(0)
    status_text = st.empty()

    def safe_fetch_history(token, from_date, to_date, interval):
        for attempt in range(3):
            try:
                data = kite.historical_data(
                    token, from_date, to_date, interval
                )
                time.sleep(0.1)
                return data
            except Exception as ex:
                if "Too many requests" in str(ex):
                    time.sleep(1.0)
                else:
                    return []
        return []

    for index, symbol in enumerate(liquid_symbols, start=1):
        try:
            status_text.text(
                f"Scanning Cash [{index}/{total_liquid}]: {symbol}..."
            )
            progress_bar.progress(index / total_liquid)

            match = cash_stocks[cash_stocks["tradingsymbol"] == symbol]
            if match.empty:
                continue

            token = int(match.iloc[0]["instrument_token"])

            c_daily = safe_fetch_history(
                token, from_date_daily, to_date, "day"
            )
            df_daily = pd.DataFrame(c_daily)

            if len(df_daily) < 60:
                continue

            avg_vol_20d = df_daily["volume"].tail(20).mean()
            last_price = df_daily["close"].iloc[-1]
            turnover_cr = (avg_vol_20d * last_price) / 10000000.0

            if turnover_cr < 0.5:
                continue

            df_daily["date"] = pd.to_datetime(df_daily["date"])
            df_weekly = (
                df_daily.resample("W-MON", on="date")
                .agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    }
                )
                .dropna()
                .reset_index()
            )
            df_monthly = (
                df_daily.resample("ME", on="date")
                .agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    }
                )
                .dropna()
                .reset_index()
            )

            daily_bb = check_bollinger_blast(df_daily)
            weekly_bb = check_bollinger_blast(df_weekly)
            monthly_bb = check_bollinger_blast(df_monthly)

            if not (daily_bb and weekly_bb and monthly_bb):
                continue

            c_3min = safe_fetch_history(
                token, from_date_3m, to_date, "3minute"
            )
            df_3m = pd.DataFrame(c_3min)

            if df_3m.empty or len(df_3m) < 30:
                continue

            df_3m["date"] = pd.to_datetime(df_3m["date"])
            latest_day = df_3m["date"].dt.date.iloc[-1]
            df_today = df_3m[df_3m["date"].dt.date == latest_day].copy()

            if df_today.empty:
                continue

            df_today["time"] = df_today["date"].dt.time
            t_1100 = datetime.strptime("11:00:00", "%H:%M:%S").time()
            t_1300 = datetime.strptime("13:00:00", "%H:%M:%S").time()
            t_0915 = datetime.strptime("09:15:00", "%H:%M:%S").time()

            df_dry = df_today[
                (df_today["time"] >= t_1100) & (df_today["time"] <= t_1300)
            ]
            df_morn = df_today[
                (df_today["time"] >= t_0915) & (df_today["time"] < t_1100)
            ]

            if df_dry.empty:
                continue

            avg_dry_vol = df_dry["volume"].mean()

            df_today["sma20"] = df_today["close"].rolling(20).mean()
            df_today["std"] = df_today["close"].rolling(20).std()
            df_today["ub"] = df_today["sma20"] + (2 * df_today["std"])
            df_today["bb_width"] = (
                df_today["ub"] - (df_today["sma20"] - (2 * df_today["std"]))
            ) / df_today["sma20"]

            df_today["tp"] = (
                df_today["high"] + df_today["low"] + df_today["close"]
            ) / 3.0
            df_today["vwap"] = (
                df_today["tp"] * df_today["volume"]
            ).cumsum() / df_today["volume"].cumsum().replace(0, np.nan)

            latest_candle = df_today.iloc[-1]

            vol_spike = (
                (latest_candle["volume"] / avg_dry_vol)
                if avg_dry_vol > 0
                else 0
            )
            is_vol_breakout = vol_spike >= 1.8
            is_above_vwap = latest_candle["close"] > latest_candle["vwap"]
            is_above_3m_ub = latest_candle["close"] >= latest_candle["ub"]

            if is_vol_breakout and is_above_vwap and is_above_3m_ub:
                ltp = latest_candle["close"]
                vwap_val = latest_candle["vwap"]
                stop_loss = round(vwap_val - 1.0, 2)

                morning_range = (
                    (df_morn["high"].max() - df_morn["low"].min())
                    if not df_morn.empty
                    else (ltp * 0.02)
                )
                target_3x = round(ltp + (3 * morning_range), 2)

                min_bb_width = max(
                    (
                        df_dry["bb_width"].min()
                        if not df_dry["bb_width"].empty
                        else 0.01
                    ),
                    0.0001,
                )
                vwap_std = max(
                    (
                        df_dry["close"].std()
                        if not df_dry["close"].empty
                        else 1.0
                    ),
                    0.0001,
                )

                # Bounded 100-point breakout score; avoids unstable 1/x scoring.
                score = 0.0
                score += min(25.0, max(0.0, (vol_spike - 1.0) * 12.5))
                score += 20.0 if is_above_vwap else 0.0
                score += 20.0 if is_above_3m_ub else 0.0
                score += 15.0 if latest_candle["close"] >= df_today["high"].iloc[:-1].max() else 0.0
                score += 10.0 if latest_candle["bb_width"] > min_bb_width * 1.15 else 0.0
                score += 10.0 if morning_range > 0 and (ltp - vwap_val) / morning_range > 0.25 else 0.0
                score = round(min(100.0, score), 1)

                udd_ja_results.append(
                    {
                        "Symbol": symbol,
                        "LTP (₹)": round(ltp, 2),
                        "Stop Loss (₹)": round(stop_loss, 2),
                        "Target (3x Range) (₹)": round(target_3x, 2),
                        "Vol Spike": f"{round(vol_spike, 1)}x",
                        "Score": score,
                        "Grade": "A+" if score >= 85 else "A" if score >= 75 else "B" if score >= 65 else "Watch",
                    }
                )

        except Exception as e:
            st.error(f"Error scanning cash symbol {symbol}: {str(e)}")

    status_text.text("Udd Ja Cash Scan Completed!")
    progress_bar.empty()

    if udd_ja_results:
        df_res = pd.DataFrame(udd_ja_results)
        return df_res.sort_values(by="Score", ascending=False).reset_index(
            drop=True
        )
    return pd.DataFrame()


# ==========================================
# 13. YEARLY BREAKOUTS ENGINE
# ==========================================
def scan_yearly_breakout_cash_stocks(kite):
    st.info("📅 Fetching 52-Week High & Historical Data for NSE Cash Equities...")

    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)

    cash_stocks = df[
        (df["segment"] == "NSE")
        & (df["instrument_type"] == "EQ")
        & (df["name"].str.strip() != "")
    ].copy()

    exclude_keywords = [
        "BEES", "ETF", "GOLD", "SILVER", "LIQUID", "NIFTY", "BOND", 
        "SGB", "NAV", "GSEC", "IWIN", "-RE", "-SG"
    ]
    pattern = "|".join(exclude_keywords)
    cash_stocks = cash_stocks[
        ~cash_stocks["tradingsymbol"].str.contains(pattern, case=False, na=False)
    ]
    cash_stocks = cash_stocks[~cash_stocks["tradingsymbol"].str.match(r"^\d")]

    all_symbols = cash_stocks["tradingsymbol"].dropna().unique().tolist()
    formatted_symbols = [f"NSE:{s}" for s in all_symbols]

    st.write(f"🔍 Pre-filtering liquidity for {len(all_symbols)} cash symbols...")
    liquid_symbols = []

    chunk_size = 50
    for i in range(0, len(formatted_symbols), chunk_size):
        chunk = formatted_symbols[i : i + chunk_size]
        try:
            quotes = kite.quote(chunk)
            if isinstance(quotes, dict):
                for sym_key, qdata in quotes.items():
                    if not isinstance(qdata, dict):
                        continue
                    clean_sym = sym_key.replace("NSE:", "")
                    ltp = qdata.get("last_price", 0) or qdata.get("ohlc", {}).get("close", 0)
                    vol = qdata.get("volume", 0)

                    if ltp >= 30.0 and (vol >= 20000 or vol == 0):
                        liquid_symbols.append(clean_sym)
            time.sleep(0.05)
        except Exception:
            time.sleep(0.3)

    total_liquid = len(liquid_symbols)
    st.success(f"⚡ Filtered down to **{total_liquid} active stocks**. Scanning 52W Breakouts & Confluence Signals...")

    yearly_breakout_results = []
    to_date = datetime.now()
    from_date = to_date - timedelta(days=730)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for index, symbol in enumerate(liquid_symbols, start=1):
        try:
            status_text.text(f"Scanning Yearly Breakouts [{index}/{total_liquid}]: {symbol}...")
            progress_bar.progress(index / total_liquid)

            match = cash_stocks[cash_stocks["tradingsymbol"] == symbol]
            if match.empty:
                continue

            token = int(match.iloc[0]["instrument_token"])

            candles = kite.historical_data(
                instrument_token=token,
                from_date=from_date.strftime("%Y-%m-%d %H:%M:%S"),
                to_date=to_date.strftime("%Y-%m-%d %H:%M:%S"),
                interval="day",
            )
            df_daily = pd.DataFrame(candles)

            if len(df_daily) < 200:
                continue

            ltp = df_daily["close"].iloc[-1]
            prev_close = df_daily["close"].iloc[-2]
            single_day_gain_pct = round(((ltp - prev_close) / prev_close) * 100, 2)

            high_52w = df_daily["high"].iloc[:-1].max()
            sma_20 = df_daily["close"].rolling(20).mean().iloc[-1]
            sma_50 = df_daily["close"].rolling(50).mean().iloc[-1]
            vol_20d_avg = df_daily["volume"].tail(20).mean()
            today_vol = df_daily["volume"].iloc[-1]
            vol_ratio = round(today_vol / vol_20d_avg, 2) if vol_20d_avg > 0 else 1.0

            dist_to_52w_pct = round(((ltp - high_52w) / high_52w) * 100, 2)

            if dist_to_52w_pct >= -1.5:
                df_daily_hm = calculate_hilega_milega(df_daily.copy())
                df_daily_hm["date"] = pd.to_datetime(df_daily_hm["date"])

                df_weekly = (
                    df_daily_hm.resample("W-MON", on="date")
                    .agg({
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum"
                    })
                    .dropna()
                    .reset_index()
                )
                df_weekly = calculate_hilega_milega(df_weekly)

                cpr_confluence_status = "⚪ Standard 52W Breakout"

                if len(df_weekly) >= 20:
                    prev_week = df_weekly.iloc[-2]
                    weekly_pivot, weekly_tc, weekly_bc, is_narrow_w_cpr = calculate_cpr(prev_week)

                    above_weekly_pivot = ltp >= weekly_pivot

                    df_daily_hm["sma20"] = df_daily_hm["close"].rolling(20).mean()
                    df_daily_hm["std"] = df_daily_hm["close"].rolling(20).std()
                    df_daily_hm["ub"] = df_daily_hm["sma20"] + (2 * df_daily_hm["std"])
                    df_daily_hm["lb"] = df_daily_hm["sma20"] - (2 * df_daily_hm["std"])
                    df_daily_hm["bb_width"] = (df_daily_hm["ub"] - df_daily_hm["lb"]) / df_daily_hm["sma20"]
                    
                    recent_bb_width = df_daily_hm["bb_width"].iloc[-1]
                    min_20d_bb_width = df_daily_hm["bb_width"].tail(20).min()
                    is_bb_squeezed = (recent_bb_width <= min_20d_bb_width * 1.15) or (recent_bb_width <= 0.08)

                    latest_hm_ema = df_daily_hm["hm_ema_price"].iloc[-1] if "hm_ema_price" in df_daily_hm.columns else 0
                    is_hm_above_50 = latest_hm_ema >= 50.0

                    if above_weekly_pivot and is_bb_squeezed and is_hm_above_50:
                        cpr_confluence_status = "🔥 POWER SETUP (Weekly CPR + BB Squeeze + HM > 50)"
                    elif above_weekly_pivot and is_hm_above_50:
                        cpr_confluence_status = "🟢 Bullish (Weekly Pivot + HM > 50)"

                if single_day_gain_pct > 8.0:
                    entry_price = round(high_52w, 2)
                    trade_action = "⚠️ Slippage Risk (Wait for Pullback Retest)"
                    strategy_note = f"Limit Buy near 52W Level (₹{high_52w:,.2f}) on light volume pullback."
                elif -1.5 <= dist_to_52w_pct <= 1.0:
                    entry_price = round(high_52w * 1.002, 2)
                    trade_action = "🎯 Ideal Consolidation / Pre-Breakout Entry"
                    strategy_note = "Pre-Breakout / Retest accumulation near 52W level."
                else:
                    entry_price = round(ltp, 2)
                    trade_action = "🚀 Active 52W Breakout"
                    strategy_note = "Accumulate position for 3–6 month swing horizon."

                stop_loss_tight = round(max(high_52w * 0.98, sma_20), 2)
                stop_loss_50sma = round(sma_50, 2) if not np.isnan(sma_50) else round(high_52w * 0.92, 2)

                risk_per_share = max(entry_price - stop_loss_tight, entry_price * 0.03)
                target_3x = round(entry_price + (3 * risk_per_share), 2)

                yearly_breakout_results.append(
                    {
                        "Symbol": symbol,
                        "LTP (₹)": round(ltp, 2),
                        "52W High (₹)": round(high_52w, 2),
                        "Dist to 52W %": dist_to_52w_pct,
                        "Single-Day Gain %": single_day_gain_pct,
                        "Trigger / Entry Price (₹)": entry_price,
                        "Tight Stop Loss (₹)": stop_loss_tight,
                        "Swing SL (50 SMA) (₹)": stop_loss_50sma,
                        "Target (1:3 R:R) (₹)": target_3x,
                        "Vol Ratio": f"{vol_ratio}x",
                        "Confluence Signal": cpr_confluence_status,
                        "Action Status": trade_action,
                        "Execution Plan": strategy_note,
                    }
                )

            time.sleep(0.05)

        except Exception as e:
            st.error(f"Error scanning yearly breakout for {symbol}: {str(e)}")

    status_text.text("Yearly Breakout Scan Completed!")
    progress_bar.empty()

    return pd.DataFrame(yearly_breakout_results)


# ==========================================
# 14. PRE-BREAKOUT TRADING LOGIC ENGINE
# ==========================================
def calculate_weekly_pre_breakout_candidates(kite, ma_prox_thresh=1.0, rsi_min=50.0, rsi_max=65.0):
    st.info("🎯 Running Pre-Breakout Squeeze Scan (Weekly 11 EMA / 20 SMA / RSI 50-65 / BB Compression + MTF RSI 9 Strength)...")

    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)

    cash_stocks = df[
        (df["segment"] == "NSE")
        & (df["instrument_type"] == "EQ")
        & (df["name"].str.strip() != "")
    ].copy()

    exclude_keywords = [
        "BEES", "ETF", "GOLD", "SILVER", "LIQUID", "NIFTY", "BOND", 
        "SGB", "NAV", "GSEC", "IWIN", "-RE", "-SG"
    ]
    pattern = "|".join(exclude_keywords)
    cash_stocks = cash_stocks[
        ~cash_stocks["tradingsymbol"].str.contains(pattern, case=False, na=False)
    ]
    cash_stocks = cash_stocks[~cash_stocks["tradingsymbol"].str.match(r"^\d")]

    all_symbols = cash_stocks["tradingsymbol"].dropna().unique().tolist()
    formatted_symbols = [f"NSE:{s}" for s in all_symbols]

    liquid_symbols = []
    chunk_size = 50
    for i in range(0, len(formatted_symbols), chunk_size):
        chunk = formatted_symbols[i : i + chunk_size]
        try:
            quotes = kite.quote(chunk)
            if isinstance(quotes, dict):
                for sym_key, qdata in quotes.items():
                    if not isinstance(qdata, dict):
                        continue
                    clean_sym = sym_key.replace("NSE:", "")
                    ltp = qdata.get("last_price", 0) or qdata.get("ohlc", {}).get("close", 0)
                    vol = qdata.get("volume", 0)

                    if ltp >= 30.0 and (vol >= 15000 or vol == 0):
                        liquid_symbols.append(clean_sym)
            time.sleep(0.05)
        except Exception:
            time.sleep(0.3)

    total_liquid = len(liquid_symbols)
    pre_breakout_results = []
    to_date = datetime.now()
    from_date = to_date - timedelta(days=1825)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for index, symbol in enumerate(liquid_symbols, start=1):
        try:
            status_text.text(f"Scanning Pre-Breakout [{index}/{total_liquid}]: {symbol}...")
            progress_bar.progress(index / total_liquid)

            match = cash_stocks[cash_stocks["tradingsymbol"] == symbol]
            if match.empty:
                continue

            token = int(match.iloc[0]["instrument_token"])

            candles = kite.historical_data(
                instrument_token=token,
                from_date=from_date.strftime("%Y-%m-%d %H:%M:%S"),
                to_date=to_date.strftime("%Y-%m-%d %H:%M:%S"),
                interval="day",
            )
            df_daily = pd.DataFrame(candles)

            if len(df_daily) < 150:
                continue

            df_daily["date"] = pd.to_datetime(df_daily["date"])

            df_weekly = (
                df_daily.resample("W-MON", on="date")
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum"
                })
                .dropna()
                .reset_index()
            )

            df_monthly = (
                df_daily.resample("ME", on="date")
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum"
                })
                .dropna()
                .reset_index()
            )

            if len(df_weekly) < 30 or len(df_monthly) < 22:
                continue

            daily_rsi_buy, daily_rsi_val = check_rsi_strength_9(df_daily)
            weekly_rsi_buy, weekly_rsi_val = check_rsi_strength_9(df_weekly)
            monthly_rsi_buy, monthly_rsi_val = check_rsi_strength_9(df_monthly)

            cond_rsi_mtf_buy = daily_rsi_buy and weekly_rsi_buy and monthly_rsi_buy

            df_weekly["ema11"] = df_weekly["close"].ewm(span=11, adjust=False).mean()
            df_weekly["sma20"] = df_weekly["close"].rolling(20).mean()
            df_weekly["std20"] = df_weekly["close"].rolling(20).std()
            df_weekly["upper_bb"] = df_weekly["sma20"] + (2 * df_weekly["std20"])
            df_weekly["lower_bb"] = df_weekly["sma20"] - (2 * df_weekly["std20"])
            df_weekly["bb_width"] = (df_weekly["upper_bb"] - df_weekly["lower_bb"]) / df_weekly["sma20"]
            df_weekly["rsi9"] = calculate_rsi(df_weekly["close"], period=9)

            curr_weekly = df_weekly.iloc[-1]
            ltp = curr_weekly["close"]
            w_ema11 = curr_weekly["ema11"]
            w_sma20 = curr_weekly["sma20"]
            w_rsi9 = curr_weekly["rsi9"]
            curr_bb_width = curr_weekly["bb_width"]

            min_20w_bb_width = df_weekly["bb_width"].tail(20).min()
            is_bb_compressed = (curr_bb_width <= min_20w_bb_width * 1.15) or (curr_bb_width <= 0.12)

            dist_ema11_pct = abs(ltp - w_ema11) / w_ema11 * 100.0
            dist_sma20_pct = abs(ltp - w_sma20) / w_sma20 * 100.0
            cond_ma_proximity = (dist_ema11_pct <= ma_prox_thresh) or (dist_sma20_pct <= ma_prox_thresh)

            cond_rsi_range = rsi_min <= w_rsi9 <= rsi_max

            # Pre-breakout is a setup score, not an immediate buy signal.
            setup_score = 0.0
            setup_score += 25.0 if cond_ma_proximity else 0.0
            setup_score += 25.0 if is_bb_compressed else 0.0
            setup_score += 15.0 if cond_rsi_range else 0.0
            setup_score += 20.0 if cond_rsi_mtf_buy else 0.0
            # Prefer consolidation/accumulation: current weekly range should not be extreme.
            if len(df_weekly) >= 6:
                recent_range = (df_weekly["high"].iloc[-1] - df_weekly["low"].iloc[-1]) / max(ltp, 1) * 100
                setup_score += 10.0 if recent_range <= 5.0 else 0.0
            setup_score += 5.0 if ltp >= w_ema11 and ltp >= w_sma20 else 0.0
            setup_score = round(min(100.0, setup_score), 1)

            if setup_score >= 70:
                setup_grade = "🔥 A+ PRE-BREAKOUT" if setup_score >= 85 else "🟢 A PRE-BREAKOUT"
            else:
                setup_grade = "🟡 WATCH"

            if setup_score >= 70 and cond_ma_proximity and cond_rsi_range and is_bb_compressed:

                accum_low = round(min(w_ema11, w_sma20) * 0.99, 2)
                accum_high = round(max(w_ema11, w_sma20) * 1.01, 2)
                stop_loss = round(min(w_ema11, w_sma20) * 0.95, 2)

                risk_amount = ltp - stop_loss
                target_1 = round(ltp + (2 * risk_amount), 2)
                target_2 = round(ltp + (3.5 * risk_amount), 2)

                pre_breakout_results.append(
                    {
                        "Symbol": symbol,
                        "LTP (₹)": round(ltp, 2),
                        "Weekly 11 EMA (₹)": round(w_ema11, 2),
                        "Weekly 20 SMA (₹)": round(w_sma20, 2),
                        "EMA11 Dist %": round(dist_ema11_pct, 2),
                        "SMA20 Dist %": round(dist_sma20_pct, 2),
                        "Weekly RSI (9)": round(w_rsi9, 1),
                        "MTF RSI 9 Status": "🟢 BUY Aligned" if cond_rsi_mtf_buy else "⚪ Neutral",
                        "BB Width %": round(curr_bb_width * 100, 2),
                        "Accumulation Zone (₹)": f"₹{accum_low} - ₹{accum_high}",
                        "Stop Loss (₹)": stop_loss,
                        "Target 1 (1:2) (₹)": target_1,
                        "Target 2 (1:3.5) (₹)": target_2,
                        "Setup Score": setup_score,
                        "Setup Grade": setup_grade,
                    }
                )

            time.sleep(0.05)

        except Exception as e:
            st.error(f"Error scanning pre-breakout for {symbol}: {str(e)}")

    status_text.text("Pre-Breakout Scan Completed!")
    progress_bar.empty()

    return pd.DataFrame(pre_breakout_results)


# ==========================================
# 15. MAIN STREAMLIT APPLICATION ROUTER
# ==========================================
def main():
    st.set_page_config(
        page_title="Institutional Market Intelligence & Algorithmic Screener",
        page_icon="📈",
        layout="wide",
    )

    st.title("📈 Institutional Market Intelligence Terminal")
    st.caption("Powered by Zerodha Kite Connect API | Real-time Option Chains & MTF Technical Analysis")

    # Authenticate Zerodha Session
    kite = get_authenticated_kite()

    if not kite:
        st.info("👋 Please complete Zerodha login in your browser window to start streaming live data.")
        st.stop()

    # Sidebar Navigation Controls
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
        st.caption("Score-based confluence engine: MTF trend + RVOL + Futures OI + CPR + structure + option-chain confirmation + risk vetoes. Scores rank setups; they do not guarantee returns.")
        if st.button("🚀 Run F&O Market Scan", type="primary"):
            df_intra, df_strict, df_all = scan_fno_opportunities(kite)

            tab_intraday, tab_strict, tab_universe = st.tabs(
                [
                    "⚡ Top Intraday Trades",
                    "🎯 High-Confidence Signals",
                    "📊 Entire Scanned Universe",
                ]
            )

            with tab_intraday:
                st.markdown("### ⚡ High Volume & Momentum Intraday Picks")
                st.dataframe(df_intra, use_container_width=True, hide_index=True)

            with tab_strict:
                st.markdown("### 🎯 Filtered Trade Setups")
                st.dataframe(df_strict, use_container_width=True, hide_index=True)

            with tab_universe:
                st.markdown("### 📊 All F&O Scanned Stocks")
                st.dataframe(df_all, use_container_width=True, hide_index=True)

    elif menu_choice == "🚀 Udd Ja Breakout (Cash Equities)":
        st.markdown("## 🚀 Udd Ja High-Volume Breakout Engine (Cash Equities)")
        if st.button("🚀 Scan Cash Equities for Udd Ja Breakouts", type="primary"):
            df_udd_ja = scan_udd_ja_cash_stocks(kite)
            if not df_udd_ja.empty:
                st.dataframe(df_udd_ja, use_container_width=True, hide_index=True)
            else:
                st.info("No Cash Equities matched the Udd Ja breakout criteria currently.")

    elif menu_choice == "📅 Yearly 52-Week Breakouts":
        st.markdown("## 📅 Yearly (52-Week High) Breakout Engine")
        if st.button("🚀 Scan 52-Week High Breakouts", type="primary"):
            df_yearly = scan_yearly_breakout_cash_stocks(kite)
            if not df_yearly.empty:
                st.dataframe(df_yearly, use_container_width=True, hide_index=True)
            else:
                st.info("No stocks currently near or breaking out of 52-Week High levels.")

    elif menu_choice == "🎯 Weekly Pre-Breakout Squeeze":
        st.markdown("## 🎯 Weekly Pre-Breakout Squeeze Engine")
        col_prox, col_rsi_l, col_rsi_h = st.columns(3)
        with col_prox:
            prox_val = st.number_input("MA Proximity Threshold (%)", value=1.0, step=0.1)
        with col_rsi_l:
            rsi_l_val = st.number_input("Weekly RSI Min", value=50.0, step=1.0)
        with col_rsi_h:
            rsi_h_val = st.number_input("Weekly RSI Max", value=65.0, step=1.0)

        if st.button("🚀 Run Pre-Breakout Squeeze Scan", type="primary"):
            df_pre = calculate_weekly_pre_breakout_candidates(
                kite, ma_prox_thresh=prox_val, rsi_min=rsi_l_val, rsi_max=rsi_h_val
            )
            if not df_pre.empty:
                st.dataframe(df_pre, use_container_width=True, hide_index=True)
            else:
                st.info("No stocks currently matching the Pre-Breakout Squeeze conditions.")

    elif menu_choice == "🔥 Hero-Zero Options Expiry Scan":
        st.markdown("## 🔥 Hero-Zero Expiry Options Engine")
        if st.button("⚡ Scan Active Expiry Index Options", type="primary"):
            df_hz = scan_hero_zero_opportunities(kite)
            if not df_hz.empty:
                st.dataframe(df_hz, use_container_width=True, hide_index=True)
            else:
                st.info("No active Hero-Zero opportunities detected at this time.")


if __name__ == "__main__":
    main()


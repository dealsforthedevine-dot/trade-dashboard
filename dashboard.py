import io
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Account Statement Dashboard", layout="wide")
st.title("Schwab / ThinkorSwim Account Statement Dashboard")

uploaded_file = st.file_uploader("Upload Account Statement export", type=["csv", "txt"])
if not uploaded_file:
    st.stop()

# --------- SECTION DEFINITIONS (column-based detection) ---------

SECTION_PATTERNS = {
    "CASH_BALANCE": ["DATE", "TIME", "TYPE", "DESCRIPTION", "AMOUNT", "BALANCE"],
    "FUTURES_STMT": ["Trade Date", "Exec Date", "Exec Time", "Description", "Amount", "Balance"],
    "FOREX": ["Date", "Time", "Type", "Description", "Amount(USD)", "Balance"],
    "CRYPTO": ["Trade Date", "Exec Date", "Exec Time", "Description", "Amount", "Balance"],
    "ORDERS": ["Time Placed", "Spread", "Side", "Qty", "Symbol", "Strike", "Status"],
    "TRADES": ["Exec Time", "Spread", "Side", "Qty", "Symbol", "Strike", "Net Price"],
    "EQUITIES": ["Symbol", "Description", "Qty", "Trade Price"],
    "OPTIONS_POS": ["Symbol", "Exp", "Strike", "Type", "Trade Price", "Mark", "Qty"],
    "FUTURES_POS": ["Symbol", "Description", "SPC", "Exp", "Qty", "Trade Price"],
    "PNL": ["Symbol", "Description", "P/L Open", "P/L Day", "P/L YTD"],
}

ACCOUNT_SUMMARY_KEYS = [
    "Net Liquidating Value",
    "Stock Buying Power",
    "Option Buying Power",
    "Equity Commissions & Fees YTD",
    "Futures Commissions & Fees YTD",
    "Crypto Trading Fees YTD",
    "Total Commissions & Fees YTD",
]

def detect_section(line: str):
    for name, cols in SECTION_PATTERNS.items():
        if all(col in line for col in cols):
            return name
    return None

def parse_statement(file):
    text = file.read().decode("utf-8", errors="ignore")
    lines = text.splitlines()

    sections = {name: [] for name in SECTION_PATTERNS}
    current = None
    buffer = []

    account_summary = {}

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        # Account Summary block
        if line.startswith("Account Summary"):
            j = i + 1
            while j < len(lines) and lines[j].strip():
                row = lines[j].split("\t")
                if len(row) >= 2:
                    key = row[0].strip()
                    val = row[1].strip()
                    if key in ACCOUNT_SUMMARY_KEYS:
                        account_summary[key] = val
                j += 1
            i = j
            continue

        sec = detect_section(line)
        if sec:
            if current and buffer:
                sections[current].append("\n".join(buffer))
            current = sec
            buffer = [raw]  # keep original line
        else:
            if current:
                buffer.append(raw)

        i += 1

    if current and buffer:
        sections[current].append("\n".join(buffer))

    dfs = {}
    for name, blocks in sections.items():
        frames = []
        for block in blocks:
            try:
                df = pd.read_csv(io.StringIO(block), sep=None, engine="python")
                frames.append(df)
            except:
                pass
        if frames:
            dfs[name] = pd.concat(frames, ignore_index=True)

    return dfs, account_summary

def safe_float_series(s):
    return (
        s.astype(str)
        .str.replace("[,$]", "", regex=True)
        .str.replace(" ", "", regex=False)
        .replace("", "0")
        .astype(float)
    )

dfs, acct_summary = parse_statement(uploaded_file)

if not dfs and not acct_summary:
    st.error("No recognizable sections found. This file uses a format we haven't mapped yet.")
    st.stop()

# ----------------- HIGH-LEVEL METRICS -----------------

# Net Liq from Account Summary
net_liq = None
if "Net Liquidating Value" in acct_summary:
    try:
        net_liq = float(acct_summary["Net Liquidating Value"].replace(",", "").replace("$", ""))
    except:
        net_liq = None

# Daily P/L from PNL section
daily_pl = None
if "PNL" in dfs and "P/L Day" in dfs["PNL"].columns:
    daily_pl = safe_float_series(dfs["PNL"]["P/L Day"]).sum()

# Total income / outflow from cash-like sections
total_inflow = 0.0
total_outflow = 0.0
for sec_name in ["CASH_BALANCE", "FUTURES_STMT", "FOREX", "CRYPTO"]:
    if sec_name in dfs:
        df = dfs[sec_name]
        amt_col = None
        for c in df.columns:
            if "Amount" in c or "AMOUNT" in c:
                amt_col = c
                break
        if amt_col:
            vals = safe_float_series(df[amt_col])
            total_inflow += vals[vals > 0].sum()
            total_outflow += vals[vals < 0].sum()

# Open positions count
open_positions = 0
for sec_name in ["EQUITIES", "OPTIONS_POS", "FUTURES_POS"]:
    if sec_name in dfs:
        open_positions += len(dfs[sec_name])

# Win rate from TRADES (very rough: positive Net Price vs negative)
win_rate = None
if "TRADES" in dfs and "Net Price" in dfs["TRADES"].columns:
    np_series = safe_float_series(dfs["TRADES"]["Net Price"])
    wins = (np_series > 0).sum()
    total_trades = (np_series != 0).sum()
    if total_trades > 0:
        win_rate = wins / total_trades * 100.0

# ----------------- LAYOUT: TABS -----------------

tabs = st.tabs(["Overview", "Positions", "Orders & Trades", "Cash & P/L", "Account Summary"])

# -------- Overview Tab --------
with tabs[0]:
    st.subheader("Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Net Liquidating Value", f"${net_liq:,.2f}" if net_liq is not None else "—")
    with col2:
        st.metric("Daily P/L", f"${daily_pl:,.2f}" if daily_pl is not None else "—")
    with col3:
        st.metric("Total Inflow", f"${total_inflow:,.2f}")
    with col4:
        st.metric("Total Outflow", f"${total_outflow:,.2f}")

    col5, col6 = st.columns([2, 1])

    # Portfolio allocation pie (by Mark Value or Qty)
    with col5:
        st.markdown("### Portfolio Allocation")
        alloc_rows = []

        if "EQUITIES" in dfs:
            e = dfs["EQUITIES"].copy()
            if "Qty" in e.columns:
                qty = safe_float_series(e["Qty"])
                for sym, q in zip(e["Symbol"], qty):
                    alloc_rows.append(("Equity", sym, q))
        if "OPTIONS_POS" in dfs:
            o = dfs["OPTIONS_POS"].copy()
            if "Mark Value" in o.columns:
                mv = safe_float_series(o["Mark Value"])
                for sym, v in zip(o["Symbol"], mv):
                    alloc_rows.append(("Option", sym, v))
        if "FUTURES_POS" in dfs:
            f = dfs["FUTURES_POS"].copy()
            if "P/L Day" in f.columns:
                pl = safe_float_series(f["P/L Day"])
                for sym, v in zip(f["Symbol"], pl):
                    alloc_rows.append(("Futures", sym, v))

        if alloc_rows:
            alloc_df = pd.DataFrame(alloc_rows, columns=["AssetClass", "Symbol", "Value"])
            alloc_df = alloc_df.groupby(["AssetClass", "Symbol"], as_index=False)["Value"].sum()
            fig = px.pie(
                alloc_df,
                values="Value",
                names="Symbol",
                color="AssetClass",
                title="Allocation by Symbol",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No position data available for allocation chart.")

    # Recent activity
    with col6:
        st.markdown("### Recent Activity")
        recent = None
        if "TRADES" in dfs:
            recent = dfs["TRADES"].copy()
            if "Exec Time" in recent.columns:
                recent = recent.tail(10)
        elif "ORDERS" in dfs:
            recent = dfs["ORDERS"].copy().tail(10)

        if recent is not None:
            st.dataframe(recent, use_container_width=True, height=350)
        else:
            st.info("No recent trades or orders found.")

# -------- Positions Tab --------
with tabs[1]:
    st.subheader("Open Positions")

    pos_tabs = st.tabs(["Equities", "Options", "Futures"])

    with pos_tabs[0]:
        if "EQUITIES" in dfs:
            st.markdown("#### Equities")
            st.dataframe(dfs["EQUITIES"], use_container_width=True)
        else:
            st.info("No equities positions found.")

    with pos_tabs[1]:
        if "OPTIONS_POS" in dfs:
            st.markdown("#### Options")
            st.dataframe(dfs["OPTIONS_POS"], use_container_width=True)
        else:
            st.info("No options positions found.")

    with pos_tabs[2]:
        if "FUTURES_POS" in dfs:
            st.markdown("#### Futures")
            st.dataframe(dfs["FUTURES_POS"], use_container_width=True)
        else:
            st.info("No futures positions found.")

# -------- Orders & Trades Tab --------
with tabs[2]:
    st.subheader("Orders & Trades")

    ot_tabs = st.tabs(["Orders", "Trades"])

    with ot_tabs[0]:
        if "ORDERS" in dfs:
            st.markdown("#### Orders")
            st.dataframe(dfs["ORDERS"], use_container_width=True)
        else:
            st.info("No orders section found.")

    with ot_tabs[1]:
        if "TRADES" in dfs:
            st.markdown("#### Trades")
            tdf = dfs["TRADES"].copy()
            st.dataframe(tdf, use_container_width=True)

            if "Symbol" in tdf.columns:
                sym_counts = tdf["Symbol"].value_counts().reset_index()
                sym_counts.columns = ["Symbol", "Trades"]
                fig = px.bar(sym_counts, x="Symbol", y="Trades", title="Trades per Symbol")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No trades section found.")

# -------- Cash & P/L Tab --------
with tabs[3]:
    st.subheader("Cash & P/L")

    cp_tabs = st.tabs(["Cash Flow", "P/L Summary"])

    with cp_tabs[0]:
        st.markdown("#### Cash-like Activity")
        combined = []
        for sec_name in ["CASH_BALANCE", "FUTURES_STMT", "FOREX", "CRYPTO"]:
            if sec_name in dfs:
                df = dfs[sec_name].copy()
                df["Source"] = sec_name
                combined.append(df)
        if combined:
            cdf = pd.concat(combined, ignore_index=True)
            st.dataframe(cdf, use_container_width=True)
        else:
            st.info("No cash/funding sections found.")

    with cp_tabs[1]:
        if "PNL" in dfs:
            st.markdown("#### P/L Summary")
            p_df = dfs["PNL"].copy()
            for col in ["P/L Open", "P/L Day", "P/L YTD"]:
                if col in p_df.columns:
                    p_df[col + "_NUM"] = safe_float_series(p_df[col])
            st.dataframe(p_df, use_container_width=True)

            if "Symbol" in p_df.columns and "P/L Day_NUM" in p_df.columns:
                sym_pl = p_df.groupby("Symbol", as_index=False)["P/L Day_NUM"].sum()
                fig = px.bar(sym_pl, x="Symbol", y="P/L Day_NUM", title="P/L Day by Symbol")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No P/L section found.")

# -------- Account Summary Tab --------
with tabs[4]:
    st.subheader("Account Summary")
    if acct_summary:
        summary_df = pd.DataFrame(
            [{"Metric": k, "Value": v} for k, v in acct_summary.items()]
        )
        st.table(summary_df)
    else:
        st.info("No Account Summary block detected.")

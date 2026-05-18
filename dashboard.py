# dashboard.py
import io
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(
    page_title="Schwab / ThinkorSwim Account Statement Analyzer",
    layout="wide",
)

st.title("Account Statement Analyzer")

st.markdown(
    "Upload your **Schwab / ThinkorSwim Account Statement export** (CSV/TXT). "
    "This app detects sections (Cash, Futures, Forex, Crypto, Orders, Trades, "
    "Equities, Options, Futures positions, P/L, Account Summary) and builds analytics."
)

uploaded_file = st.file_uploader("Upload Account Statement export", type=["csv", "txt"])

if not uploaded_file:
    st.info("Upload your Account Statement file to get started.")
    st.stop()

# ---------- Section definitions (by exact header line) ----------

SECTION_HEADERS = {
    # Cash balance section
    "CASH_BALANCE": "DATE\tTIME\tTYPE\tREF #\tDESCRIPTION\tMisc Fees\tCommissions & Fees\tAMOUNT\tBALANCE",
    # Futures statement (cash-style)
    "FUTURES_STMT": "Trade Date\tExec Date\tExec Time\tType\tRef #\tDescription\tMisc Fees\tCommissions & Fees\tAmount\tBalance",
    # Forex statements
    "FOREX": "Date\tTime\tType\tRef #\tDescription\tCommissions & Fees\tAmount\tAmount(USD)\tBalance",
    # Crypto
    "CRYPTO": "Trade Date\tExec Date\tExec Time\tType\tRef #\tDescription\tCommissions & Fees\tAmount\tBalance",
    # Account order history
    "ORDERS": "Notes\t\tTime Placed\tSpread\tSide\tQty\tPos Effect\tSymbol\tExp\tStrike\tType\tPRICE\t\tTIF\tStatus",
    # Account trade history
    "TRADES": "Exec Time\tSpread\tSide\tQty\tPos Effect\tSymbol\tExp\tStrike\tType\tPrice\tNet Price\tOrder Type",
    # Equities positions
    "EQUITIES": "Symbol\tDescription\tQty\tTrade Price",
    # Options positions
    "OPTIONS_POS": "Symbol\tExp\tStrike\tType\tTrade Price\tMark\tQty\tP/L Day\tP/L Open\tOption Code\tP/L %\tMark Value",
    # Futures positions
    "FUTURES_POS": "Symbol\tDescription\tSPC\tExp\tQty\tTrade Price\tP/L Day",
    # Profits and Losses summary
    "PNL": "Symbol\tDescription\tP/L Open\tP/L %\tP/L Day\tP/L YTD\tP/L Diff\tMargin Req\tMark Value",
    # Account Summary (we'll treat as key/value lines, not a tabular header)
    # We'll detect it by a line starting with 'Account Summary'
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
    line_stripped = line.strip()
    for name, header in SECTION_HEADERS.items():
        if line_stripped == header:
            return name
    return None

def parse_multi_section_statement(file):
    """Return dict: {section_name: DataFrame} and account_summary dict."""
    content = file.read()
    try:
        text = content.decode("utf-8")
    except AttributeError:
        text = content

    lines = text.splitlines()

    sections_raw = {name: [] for name in SECTION_HEADERS.keys()}
    current_section = None
    buffer = []

    account_summary = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect Account Summary block
        if stripped.startswith("Account Summary"):
            # Consume following lines until blank
            j = i + 1
            while j < len(lines) and lines[j].strip() != "":
                row = lines[j].strip()
                # Expect something like: "Net Liquidating Value\t123,456.78"
                parts = row.split("\t")
                if len(parts) >= 2:
                    key = parts[0].strip()
                    val = "\t".join(parts[1:]).strip()
                    if key in ACCOUNT_SUMMARY_KEYS:
                        account_summary[key] = val
                j += 1
            i = j
            continue

        sec = detect_section(line)
        if sec is not None:
            # flush previous
            if current_section is not None and buffer:
                sections_raw[current_section].append("\n".join(buffer))
            current_section = sec
            buffer = [SECTION_HEADERS[sec]]  # start with header
        else:
            if current_section is not None:
                buffer.append(line)

        i += 1

    # flush last
    if current_section is not None and buffer:
        sections_raw[current_section].append("\n".join(buffer))

    # Convert each section to DataFrame
    dfs = {}
    for name, blocks in sections_raw.items():
        if not blocks:
            continue
        frames = []
        for block in blocks:
            try:
                df = pd.read_csv(io.StringIO(block), sep="\t")
                frames.append(df)
            except Exception:
                continue
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

# ---------- Parse file ----------

try:
    section_dfs, account_summary = parse_multi_section_statement(uploaded_file)
except Exception as e:
    st.error(f"Error reading file: {e}")
    st.stop()

if not section_dfs and not account_summary:
    st.error("No recognizable sections found. Check that this is a Schwab / TOS Account Statement export.")
    st.stop()

detected = list(section_dfs.keys())
if account_summary:
    detected.append("ACCOUNT_SUMMARY")
st.success(f"Detected sections: {', '.join(detected)}")

# ---------- Tabs ----------

tab_labels = []
if "CASH_BALANCE" in section_dfs:
    tab_labels.append("Cash")
if "FUTURES_STMT" in section_dfs:
    tab_labels.append("Futures Statement")
if "FOREX" in section_dfs:
    tab_labels.append("Forex")
if "CRYPTO" in section_dfs:
    tab_labels.append("Crypto")
if "ORDERS" in section_dfs:
    tab_labels.append("Order History")
if "TRADES" in section_dfs:
    tab_labels.append("Trade History")
if "EQUITIES" in section_dfs:
    tab_labels.append("Equities")
if "OPTIONS_POS" in section_dfs:
    tab_labels.append("Options Positions")
if "FUTURES_POS" in section_dfs:
    tab_labels.append("Futures Positions")
if "PNL" in section_dfs:
    tab_labels.append("P/L Summary")
if account_summary:
    tab_labels.append("Account Summary")

tabs = st.tabs(tab_labels)
tab_index = 0

# ----- Cash tab -----
if "CASH_BALANCE" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Cash Balance")
        cash_df = section_dfs["CASH_BALANCE"].copy()

        for col in ["Misc Fees", "Commissions & Fees", "AMOUNT", "BALANCE"]:
            if col in cash_df.columns:
                cash_df[col + "_NUM"] = safe_float_series(cash_df[col])

        st.dataframe(cash_df, use_container_width=True)

        if "BALANCE_NUM" in cash_df.columns and "DATE" in cash_df.columns and "TIME" in cash_df.columns:
            cash_df["DATETIME"] = pd.to_datetime(
                cash_df["DATE"].astype(str) + " " + cash_df["TIME"].astype(str),
                errors="coerce",
            )
            cash_df = cash_df.sort_values("DATETIME")
            fig = px.line(
                cash_df,
                x="DATETIME",
                y="BALANCE_NUM",
                title="Cash Balance Over Time",
            )
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Futures statement tab -----
if "FUTURES_STMT" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Futures Statement (Cash)")
        fut_df = section_dfs["FUTURES_STMT"].copy()

        for col in ["Misc Fees", "Commissions & Fees", "Amount", "Balance"]:
            if col in fut_df.columns:
                fut_df[col + "_NUM"] = safe_float_series(fut_df[col])

        st.dataframe(fut_df, use_container_width=True)

        if "Amount_NUM" in fut_df.columns and "Exec Date" in fut_df.columns and "Exec Time" in fut_df.columns:
            fut_df["DATETIME"] = pd.to_datetime(
                fut_df["Exec Date"].astype(str) + " " + fut_df["Exec Time"].astype(str),
                errors="coerce",
            )
            fut_df = fut_df.sort_values("DATETIME")
            fut_df["CUM_P_L"] = fut_df["Amount_NUM"].cumsum()
            fig = px.line(
                fut_df,
                x="DATETIME",
                y="CUM_P_L",
                title="Futures Cumulative P/L",
            )
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Forex tab -----
if "FOREX" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Forex Statements")
        fx_df = section_dfs["FOREX"].copy()

        for col in ["Commissions & Fees", "Amount", "Amount(USD)", "Balance"]:
            if col in fx_df.columns:
                fx_df[col + "_NUM"] = safe_float_series(fx_df[col])

        st.dataframe(fx_df, use_container_width=True)

        if "Amount(USD)_NUM" in fx_df.columns and "Date" in fx_df.columns and "Time" in fx_df.columns:
            fx_df["DATETIME"] = pd.to_datetime(
                fx_df["Date"].astype(str) + " " + fx_df["Time"].astype(str),
                errors="coerce",
            )
            fx_df = fx_df.sort_values("DATETIME")
            fx_df["CUM_P_L"] = fx_df["Amount(USD)_NUM"].cumsum()
            fig = px.line(
                fx_df,
                x="DATETIME",
                y="CUM_P_L",
                title="Forex Cumulative P/L (USD)",
            )
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Crypto tab -----
if "CRYPTO" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Crypto Statement")
        c_df = section_dfs["CRYPTO"].copy()

        for col in ["Commissions & Fees", "Amount", "Balance"]:
            if col in c_df.columns:
                c_df[col + "_NUM"] = safe_float_series(c_df[col])

        st.dataframe(c_df, use_container_width=True)

        if "Amount_NUM" in c_df.columns and "Exec Date" in c_df.columns and "Exec Time" in c_df.columns:
            c_df["DATETIME"] = pd.to_datetime(
                c_df["Exec Date"].astype(str) + " " + c_df["Exec Time"].astype(str),
                errors="coerce",
            )
            c_df = c_df.sort_values("DATETIME")
            c_df["CUM_P_L"] = c_df["Amount_NUM"].cumsum()
            fig = px.line(
                c_df,
                x="DATETIME",
                y="CUM_P_L",
                title="Crypto Cumulative P/L",
            )
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Order history tab -----
if "ORDERS" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Account Order History")
        o_df = section_dfs["ORDERS"].copy()
        st.dataframe(o_df, use_container_width=True)

        if "Symbol" in o_df.columns:
            sym_counts = o_df["Symbol"].value_counts().reset_index()
            sym_counts.columns = ["Symbol", "Orders"]
            fig = px.bar(sym_counts, x="Symbol", y="Orders", title="Orders per Symbol")
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Trade history tab -----
if "TRADES" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Account Trade History")
        t_df = section_dfs["TRADES"].copy()

        if "Price" in t_df.columns:
            t_df["Price_NUM"] = safe_float_series(t_df["Price"])
        if "Net Price" in t_df.columns:
            t_df["NetPrice_NUM"] = safe_float_series(t_df["Net Price"])

        st.dataframe(t_df, use_container_width=True)

        if "Symbol" in t_df.columns:
            sym_counts = t_df["Symbol"].value_counts().reset_index()
            sym_counts.columns = ["Symbol", "Trades"]
            fig = px.bar(sym_counts, x="Symbol", y="Trades", title="Trades per Symbol")
            st.plotly_chart(fig, use_container_width=True)

        if "Exec Time" in t_df.columns:
            fig2 = px.histogram(
                t_df,
                x="Exec Time",
                title="Trade Time Distribution",
            )
            st.plotly_chart(fig2, use_container_width=True)
    tab_index += 1

# ----- Equities tab -----
if "EQUITIES" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Equities Positions")
        e_df = section_dfs["EQUITIES"].copy()
        st.dataframe(e_df, use_container_width=True)

        if "Symbol" in e_df.columns and "Qty" in e_df.columns:
            qty = safe_float_series(e_df["Qty"])
            sym_qty = pd.DataFrame({"Symbol": e_df["Symbol"], "Qty": qty})
            sym_qty = sym_qty.groupby("Symbol", as_index=False)["Qty"].sum()
            fig = px.bar(sym_qty, x="Symbol", y="Qty", title="Equity Position Size by Symbol")
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Options positions tab -----
if "OPTIONS_POS" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Options Positions")
        op_df = section_dfs["OPTIONS_POS"].copy()
        st.dataframe(op_df, use_container_width=True)

        if "Symbol" in op_df.columns and "Qty" in op_df.columns:
            qty = safe_float_series(op_df["Qty"])
            sym_qty = pd.DataFrame({"Symbol": op_df["Symbol"], "Qty": qty})
            sym_qty = sym_qty.groupby("Symbol", as_index=False)["Qty"].sum()
            fig = px.bar(sym_qty, x="Symbol", y="Qty", title="Options Position Size by Symbol")
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Futures positions tab -----
if "FUTURES_POS" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Futures Positions")
        fp_df = section_dfs["FUTURES_POS"].copy()
        st.dataframe(fp_df, use_container_width=True)

        if "Symbol" in fp_df.columns and "Qty" in fp_df.columns:
            qty = safe_float_series(fp_df["Qty"])
            sym_qty = pd.DataFrame({"Symbol": fp_df["Symbol"], "Qty": qty})
            sym_qty = sym_qty.groupby("Symbol", as_index=False)["Qty"].sum()
            fig = px.bar(sym_qty, x="Symbol", y="Qty", title="Futures Position Size by Symbol")
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- P/L summary tab -----
if "PNL" in section_dfs:
    with tabs[tab_index]:
        st.subheader("Profits and Losses Summary")
        p_df = section_dfs["PNL"].copy()

        for col in ["P/L Open", "P/L %", "P/L Day", "P/L YTD", "P/L Diff", "Margin Req", "Mark Value"]:
            if col in p_df.columns:
                p_df[col + "_NUM"] = safe_float_series(p_df[col])

        st.dataframe(p_df, use_container_width=True)

        if "Symbol" in p_df.columns and "P/L Day_NUM" in p_df.columns:
            sym_pl = p_df.groupby("Symbol", as_index=False)["P/L Day_NUM"].sum()
            fig = px.bar(sym_pl, x="Symbol", y="P/L Day_NUM", title="P/L Day by Symbol")
            st.plotly_chart(fig, use_container_width=True)
    tab_index += 1

# ----- Account Summary tab -----
if account_summary:
    with tabs[tab_index]:
        st.subheader("Account Summary")
        summary_items = [{"Metric": k, "Value": v} for k, v in account_summary.items()]
        summary_df = pd.DataFrame(summary_items)
        st.table(summary_df)

st.caption(
    "This dashboard parses the multi-section Schwab / ThinkorSwim Account Statement export and "
    "builds analytics for cash, futures, forex, crypto, orders, trades, positions, P/L, and account summary."
)

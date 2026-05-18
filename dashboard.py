import io
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Account Statement Analyzer", layout="wide")
st.title("Schwab / ThinkorSwim Account Statement Analyzer")

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

def detect_section(line):
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
        line = lines[i].strip()

        # Detect Account Summary
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

        # Detect section header
        sec = detect_section(line)
        if sec:
            if current and buffer:
                sections[current].append("\n".join(buffer))
            current = sec
            buffer = [line]
        else:
            if current:
                buffer.append(line)

        i += 1

    if current and buffer:
        sections[current].append("\n".join(buffer))

    # Convert to DataFrames
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

dfs, acct_summary = parse_statement(uploaded_file)

if not dfs and not acct_summary:
    st.error("No recognizable sections found. This file uses a format we haven't mapped yet.")
    st.stop()

st.success("Sections detected: " + ", ".join([k for k in dfs if dfs[k].shape[0] > 0]))

# --------- DISPLAY TABS ---------

tabs = st.tabs([k for k in dfs] + (["Account Summary"] if acct_summary else []))

for idx, name in enumerate(dfs):
    with tabs[idx]:
        st.subheader(name.replace("_", " ").title())
        st.dataframe(dfs[name], use_container_width=True)

if acct_summary:
    with tabs[-1]:
        st.subheader("Account Summary")
        st.table(pd.DataFrame(list(acct_summary.items()), columns=["Metric", "Value"]))

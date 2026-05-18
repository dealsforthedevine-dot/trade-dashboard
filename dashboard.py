# dashboard.py
import re
import io
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(
    page_title="Trade Analytics Dashboard",
    layout="wide",
)

# ---------- Helpers ----------

def parse_tos_description(desc: str):
    """
    Parse ThinkorSwim DESCRIPTION field like:
    'SOLD -10 SOXL 100 (Weeklys) 22 MAY 26 144 PUT @5.25 CBOE'
    """
    if not isinstance(desc, str):
        return None, None, None, None, None, None

    # Action
    action = "SELL" if "SOLD" in desc.upper() else "BUY" if "BOT" in desc.upper() else None

    # Qty (handles -10 or +10)
    qty_match = re.search(r'([+-]?\d+)\s+[A-Z]+ 100', desc)
    qty = int(qty_match.group(1)) if qty_match else None

    # Symbol
    sym_match = re.search(r'\s([A-Z]+)\s+100', desc)
    symbol = sym_match.group(1) if sym_match else None

    # Expiration (e.g. '22 MAY 26')
    exp_match = re.search(r'(\d{1,2}\s+[A-Z]{3}\s+\d{2})', desc)
    expiration = exp_match.group(1) if exp_match else None

    # Strike
    strike_match = re.search(r'\s(\d+(\.\d+)?)\s+(CALL|PUT)', desc)
    strike = float(strike_match.group(1)) if strike_match else None

    # Call/Put
    cp_match = re.search(r'(CALL|PUT)', desc)
    cp = cp_match.group(1) if cp_match else None

    # Price
    price_match = re.search(r'@(\d+(\.\d+)?)', desc)
    price = float(price_match.group(1)) if price_match else None

    return action, qty, symbol, expiration, strike, cp, price


def load_tos_csv(file) -> pd.DataFrame:
    # Try to read as tab or comma separated
    content = file.read()
    try:
        df = pd.read_csv(io.BytesIO(content), sep="\t")
    except Exception:
        df = pd.read_csv(io.BytesIO(content))

    # Normalize column names
    df.columns = [c.strip().upper() for c in df.columns]

    # Parse description into structured fields
    parsed = df["DESCRIPTION"].apply(parse_tos_description)
    df[["ACTION", "QTY", "SYMBOL", "EXPIRATION", "STRIKE", "CP", "PRICE"]] = pd.DataFrame(
        parsed.tolist(), index=df.index
    )

    # Cash flow (AMOUNT) if present
    if "AMOUNT" in df.columns:
        df["AMOUNT_CLEAN"] = (
            df["AMOUNT"]
            .astype(str)
            .str.replace("[,$]", "", regex=True)
            .astype(float)
        )
    else:
        df["AMOUNT_CLEAN"] = 0.0

    # Build a trade key per contract
    df["TRADE_KEY"] = (
        df["SYMBOL"].astype(str)
        + "_"
        + df["EXPIRATION"].astype(str)
        + "_"
        + df["STRIKE"].astype(str)
        + "_"
        + df["CP"].astype(str)
    )

    # Combine DATE + TIME if present
    if "DATE" in df.columns:
        if "TIME" in df.columns:
            df["DATETIME"] = pd.to_datetime(df["DATE"] + " " + df["TIME"], errors="coerce")
        else:
            df["DATETIME"] = pd.to_datetime(df["DATE"], errors="coerce")
    else:
        df["DATETIME"] = pd.NaT

    return df


def build_trade_summary(df: pd.DataFrame) -> pd.DataFrame:
    # Aggregate by TRADE_KEY to get net P/L per contract group
    grp = df.groupby("TRADE_KEY", dropna=False)

    summary = grp.agg(
        SYMBOL=("SYMBOL", "first"),
        EXPIRATION=("EXPIRATION", "first"),
        STRIKE=("STRIKE", "first"),
        CP=("CP", "first"),
        QTY_NET=("QTY", "sum"),
        CASH_FLOW=("AMOUNT_CLEAN", "sum"),
        FIRST_DT=("DATETIME", "min"),
        LAST_DT=("DATETIME", "max"),
    ).reset_index()

    # Define outcome: positive cash flow = profit (for closed trades)
    summary["P_L"] = summary["CASH_FLOW"]
    summary["OUTCOME"] = summary["P_L"].apply(lambda x: "Win" if x > 0 else "Loss" if x < 0 else "Flat")

    # Simple R-multiple placeholder
    losses = summary.loc[summary["P_L"] < 0, "P_L"].abs()
    avg_loss = losses.mean() if not losses.empty else 1.0
    summary["R_MULTIPLE"] = summary["P_L"] / avg_loss if avg_loss != 0 else 0

    return summary


# ---------- UI ----------

st.title("Trade Analytics Dashboard")

st.markdown(
    "Upload your **ThinkorSwim trade export** (CSV or TXT). "
    "This app will parse the DESCRIPTION field, group trades, and show analytics."
)

uploaded_file = st.file_uploader("Upload ThinkorSwim export", type=["csv", "txt"])

if not uploaded_file:
    st.info("Upload a ThinkorSwim export file to get started.")
    st.stop()

try:
    raw_df = load_tos_csv(uploaded_file)
except Exception as e:
    st.error(f"Error reading file: {e}")
    st.stop()

summary_df = build_trade_summary(raw_df)

# Strategy tagging (Support/Resistance, FVG, etc.)
st.sidebar.header("Filters & Tags")

# Add a simple manual tag column if not present
if "SETUP_TYPE" not in summary_df.columns:
    summary_df["SETUP_TYPE"] = "Unlabeled"

# Let user tag by symbol or trade key
with st.sidebar.expander("Tag trades (SR / FVG / Other)", expanded=False):
    editable = st.data_editor(
        summary_df[["TRADE_KEY", "SYMBOL", "P_L", "OUTCOME", "SETUP_TYPE"]],
        num_rows="dynamic",
        key="tag_editor",
    )
    summary_df = summary_df.drop(columns=["SETUP_TYPE"]).merge(
        editable[["TRADE_KEY", "SETUP_TYPE"]],
        on="TRADE_KEY",
        how="left",
    )

# Filters
symbols = sorted(summary_df["SYMBOL"].dropna().unique().tolist())
selected_symbols = st.sidebar.multiselect("Symbols", symbols, default=symbols)

setup_types = sorted(summary_df["SETUP_TYPE"].dropna().unique().tolist())
selected_setups = st.sidebar.multiselect("Setup Types", setup_types, default=setup_types)

filtered = summary_df[
    summary_df["SYMBOL"].isin(selected_symbols)
    & summary_df["SETUP_TYPE"].isin(selected_setups)
]

# ---------- Top metrics ----------

total_trades = len(filtered)
wins = (filtered["OUTCOME"] == "Win").sum()
losses = (filtered["OUTCOME"] == "Loss").sum()
win_rate = wins / total_trades * 100 if total_trades > 0 else 0
net_pl = filtered["P_L"].sum()
avg_r = filtered["R_MULTIPLE"].mean() if total_trades > 0 else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Trades", total_trades)
col2.metric("Win Rate", f"{win_rate:.1f}%")
col3.metric("Net P/L", f"{net_pl:,.2f}")
col4.metric("Avg R Multiple", f"{avg_r:.2f}")

# ---------- Equity curve ----------

st.subheader("Equity Curve")

ec = raw_df.sort_values("DATETIME").copy()
ec["CUM_P_L"] = ec["AMOUNT_CLEAN"].cumsum()

fig_ec = px.line(
    ec,
    x="DATETIME",
    y="CUM_P_L",
    title="Account Growth (Cumulative P/L)",
)
st.plotly_chart(fig_ec, use_container_width=True)

# ---------- Setup performance ----------

st.subheader("Setup Performance (SR / FVG / Other)")

setup_perf = (
    filtered.groupby("SETUP_TYPE")
    .agg(
        TRADES=("TRADE_KEY", "count"),
        WIN_RATE=("OUTCOME", lambda x: (x == "Win").mean() * 100),
        AVG_R=("R_MULTIPLE", "mean"),
        NET_PL=("P_L", "sum"),
    )
    .reset_index()
)

col_a, col_b = st.columns([2, 1])

with col_a:
    st.dataframe(setup_perf, use_container_width=True)

with col_b:
    fig_pie = px.pie(
        setup_perf,
        names="SETUP_TYPE",
        values="TRADES",
        title="Trades by Setup Type",
    )
    st.plotly_chart(fig_pie, use_container_width=True)

# ---------- Trade table ----------

st.subheader("Trades")

st.dataframe(
    filtered[
        [
            "TRADE_KEY",
            "SYMBOL",
            "EXPIRATION",
            "STRIKE",
            "CP",
            "QTY_NET",
            "P_L",
            "R_MULTIPLE",
            "OUTCOME",
            "SETUP_TYPE",
            "FIRST_DT",
            "LAST_DT",
        ]
    ].sort_values("FIRST_DT"),
    use_container_width=True,
)

st.caption(
    "You can refine the parser, add more metrics (ICT FVG efficiency, SR reliability, session stats), "
    "and persist tags using a simple database later. For now, this gives you a working, local dashboard "
    "that ingests ThinkorSwim exports directly."
)

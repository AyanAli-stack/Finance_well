# dataentry.py — Finance Tracker (username + 10-char passcode)

import pandas as pd
import streamlit as st
import plotly.express as px
import sqlite3, bcrypt
from contextlib import contextmanager
from typing import Optional

#  DB HELPERS
DB_PATH = "finance.db"

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as conn:
        # Users: username + passcode_hash (only)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            passcode_hash BLOB NOT NULL
        );
        """)

        # Transactions (per user)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)

def get_user_id_by_username(username: str) -> Optional[int]:
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        return row[0] if row else None

def create_user(username: str, passcode: str) -> Optional[int]:
    """
    Create a user with a 10-character passcode (any characters allowed).
    Returns new user_id or None if invalid / already exists.
    """
    if not username or passcode is None or len(passcode) != 10:
        return None
    if get_user_id_by_username(username) is not None:
        return None
    p_hash = bcrypt.hashpw(passcode.encode("utf-8"), bcrypt.gensalt())
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users(username, passcode_hash) VALUES(?,?)",
            (username, p_hash)
        )
        return cur.lastrowid

def verify_user(username: str, passcode: str) -> Optional[int]:
    """
    Verify username + 10-char passcode.
    Returns user_id if ok, otherwise None.
    """
    if not username or passcode is None:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT id, passcode_hash FROM users WHERE username=?",
            (username,)
        ).fetchone()
    if not row:
        return None
    uid, stored = row
    if bcrypt.checkpw(passcode.encode("utf-8"), stored):
        return uid
    return None

def list_transactions(user_id: int) -> pd.DataFrame:
    with db() as conn:
        rows = conn.execute("""
            SELECT date, amount, category, description
            FROM transactions
            WHERE user_id=?
            ORDER BY date ASC, id ASC
        """, (user_id,)).fetchall()
    return pd.DataFrame(rows, columns=["date", "amount", "category", "description"])

def insert_transaction(user_id: int, date: str, amount: float, category: str, description: str):
    with db() as conn:
        conn.execute("""
            INSERT INTO transactions(user_id, date, amount, category, description)
            VALUES(?,?,?,?,?)
        """, (user_id, date, amount, category, description))

def reset_user_data(user_id: int):
    with db() as conn:
        conn.execute("DELETE FROM transactions WHERE user_id=?", (user_id,))


#  APP STATE
init_db()
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = None

st.title("Finance Tracker")

# AUTH (Login / Register) 
if st.session_state.user_id is None:
    st.header("Account")
    mode = st.radio("Choose an action", ["Login", "Register"], horizontal=True)

    if mode == "Register":
        u = st.text_input("Username", key="reg_user")
        p1 = st.text_input("10-character passcode", type="password", key="reg_pc1", max_chars=10)
        p2 = st.text_input("Confirm passcode", type="password", key="reg_pc2", max_chars=10)
        st.caption("Passcode must be exactly 10 characters (any characters allowed).")

        if st.button("Create account", key="reg_btn"):
            if len(p1 or "") != 10:
                st.error("Passcode must be exactly 10 characters.")
            elif p1 != p2:
                st.error("Passcodes do not match.")
            else:
                new_id = create_user(u.strip(), p1)
                if new_id:
                    st.success("Account created. You can now log in.")
                    st.rerun()
                else:
                    st.error("Username exists or invalid input.")

    else:  # Login
        u = st.text_input("Username", key="login_user")
        p = st.text_input("10-character passcode", type="password", key="login_pc", max_chars=10)

        if st.button("Sign in", key="login_btn"):
            if len(p or "") != 10:
                st.error("Passcode must be exactly 10 characters.")
            else:
                uid = verify_user(u.strip(), p)
                if uid is None:
                    st.error("Invalid username or passcode.")
                else:
                    st.session_state.user_id = uid
                    st.session_state.username = u.strip()
                    st.success(f"Welcome back, {st.session_state.username}!")
                    st.rerun()

    st.stop()  # Halt rendering until logged in

# LOADED (AUTH OK) 
st.caption(f"Logged in as: {st.session_state.username}")

# Load this user's transactions
df = list_transactions(st.session_state.user_id)
if not df.empty:
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

# Sidebar filters (shared)
with st.sidebar:
    st.header("Filters")
    if df.empty or df["date"].dropna().empty:
        st.info("No data yet. Add a transaction.")
        df_filtered = df.copy()
    else:
        valid_dates = df["date"].dropna()
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()
        dr = st.date_input("Date range", (min_date, max_date))
        start_date, end_date = (dr if isinstance(dr, tuple) else (dr, dr))

        mask = (
            df["date"].notna()
            & (df["date"].dt.date >= start_date)
            & (df["date"].dt.date <= end_date)
        )
        df_range = df[mask]

        cats = sorted(df_range["category"].dropna().unique().tolist())
        picked_cats = st.multiselect("Filter by category", cats, default=cats)
        df_filtered = (
            df_range[df_range["category"].isin(picked_cats)]
            if picked_cats else df_range.iloc[0:0]
        )

# Tabs
tab_tx, tab_insights, tab_dash, tab_settings = st.tabs(
    ["Transactions", "Insights", "Dashboard", "Settings"]
)

# TRANSACTIONS 
with tab_tx:
    st.subheader("Add a new transaction")
    with st.form("transaction_form"):
        date = st.date_input("Date")
        amount = st.number_input("Amount", min_value=0.01, step=0.01, format="%.2f")

        CATEGORY_CHOICES = [
            "Food", "Rent", "Transport", "Shopping", "Utilities",
            "Entertainment", "Health", "Income", "Other"
        ]
        picked = st.selectbox("Category", CATEGORY_CHOICES, key="form_cat_select")
        custom_cat = st.text_input("Custom category (only if you picked 'Other')") if picked == "Other" else ""
        category = (custom_cat.strip() if picked == "Other" else picked).strip()

        description = st.text_input("Description")
        submitted = st.form_submit_button("Add Transaction")

        if submitted:
            if not category:
                st.error("Category can't be empty.")
            else:
                insert_transaction(
                    st.session_state.user_id,
                    str(date),
                    float(amount),
                    category,
                    description.strip(),
                )
                st.success(f"Transaction added! ({category}, ${amount:.2f})")
                st.rerun()

    st.subheader("Transactions")
    st.dataframe(df_filtered, width="stretch")

    total = df_filtered["amount"].sum() if not df_filtered.empty else 0.0
    st.caption(f"Total shown: ${total:,.2f}")

    if not df_filtered.empty:
        df_ms = df_filtered.copy()
        df_ms["date"] = pd.to_datetime(df_ms["date"], errors="coerce")
        month_summary = (
            df_ms.dropna(subset=["date"])
                 .groupby(pd.Grouper(key="date", freq="MS"))["amount"]
                 .sum()
                 .reset_index()
        )
        month_summary["month"] = month_summary["date"].dt.strftime("%Y-%m")
        month_summary = month_summary[["month", "amount"]]
        st.subheader("Monthly summary")
        st.dataframe(month_summary, width="stretch")

# INSIGHTS 
with tab_insights:
    st.subheader("Spending by category")
    if not df_filtered.empty:
        category_summary = (
            df_filtered.groupby("category", dropna=False)["amount"]
                       .sum()
                       .reset_index()
                       .sort_values("amount", ascending=False)
        )
        total_amount = float(category_summary["amount"].sum())
        category_summary["percent"] = (category_summary["amount"] / total_amount * 100).round(1)

        fig = px.pie(
            category_summary,
            names="category",
            values="amount",
            hole=0.6,
        )
        fig.update_traces(textinfo="percent+label", textposition="inside")
        st.plotly_chart(fig, use_container_width=True)

        st.write("Top categories")
        st.dataframe(category_summary.rename(columns={
            "amount": "total_amount", "percent": "percent_of_total"
        }), width="stretch")
    else:
        st.info("No data in current filter to chart.")

# DASHBOARD 
with tab_dash:
    st.subheader("Overview")
    if df_filtered.empty:
        st.info("No data in current filter to summarize.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total spend", f"${df_filtered['amount'].sum():,.2f}")
        with col2:
            st.metric("Transactions", f"{len(df_filtered):,}")
        with col3:
            avg = df_filtered["amount"].mean()
            st.metric("Avg per transaction", f"${avg:,.2f}")

        df_tr = df_filtered.copy()
        df_tr["date"] = pd.to_datetime(df_tr["date"], errors="coerce")
        trend = (
            df_tr.dropna(subset=["date"])
                 .groupby(pd.Grouper(key="date", freq="MS"))["amount"]
                 .sum()
                 .reset_index()
        )
        trend["month"] = trend["date"].dt.strftime("%Y-%m")
        st.line_chart(trend.set_index("month")["amount"])

#  SETTINGS 
with tab_settings:
    st.subheader("Settings")
    st.write("Manage your data and session:")

    colA, colB = st.columns(2)
    with colA:
        if st.button("⚠️ Reset my transactions"):
            reset_user_data(st.session_state.user_id)
            st.success("All your transactions were cleared.")
            st.rerun()

    with colB:
        if not df.empty:
            st.download_button(
                label="Download my CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"{st.session_state.username}_finance_export.csv",
                mime="text/csv",
            )
        else:
            st.info("No data to download yet.")

    st.divider()

    # Change passcode (must be exactly 10 chars)
    st.markdown("**Update passcode**")
    new_p = st.text_input("New 10-character passcode", type="password", max_chars=10, key="set_passcode")
    if st.button("Save new passcode", key="save_passcode"):
        if len(new_p or "") != 10:
            st.error("Passcode must be exactly 10 characters.")
        else:
            with db() as conn:
                h = bcrypt.hashpw(new_p.encode("utf-8"), bcrypt.gensalt())
                conn.execute("UPDATE users SET passcode_hash=? WHERE id=?", (h, st.session_state.user_id))
            st.success("Passcode updated.")

    st.divider()
    if st.button("Sign out", key="signout_bottom"):
        st.session_state.user_id = None
        st.session_state.username = None
        st.success("Signed out.")
        st.rerun()



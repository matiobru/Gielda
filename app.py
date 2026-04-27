import streamlit as st
import pandas as pd
import yfinance as yf
import ta
import sqlite3
import requests
import google.generativeai as genai
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- KONFIGURACJA ---
st.set_page_config(page_title="Kombinat Pro", layout="wide")
DB_FILE = 'portfel.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.cursor().execute('CREATE TABLE IF NOT EXISTS portfel (Symbol TEXT PRIMARY KEY, Cena_Kupna REAL)')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM portfel", conn)
    conn.close()
    return df

def save_db(df):
    conn = sqlite3.connect(DB_FILE)
    df.to_sql('portfel', conn, if_exists='replace', index=False)
    conn.commit()
    conn.close()

init_db()

# --- ANALITYKA ---
def find_patterns(df):
    if len(df) < 5: return "Brak"
    c = df.iloc[-1]
    p = df.iloc[-2]
    body = abs(c.Open - c.Close)
    l_shadow = min(c.Open, c.Close) - c.Low
    u_shadow = c.High - max(c.Open, c.Close)
    if l_shadow > 2*body and u_shadow < 0.2*body: return "🔨 Młot"
    if p.Close < p.Open and c.Close > c.Open and c.Open <= p.Close and c.Close >= p.Open: return "📈 Objęcie"
    return "Brak"

def get_avwap(df):
    try:
        pivot = df['High'].tail(150).idxmax()
        d = df.loc[pivot:].copy()
        d['TP'] = (d.High + d.Low + d.Close) / 3
        return (d.TP * d.Volume).cumsum() / d.Volume.cumsum()
    except: return None

# --- POBIERANIE ---
st.sidebar.header("🔑 AI & Rynek")
api_key = st.sidebar.text_input("Gemini API Key", type="password")
new_s = st.sidebar.text_input("Dodaj Akcję:").upper()
if st.sidebar.button("Dodaj"):
    db = get_db()
    if new_s and new_s not in db.Symbol.values:
        save_db(pd.concat([db, pd.DataFrame({'Symbol':[new_s], 'Cena_Kupna':[0.0]})]))
        st.rerun()

@st.cache_data(ttl=3600)
def fetch(tickers):
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0'})
    t_str = " ".join(tickers)
    d1d = yf.download(t_str, period="1y", interval="1d", group_by="ticker", session=s)
    d1h = yf.download(t_str, period="1mo", interval="1h", group_by="ticker", session=s)
    return d1d, d1h

# --- LOGIKA GŁÓWNA ---
db_portfel = get_db()
nasdaq = ['QQQ','AAPL','NVDA','MSFT','TSLA','AMD','PLTR','META','AMZN','GOOGL']
all_t = list(set(nasdaq + db_portfel.Symbol.tolist() + ['QQQ']))

if all_t:
    d1d, d1h = fetch(all_t)
    res = []
    for t in [x for x in all_t if x != 'QQQ']:
        try:
            df = d1d[t].dropna()
            dfh = d1h[t].dropna()
            c = df.Close.iloc[-1]
            
            # Wskaźniki
            rsi1d = ta.momentum.rsi(df.Close, 14).iloc[-1]
            rsi1h = ta.momentum.rsi(dfh.Close, 14).iloc[-1]
            ema10, ema20 = ta.trend.ema_indicator(df.Close, 10).iloc[-1], ta.trend.ema_indicator(df.Close, 20).iloc[-1]
            vol_s = df.Volume.tail(20).mean()
            rvol = df.Volume.iloc[-1] / vol_s
            avw = get_avwap(df).iloc[-1]
            
            # Fibo & SL
            hi, lo = df.High.max(), df.Low.min()
            f38 = hi - (hi - lo) * 0.382
            sl = max(avw * 0.98, c - (ta.volatility.average_true_range(df.High, df.Low, df.Close).iloc[-1] * 1.5))

            res.append({
                "Symbol": t, "Cena": round(c, 2), "Wzór": find_patterns(df),
                "RSI 1h": round(rsi1h, 1), "RSI 1d": round(rsi1d, 1), "RVOL": round(rvol, 2),
                "EMA10": round(ema10, 2), "EMA20": round(ema20, 2), "AVWAP": round(avw, 2),
                "Fibo 38": round(f38, 2), "MACD": round(ta.trend.macd_diff(df.Close).iloc[-1], 2),
                "Stop Loss": round(sl, 2)
            })
        except: pass

    # --- UI ---
    df_res = pd.DataFrame(res)
    t1, t2, t3 = st.tabs(["🛡️ Portfel", "🌐 Skaner", "🧠 AI Gemini"])
    
    with t1:
        edit_db = st.data_editor(db_portfel, num_rows="dynamic", use_container_width=True)
        if not edit_db.equals(db_portfel): save_db(edit_db); st.rerun()
        
        m = pd.merge(edit_db, df_res, on="Symbol")
        if not m.empty:
            m['Zysk %'] = ((m.Cena - m.Cena_Kupna)/m.Cena_Kupna*100).apply(lambda x: f"{x:+.2f}%")
            st.dataframe(m[['Symbol','Zysk %','Cena','Cena_Kupna','Stop Loss','Wzór','RSI 1h','RSI 1d','AVWAP']], use_container_width=True)

    with t2: st.dataframe(df_res, use_container_width=True)

    with t3:
        if api_key:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-flash-latest')
            if st.button("🤖 Analizuj Portfel"):
                txt = m.to_string()
                resp = model.generate_content(f"Jesteś traderem. Oceń mój portfel na 2 tygodnie: {txt}. Podaj konkretne ruchy i Stop Lossy.")
                st.info(resp.text)

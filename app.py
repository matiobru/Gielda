import streamlit as st
import pandas as pd
import yfinance as yf
import ta
import datetime
import plotly.graph_objects as go
import requests
import sqlite3
import google.generativeai as genai

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kombinat Giełdowy Pro", layout="wide", page_icon="📈")
st.title("📈 Kombinat Giełdowy - God Mode (UGREEN Edition)")

# --- BAZA DANYCH (Lokalna SQLite) ---
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

# --- PANEL BOCZNY (KLUCZE I WATCHLISTA) ---
st.sidebar.header("🔑 Klucze Dostępu")
gemini_api_key = st.sidebar.text_input("Gemini API Key", type="password")
tg_token = st.sidebar.text_input("Telegram Bot Token", type="password")
tg_chat_id = st.sidebar.text_input("Telegram Chat ID", type="password")

st.sidebar.header("⚙️ Dodaj do Bazy")
nowy_ticker = st.sidebar.text_input("Dodaj akcję (np. PLTR):").upper()
if st.sidebar.button("Dodaj"):
    db = get_db()
    if nowy_ticker and nowy_ticker not in db['Symbol'].values:
        save_db(pd.concat([db, pd.DataFrame({'Symbol':[nowy_ticker], 'Cena_Kupna':[0.0]})], ignore_index=True))
        st.sidebar.success(f"Dodano {nowy_ticker}!")
        st.rerun()

def wyslij_telegram(wiadomosc):
    if tg_token and tg_chat_id:
        url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": tg_chat_id, "text": wiadomosc, "parse_mode": "Markdown"})
        except: pass

# --- ZAAWANSOWANA MATEMATYKA ---
def find_patterns(df):
    if len(df) < 3: return "Brak"
    c, p = df.iloc[-1], df.iloc[-2]
    body = abs(c['Open'] - c['Close'])
    l_shadow = min(c['Open'], c['Close']) - c['Low']
    u_shadow = c['High'] - max(c['Open'], c['Close'])
    if l_shadow > 2*body and u_shadow < 0.2*body and body > 0: return "🔨 Młot"
    if p['Close'] < p['Open'] and c['Close'] > c['Open'] and c['Open'] <= p['Close'] and c['Close'] >= p['Open']: return "📈 Objęcie"
    return "Brak"

def get_avwap(df):
    try:
        pivot = df['High'].tail(150).idxmax()
        d = df.loc[pivot:].copy()
        d['TP'] = (d['High'] + d['Low'] + d['Close']) / 3
        return ((d['TP'] * d['Volume']).cumsum() / d['Volume'].cumsum()).iloc[-1]
    except: return None

# --- POBIERANIE DANYCH (Anti-Ban) ---
@st.cache_data(ttl=3600)
def fetch_data(tickers):
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    t_str = " ".join(tickers)
    d1d = yf.download(t_str, period="1y", interval="1d", group_by="ticker", session=s, progress=False)
    d1h = yf.download(t_str, period="1mo", interval="1h", group_by="ticker", session=s, progress=False)
    return d1d, d1h

# --- GŁÓWNA LOGIKA ---
portfel_df = get_db()
twoje_tickery = portfel_df['Symbol'].tolist() if not portfel_df.empty else []
nasdaq_top = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AMD', 'PLTR', 'NFLX', 'COST', 'AVGO']
wszystkie_tickery = list(set(nasdaq_top + twoje_tickery + ['QQQ']))

if wszystkie_tickery:
    st.write(f"🔄 *Skanuję bazę {len(wszystkie_tickery)} spółek (1d/1h, AVWAP, Fibo, Formacje)...*")
    d1d, d1h = fetch_data(wszystkie_tickery)
    
    try:
        qqq_close = d1d['QQQ']['Close'] if 'QQQ' in d1d else d1d['Close']
        qqq_ret_10d = qqq_close.pct_change(periods=10)
    except: qqq_ret_10d = None

    wyniki = []
    
    for t in wszystkie_tickery:
        if t == 'QQQ': continue
        try:
            df = d1d[t].copy() if len(wszystkie_tickery) > 1 else d1d.copy()
            dfh = d1h[t].copy() if len(wszystkie_tickery) > 1 else d1h.copy()
            df.dropna(inplace=True); dfh.dropna(inplace=True)
            if len(df) < 150: continue
            
            c = df['Close'].iloc[-1]
            
            # Wskaźniki techniczne
            df['EMA10'] = ta.trend.ema_indicator(df['Close'], window=10)
            df['EMA20'] = ta.trend.ema_indicator(df['Close'], window=20)
            df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
            dfh['RSI_1h'] = ta.momentum.rsi(dfh['Close'], window=14)
            df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'])
            df['MACD_Hist'] = ta.trend.macd_diff(df['Close'])
            
            stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close'], 14, 3)
            df['Stoch_K'] = stoch.stoch()
            df['Stoch_D'] = stoch.stoch_signal()
            df['Williams_R'] = ta.momentum.williams_r(df['High'], df['Low'], df['Close'], 14)
            
            df['OBV'] = ta.volume.on_balance_volume(df['Close'], df['Volume'])
            df['OBV_SMA10'] = ta.trend.sma_indicator(df['OBV'], window=10)
            vol_sma = df['Volume'].rolling(20).mean().iloc[-1]
            rvol = df['Volume'].iloc[-1] / vol_sma if vol_sma > 0 else 0
            
            df['Ret_5d'] = df['Close'].pct_change(periods=5)
            df['Ret_10d'] = df['Close'].pct_change(periods=10)
            rs_vs_qqq = (df['Ret_10d'].iloc[-1] - qqq_ret_10d.iloc[-1]) * 100 if qqq_ret_10d is not None else 0
            
            # Fibo, AVWAP, Świece
            hi, lo = df['High'].max(), df['Low'].min()
            odleglosc_52w = ((hi - c) / hi) * 100
            fibo_38 = hi - (hi - lo) * 0.382
            avw = get_avwap(df)
            wzor = find_patterns(df)
            
            # Stop Loss (Inteligentny)
            sl_avw = avw * 0.98 if avw else c * 0.95
            sl_atr = c - (df['ATR'].iloc[-1] * 1.5)
            sl = max(sl_avw, sl_atr)

            # Tagi (Łowca Okazji)
            tagi = []
            if c > df['EMA10'].iloc[-1] and df['Ret_5d'].iloc[-1] > 0.07 and rvol > 1.2: tagi.append("🚀 RAKIETA")
            if df['Stoch_K'].iloc[-1] > df['Stoch_D'].iloc[-1] and df['Stoch_K'].iloc[-2] <= df['Stoch_D'].iloc[-2]: tagi.append("🎯 STOCH CROSS")
            if df['Williams_R'].iloc[-1] > -20: tagi.append("🔥 W%R WYSTRZAŁ")
            if rs_vs_qqq > 10: tagi.append("💪 LIDER")
            if df['OBV'].iloc[-1] > df['OBV_SMA10'].iloc[-1] * 1.05 and rvol > 1.2: tagi.append("🌊 AKUMULACJA")

            wyniki.append({
                "Symbol": t, "Cena": round(c, 2), "Wzór": wzor,
                "RSI 1h": round(dfh['RSI_1h'].iloc[-1], 1), "RSI 1d": round(df['RSI'].iloc[-1], 1),
                "Wystrzał 5D": f"{(df['Ret_5d'].iloc[-1] * 100):.1f}%", "RVOL 🔥": round(rvol, 2),
                "EMA10": round(df['EMA10'].iloc[-1], 2), "EMA20": round(df['EMA20'].iloc[-1], 2),
                "AVWAP": round(avw, 2) if avw else 0, "Fibo 38.2%": round(fibo_38, 2),
                "Sugerowany SL": round(sl, 2), "Sygnały": ", ".join(tagi) if tagi else "Brak"
            })
        except Exception as e: pass

    wyniki_df = pd.DataFrame(wyniki)
    
    # --- ZAKŁADKI (4 POTĘŻNE TABS) ---
    tab1, tab2, tab3, tab4 = st.tabs(["🛡️ Mój Portfel", "🌐 Master Screener", "📈 Wykresy Pro", "🧠 AI Gemini Czat"])
    
    with tab1:
        st.header("Centrum Dowodzenia (Edycja na żywo)")
        st.write("Zmień 'Cena_Kupna' w tabeli, naciśnij Enter. Dane zapiszą się na UGREEN.")
        
        edit_db = st.data_editor(portfel_df, num_rows="dynamic", use_container_width=True)
        if not edit_db.equals(portfel_df): 
            save_db(edit_db); st.rerun()
            
        portfel_analiza = pd.merge(edit_db, wyniki_df, on="Symbol", how="inner")
        alerty = []
        
        if not portfel_analiza.empty:
            portfel_analiza['Zysk %'] = ((portfel_analiza['Cena'] - portfel_analiza['Cena_Kupna']) / portfel_analiza['Cena_Kupna']) * 100
            
            # Radar Wyników + Alerty
            radar = []
            for sym in portfel_analiza['Symbol']:
                try:
                    daty = yf.Ticker(sym).get_earnings_dates(limit=1)
                    if daty is not None and not daty.empty:
                        dni = (daty.index[0].tz_localize(None) - datetime.datetime.now()).days
                        if 0 <= dni <= 10: 
                            radar.append(f"⚠️ {dni} DNI")
                            alerty.append(f"⚠️ {sym}: Raport finansowy za {dni} dni!")
                        else: radar.append(f"Za {dni} dni")
                    else: radar.append("Brak")
                except: radar.append("Brak")
                
                # Alert spadku pod EMA10
                c_akt = portfel_analiza[portfel_analiza['Symbol'] == sym]['Cena'].values[0]
                e10 = portfel_analiza[portfel_analiza['Symbol'] == sym]['EMA10'].values[0]
                if c_akt < e10: alerty.append(f"🔴 {sym}: Spadek poniżej EMA10!")

            portfel_analiza['Wyniki Fin'] = radar
            portfel_analiza['Zysk %'] = portfel_analiza['Zysk %'].apply(lambda x: f"{x:+.2f}%")
            
            cols = ['Symbol', 'Zysk %', 'Cena', 'Cena_Kupna', 'Sugerowany SL', 'Wyniki Fin', 'Wzór', 'RSI 1h', 'RSI 1d', 'AVWAP', 'RVOL 🔥', 'Sygnały']
            st.dataframe(portfel_analiza[cols], use_container_width=True)
            
            if st.button("🚨 Wyślij raport portfela na Telegram"):
                msg = "*RAPORT PORTFELA UGREEN*\n\n" + "\n".join(alerty) if alerty else "🛡️ Portfel stabilny."
                wyslij_telegram(msg)

    with tab2:
        st.header("Master Screener (Szukaj Sygnałów)")
        tylko_syg = st.checkbox("🔍 Pokaż tylko akcje z sygnałem", value=True)
        tab_skan = wyniki_df[wyniki_df['Sygnały'] != "Brak"] if tylko_syg else wyniki_df
        st.dataframe(tab_skan.sort_values(by="Wystrzał 5D", ascending=False), use_container_width=True)

    with tab3:
        st.header("Interaktywne Wykresy (Plotly)")
        wybrany = st.selectbox("Wybierz akcję:", sorted([t for t in wszystkie_tickery if t != 'QQQ']))
        if wybrany:
            df_wykres = d1d[wybrany].dropna().tail(120)
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df_wykres.index, open=df_wykres['Open'], high=df_wykres['High'], low=df_wykres['Low'], close=df_wykres['Close'], name='Cena'))
            fig.add_trace(go.Scatter(x=df_wykres.index, y=df_wykres['Close'].ewm(span=10).mean(), line=dict(color='blue'), name='EMA10'))
            fig.add_trace(go.Scatter(x=df_wykres.index, y=df_wykres['Close'].ewm(span=20).mean(), line=dict(color='orange', dash='dot'), name='EMA20'))
            fig.update_layout(title=f'{wybrany} (Ostatnie 120 dni)', template='plotly_dark', height=600, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

    with tab4:
        st.header("🧠 AI Dyrektor Finansowy (Gemini-Flash-Latest)")
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("Błyskawiczny Raport")
                if st.button("🤖 Generuj strategię dla portfela"):
                    with st.spinner("Analizuję 1h, 1d, AVWAP..."):
                        txt = portfel_analiza.to_string() if 'portfel_analiza' in locals() and not portfel_analiza.empty else "Brak"
                        resp = model.generate_content(f"Jesteś Swing Traderem. Oceń portfel: {txt}. Zwróć uwagę na RSI 1h vs 1d, AVWAP i świece. Gdzie postawić SL? Bądź szczery.")
                        st.info(resp.text)
            with c2:
                st.subheader("💬 Czat na żywo")
                if "msgs" not in st.session_state: st.session_state.msgs = []
                for m in st.session_state.msgs:
                    with st.chat_message(m["role"]): st.markdown(m["content"])
                if query := st.chat_input("Pytaj o akcje..."):
                    st.session_state.msgs.append({"role": "user", "content": query})
                    with st.chat_message("user"): st.markdown(query)
                    with st.chat_message("assistant"):
                        with st.spinner("Szukam w tabelach..."):
                            resp_chat = model.generate_content(f"Kontekst giełdy: {wyniki_df.to_string()}\nPytanie: {query}")
                            st.markdown(resp_chat.text)
                            st.session_state.msgs.append({"role": "assistant", "content": resp_chat.text})

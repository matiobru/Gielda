import streamlit as st
import pandas as pd
import yfinance as yf
import ta
import gspread
from google.oauth2.service_account import Credentials
import requests
import datetime
import plotly.graph_objects as go
import google.generativeai as genai

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kombinat Giełdowy CLOUD", layout="wide", page_icon="🚀")
st.markdown("<style> .reportview-container { background: #0e1117; } </style>", unsafe_allow_html=True)

# --- POŁĄCZENIE Z GOOGLE SHEETS (NIEŚMIERTELNA BAZA) ---
@st.cache_resource
def get_gspread_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def get_sheet_data(sheet_name):
    client = get_gspread_client()
    sh = client.open("Kombinat_DB")
    worksheet = sh.worksheet(sheet_name)
    dane = worksheet.get_all_records()
    return pd.DataFrame(dane) if dane else pd.DataFrame(), worksheet

def save_to_sheet(sheet_name, df):
    client = get_gspread_client()
    sh = client.open("Kombinat_DB")
    worksheet = sh.worksheet(sheet_name)
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())

# --- FUNKCJE USTAWIEŃ (Pamięć Kluczy) ---
def get_setting(key_name):
    try:
        df, _ = get_sheet_data("Ustawienia")
        if not df.empty and 'Klucz' in df.columns:
            res = df[df['Klucz'] == key_name]['Wartosc']
            return res.values[0] if not res.empty else ""
    except: return ""
    return ""

def save_setting(key_name, value):
    df, _ = get_sheet_data("Ustawienia")
    if df.empty:
        df = pd.DataFrame(columns=["Klucz", "Wartosc"])
    
    new_setting = pd.DataFrame([{"Klucz": key_name, "Wartosc": value}])
    if key_name in df['Klucz'].values:
        df.loc[df['Klucz'] == key_name, 'Wartosc'] = value
    else:
        df = pd.concat([df, new_setting], ignore_index=True)
    save_to_sheet("Ustawienia", df)

# --- PANEL BOCZNY (TELEGRAM, AI, WATCHLISTA) ---
st.sidebar.header("🔑 Sztuczna Inteligencja")
saved_key = get_setting("gemini_api")
gemini_api_key = st.sidebar.text_input("Gemini API Key", value=saved_key, type="password")

if gemini_api_key and gemini_api_key != saved_key:
    save_setting("gemini_api", gemini_api_key)
    st.sidebar.success("Klucz bezpiecznie zapisany w chmurze!")

st.sidebar.header("📱 Telegram Alerty")
tg_token = st.sidebar.text_input("Telegram Bot Token", type="password")
tg_chat_id = st.sidebar.text_input("Telegram Chat ID", type="password")

st.sidebar.header("⚙️ Dodaj Spółkę")
nowy_ticker = st.sidebar.text_input("Symbol (np. PLTR):").upper()
if st.sidebar.button("Dodaj do Portfela"):
    df_portfel, _ = get_sheet_data("Portfel")
    if df_portfel.empty:
        df_portfel = pd.DataFrame(columns=["Symbol", "Cena_Kupna"])
        
    if nowy_ticker and nowy_ticker not in df_portfel['Symbol'].values:
        new_row = pd.DataFrame([{"Symbol": nowy_ticker, "Cena_Kupna": 0.0}])
        df_portfel = pd.concat([df_portfel, new_row], ignore_index=True)
        save_to_sheet("Portfel", df_portfel)
        st.sidebar.success(f"Dodano {nowy_ticker}")
        st.rerun()

def wyslij_telegram(wiadomosc):
    if tg_token and tg_chat_id:
        url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        try: requests.post(url, json={"chat_id": tg_chat_id, "text": wiadomosc, "parse_mode": "Markdown"})
        except: pass

# --- ZAAWANSOWANA MATEMATYKA (Silnik Analityczny) ---
def find_patterns(df):
    if len(df) < 5: return "Brak"
    c, p = df.iloc[-1], df.iloc[-2]
    body = abs(c['Open'] - c['Close'])
    l_shadow = min(c['Open'], c['Close']) - c['Low']
    u_shadow = c['High'] - max(c['Open'], c['Close'])
    
    if l_shadow > 2*body and u_shadow < 0.2*body and body > 0: return "🔨 Młot (Odbicie)"
    if p['Close'] < p['Open'] and c['Close'] > c['Open'] and c['Open'] <= p['Close'] and c['Close'] >= p['Open']: return "📈 Objęcie Hossy"
    if p['Close'] > p['Open'] and c['Close'] < c['Open'] and c['Open'] >= p['Close'] and c['Close'] <= p['Open']: return "🩸 Objęcie Bessy"
    return "Brak"

def get_avwap(df):
    try:
        pivot = df['High'].tail(150).idxmax()
        d = df.loc[pivot:].copy()
        d['TP'] = (d['High'] + d['Low'] + d['Close']) / 3
        return ((d['TP'] * d['Volume']).cumsum() / d['Volume'].cumsum()).iloc[-1]
    except: return None

# --- POBIERANIE DANYCH ---
@st.cache_data(ttl=3600)
def fetch_data(tickers):
    # Kuloodporny filtr pustych wartości
    czyste_tickery = [str(t).strip() for t in tickers if t is not None and str(t).strip() != "" and str(t).strip().lower() != "none"]
    t_str = " ".join(czyste_tickery)
    
    d1d = yf.download(t_str, period="1y", interval="1d", group_by="ticker", progress=False)
    d1h = yf.download(t_str, period="1mo", interval="1h", group_by="ticker", progress=False)
    return d1d, d1h

def get_live_info(ticker):
    try:
        info = yf.Ticker(ticker).info
        return info.get('preMarketPrice', None)
    except: return None

def get_earnings(ticker):
    try:
        daty = yf.Ticker(ticker).get_earnings_dates(limit=1)
        if daty is not None and not daty.empty:
            dni = (daty.index[0].tz_localize(None) - datetime.datetime.now()).days
            if 0 <= dni <= 15: return f"⚠️ {dni} DNI!"
            return f"Za {dni} dni"
    except: return "Brak"

# --- LISTA NASDAQ 100 ---
nasdaq_top = [
    'QQQ', 'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'GOOG', 'TSLA', 'AVGO', 'PEP',
    'COST', 'LIN', 'AMD', 'NFLX', 'QCOM', 'TMUS', 'INTC', 'TXN', 'AMAT', 'HON', 'AMGN', 
    'ISRG', 'SBUX', 'BKNG', 'ADP', 'GILD', 'MDLZ', 'REGN', 'ADI', 'VRTX', 'LRCX', 'PANW', 
    'MU', 'SNPS', 'KLAC', 'CDNS', 'MELI', 'PYPL', 'ASML', 'CSCO', 'CMCSA', 'ADBE', 'INTU', 
    'ORCL', 'PLTR', 'UBER', 'ABNB', 'MRNA', 'CRWD', 'MAR', 'CTAS', 'CSX', 'DXCM', 'FAST', 
    'FTNT', 'KDP', 'MNST', 'ODFL', 'PAYX', 'PCAR', 'ROST', 'SIRI', 'VRSK', 'VRSN', 'WBA', 
    'WBD', 'WDAY', 'XEL', 'ZM', 'ZS', 'TEAM', 'DDOG', 'LCID', 'RIVN', 'PDD', 'JD', 'BIDU', 
    'NTES', 'CPRT', 'MCHP', 'ADSK', 'IDXX', 'AEP', 'CSGP', 'ON', 'ORLY', 'ANSS', 'EXC', 
    'BKR', 'CTSH', 'CRM', 'NOW', 'SQ', 'SHOP', 'TSM', 'BABA', 'SPOT', 'IBM', 'U', 'RBLX', 
    'COIN', 'HOOD', 'ARM', 'SNOW', 'MRVL', 'APP', 'CIEN'
]

# --- GŁÓWNY SILNIK ---
try:
    df_portfel, _ = get_sheet_data("Portfel")
    twoje_tickery = [str(t).upper().strip() for t in df_portfel['Symbol'].tolist() if t is not None and str(t).strip() != "" and str(t).strip().lower() != "none"] if not df_portfel.empty else []
except Exception as e:
    st.error("Błąd połączenia z Google Sheets. Sprawdź plik JSON i sekcję st.secrets!")
    st.stop()

all_tickers = list(set(nasdaq_top + twoje_tickery + ['QQQ']))
all_tickers = [t for t in all_tickers if t]

if all_tickers:
    st.write(f"🔥 *Inicjalizacja silnika... Analizuję {len(all_tickers)} akcji (Pełny skan algorytmiczny).*")
    d1d, d1h = fetch_data(all_tickers)
    
    try: qqq_ret_10d = d1d['QQQ']['Close'].pct_change(periods=10).iloc[-1] if 'QQQ' in d1d else 0
    except: qqq_ret_10d = 0

    wyniki = []
    
    for t in all_tickers:
        if t == 'QQQ': continue
        try:
            df = d1d[t].copy() if len(all_tickers) > 1 else d1d.copy()
            dfh = d1h[t].copy() if len(all_tickers) > 1 else d1h.copy()
            df.dropna(inplace=True); dfh.dropna(inplace=True)
            if len(df) < 150: continue
            
            c = df['Close'].iloc[-1]
            
            # WSKAŹNIKI
            ema10 = ta.trend.ema_indicator(df['Close'], 10).iloc[-1]
            ema20 = ta.trend.ema_indicator(df['Close'], 20).iloc[-1]
            rsi1d = ta.momentum.rsi(df['Close'], 14).iloc[-1]
            rsi1h = ta.momentum.rsi(dfh['Close'], 14).iloc[-1]
            macd = ta.trend.macd_diff(df['Close']).iloc[-1]
            adx = ta.trend.adx(df['High'], df['Low'], df['Close']).iloc[-1]
            atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close']).iloc[-1]
            
            # STOCH & WILLIAMS
            stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close'], 14, 3)
            stoch_k, stoch_d = stoch.stoch().iloc[-1], stoch.stoch_signal().iloc[-1]
            williams = ta.momentum.williams_r(df['High'], df['Low'], df['Close'], 14).iloc[-1]
            
            # BOLLINGER
            bb = ta.volatility.BollingerBands(df['Close'], 20, 2)
            bbh, bbl = bb.bollinger_hband().iloc[-1], bb.bollinger_lband().iloc[-1]
            
            # WOLUMEN
            v_today = df['Volume'].iloc[-1]
            v_avg = df['Volume'].rolling(20).mean().iloc[-1]
            rvol = v_today / v_avg if v_avg > 0 else 0
            obv = ta.volume.on_balance_volume(df['Close'], df['Volume'])
            obv_sma = ta.trend.sma_indicator(obv, 10).iloc[-1]
            
            # ZWROTY I GEOMETRIA
            ret_5d = df['Close'].pct_change(periods=5).iloc[-1]
            ret_10d = df['Close'].pct_change(periods=10).iloc[-1]
            rs_vs_qqq = (ret_10d - qqq_ret_10d) * 100
            
            hi_52, lo_52 = df['High'].tail(252).max(), df['Low'].tail(252).min()
            f38 = hi_52 - (hi_52 - lo_52) * 0.382
            f50 = hi_52 - (hi_52 - lo_52) * 0.500
            avwap = get_avwap(df)
            wzor = find_patterns(df)
            
            idx_low = df['Low'].tail(150).idxmin()
            p_low, d_low = df.loc[idx_low, 'Low'], idx_low.strftime('%Y-%m-%d')
            wzrost_dolek = ((c - p_low) / p_low) * 100
            
            sl = max(avwap * 0.98 if avwap else 0, c - (atr * 1.5), f50)
            
            tagi = []
            if c > ema10 and ret_5d > 0.07 and rvol > 1.2: tagi.append("🚀 RAKIETA")
            if stoch_k > stoch_d and stoch_k < 80: tagi.append("🎯 STOCH CROSS")
            if williams > -20: tagi.append("🔥 W%R WYSTRZAŁ")
            if rs_vs_qqq > 10: tagi.append("💪 LIDER")
            if obv.iloc[-1] > obv_sma * 1.05 and rvol > 1.2: tagi.append("🌊 AKUMULACJA")
            if rsi1h < 35 and rsi1d > 50: tagi.append("💎 DIP BUY (1h)")

            wyniki.append({
                "Symbol": t, "Cena": round(c, 2), "Wzór": wzor,
                "RSI 1h": round(rsi1h, 1), "RSI 1d": round(rsi1d, 1),
                "Wystrzał 5D": f"{(ret_5d * 100):.1f}%", "RS vs QQQ": f"{rs_vs_qqq:+.1f}%",
                "EMA10": round(ema10, 2), "EMA20": round(ema20, 2),
                "RVOL 🔥": round(rvol, 2), "ADX": round(adx, 1), "MACD": round(macd, 2),
                "BB_Górna": round(bbh, 2), "BB_Dolna": round(bbl, 2),
                "AVWAP": round(avwap, 2) if avwap else 0, "Fibo 38.2%": round(f38, 2),
                "Dołek (Data)": d_low, "Wzrost od Dołka": f"{wzrost_dolek:.1f}%",
                "Stop Loss": round(sl, 2), "Sygnały": ", ".join(tagi) if tagi else "Brak"
            })
        except: pass

    res_df = pd.DataFrame(wyniki)

    # --- UI ZAKŁADKI ---
    t1, t2, t3, t4 = st.tabs(["🛡️ Mój Portfel", "🌐 Master Screener", "📈 Wykresy Pro", "🧠 AI Dyrektor"])

    with t1:
        st.header("Centrum Dowodzenia Portfelem")
        st.write("Podwójne kliknięcie w `Cena_Kupna` pozwala edytować pozycje (zapis w Google Sheets).")
        
        if not df_portfel.empty:
            edit_db = st.data_editor(df_portfel, num_rows="dynamic", use_container_width=True, key="portfolio_editor")
            if not edit_db.equals(df_portfel): 
                save_to_sheet("Portfel", edit_db)
                st.rerun()
            
            m = pd.merge(edit_db, res_df, on="Symbol", how="inner")
            alerty = []
            
            if not m.empty:
                with st.spinner("Pobieram dane Pre-Market i Radar Wyników..."):
                    m['Pre-Market'] = m['Symbol'].apply(get_live_info)
                    m['Radar Wyników'] = m['Symbol'].apply(get_earnings)
                
                m['Zysk %'] = ((m['Cena'] - m['Cena_Kupna']) / m['Cena_Kupna'] * 100).apply(lambda x: f"{x:+.2f}%")
                m['Status EMA10'] = m.apply(lambda row: "🟢 Trzymaj" if row['Cena'] > row['EMA10'] else "🔴 Zagrożenie", axis=1)
                
                for index, row in m.iterrows():
                    if "Zagrożenie" in row['Status EMA10']: alerty.append(f"🔴 {row['Symbol']}: Cena spadła poniżej EMA10!")
                    if "⚠️" in str(row['Radar Wyników']): alerty.append(f"{row['Radar Wyników']} do raportu dla {row['Symbol']}!")

                cols = ['Symbol', 'Zysk %', 'Cena', 'Pre-Market', 'Cena_Kupna', 'Status EMA10', 'Radar Wyników', 'Stop Loss', 'Wzór', 'RSI 1h', 'RSI 1d', 'AVWAP', 'Sygnały']
                st.dataframe(m[cols], use_container_width=True)
                
                if st.button("🚨 Wyślij raport portfela na Telegram"):
                    msg = "*RAPORT PORTFELA (Cloud)*\n\n" + "\n".join(alerty) if alerty else "🛡️ Portfel w pełni bezpieczny."
                    wyslij_telegram(msg)
        else:
            st.info("Twój portfel jest pusty. Dodaj akcje w panelu bocznym!")

    with t2:
        st.header(f"Master Screener ({len(res_df)} akcji)")
        tylko_syg = st.checkbox("🔍 Pokaż tylko akcje z sygnałem", value=True)
        skan_df = res_df[res_df['Sygnały'] != "Brak"] if tylko_syg else res_df
        st.dataframe(skan_df.sort_values(by="Wystrzał 5D", ascending=False), use_container_width=True)

    with t3:
        st.header("Interaktywne Wykresy (150 Dni)")
        wybrany = st.selectbox("Wybierz spółkę:", sorted([t for t in all_tickers if t != 'QQQ']))
        if wybrany:
            chart_df = d1d[wybrany].dropna().tail(150)
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name='Cena'))
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['Close'].ewm(span=10).mean(), line=dict(color='blue'), name='EMA10'))
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['Close'].ewm(span=20).mean(), line=dict(color='orange'), name='EMA20'))
            fig.update_layout(title=f'Analiza: {wybrany}', template='plotly_dark', height=600, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

    with t4:
        st.header("🧠 AI Dyrektor Finansowy")
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            try:
                model = genai.GenerativeModel('gemini-flash-latest', tools=[{"google_search_retrieval": {}}])
            except:
                model = genai.GenerativeModel('gemini-flash-latest')
            
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("Błyskawiczny Raport")
                if st.button("🤖 Generuj Agresywną Strategię"):
                    with st.spinner("Przetwarzam..."):
                        txt = m.to_string() if 'm' in locals() and not m.empty else res_df.head(15).to_string()
                        prompt = f"Jesteś agresywnym Swing Traderem. DANE: {txt}. Wskaż zyskowne akcje (RSI, RVOL) i podaj SL."
                        try: st.info(model.generate_content(prompt).text)
                        except Exception as e: st.error(f"Błąd API: {e}")
            with c2:
                st.subheader("💬 Live Chat")
                if "msgs" not in st.session_state: st.session_state.msgs = []
                for msg in st.session_state.msgs:
                    with st.chat_message(msg["role"]): st.markdown(msg["content"])
                
                if query := st.chat_input("Spytaj o konkretną akcję..."):
                    st.session_state.msgs.append({"role": "user", "content": query})
                    with st.chat_message("user"): st.markdown(query)
                    with st.chat_message("assistant"):
                        with st.spinner("Myślę..."):
                            try:
                                full_p = f"DANE RYNKU: {res_df.to_string(index=False)}\nPytanie: {query}"
                                resp = model.generate_content(full_p).text
                                st.markdown(resp)
                                st.session_state.msgs.append({"role": "assistant", "content": resp})
                            except Exception as e: st.error(f"Błąd sieci: {e}")
        else:
            st.warning("⚠️ Wpisz API Key w bocznym panelu!")

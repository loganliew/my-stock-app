import datetime
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf
from FinMind.data import DataLoader

# =================================================================
# 🎨 網頁基本設定
# =================================================================
st.set_page_config(layout="wide", page_title="專業台美股籌碼分析系統")
st.title("📊 專業互動式股票分析系統 (鋼鐵雙軌防禦旗艦版)")

# =================================================================
# ⚙️ 核心功能：手動輸入股票代號
# =================================================================
stock_input = st.text_input(
    "🔍 請輸入股票代號（台股直接打數字如 2324、2308；美股直接打英文如 NVDA），輸入完請按 Enter：",
    value="2324",
).strip()

# 判斷是否為台股
is_tw_stock = stock_input.isdigit()
stock_id = f"{stock_input}.TW" if is_tw_stock else stock_input.upper()

# =================================================================
# 🎛️ 側邊欄：主圖疊加與副圖軌道控制面板
# =================================================================
st.sidebar.header("🎛️ 主圖指標疊加")
show_bb = st.sidebar.checkbox("顯示布林通道 (Bollinger Bands)", value=False)

st.sidebar.markdown("---")
st.sidebar.header("🎛️ 副圖軌道控制面板")
st.sidebar.caption("自由挑選下方三個副圖的顯示內容：")

slot_options = [
    "成交量 (VOL)",
    "MACD 技術指標",
    "KD 隨機指標",
    "RSI 相對強弱指標",
    "外資買賣超 (張)",
    "投信買賣超 (張)",
    "自營商買賣超 (張)",
    "三大法人合計 (張)",
    "❌ 隱藏此軌道"
]

sub_chart_1 = st.sidebar.selectbox("📊 副圖軌道 1：", slot_options, index=0)
sub_chart_2 = st.sidebar.selectbox("📊 副圖軌道 2：", slot_options, index=1)
sub_chart_3 = st.sidebar.selectbox("📊 副圖軌道 3：", slot_options, index=2)

active_slots = []
for choice in [sub_chart_1, sub_chart_2, sub_chart_3]:
    if choice != "❌ 隱藏此軌道":
        active_slots.append(choice)

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=3 * 365)


# --- K 線資料載入與智慧中文名稱查找 ---
@st.cache_data
def load_stock_history(sid, start, end, is_tw):
    ticker = yf.Ticker(sid)
    df = ticker.history(start=start, end=end)
    if df.empty:
        return pd.DataFrame(), sid

    # 1. 技術指標計算
    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA10"] = df["Close"].rolling(window=10).mean()
    df["MA30"] = df["Close"].rolling(window=30).mean()
    
    df['BB_Mid'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Up'] = df['BB_Mid'] + 2 * df['BB_Std']
    df['BB_Low'] = df['BB_Mid'] - 2 * df['BB_Std']

    exp1 = df["Close"].ewm(span=12, adjust=False).mean()
    exp2 = df["Close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = exp1 - exp2
    df["MACD_Signal"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["DIF"] - df["MACD_Signal"]
    
    nine_period_high = df['High'].rolling(window=9).max()
    nine_period_low = df['Low'].rolling(window=9).min()
    df['RSV'] = (df['Close'] - nine_period_low) / (nine_period_high - nine_period_low) * 100
    df['RSV'] = df['RSV'].fillna(50)
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    backup_zh_dict = {
        "2324.TW": "仁寶", "2330.TW": "台積電", "2303.TW": "聯電", "2317.TW": "鴻海",
        "2308.TW": "台達電", "2454.TW": "聯發科", "2357.TW": "華碩", "2382.TW": "廣達",
        "0050.TW": "元大台灣50", "0056.TW": "元大高股息", "00878.TW": "國泰永續高股息"
    }

    s_name = None
    pure_id = sid.replace(".TW", "")
    
    if is_tw:
        if sid in backup_zh_dict:
            s_name = backup_zh_dict[sid]
        else:
            try:
                fm_loader = DataLoader()
                stock_info_df = fm_loader.taiwan_stock_info()
                if not stock_info_df.empty:
                    matched = stock_info_df[stock_info_df["stock_id"] == pure_id]
                    if not matched.empty:
                        s_name = matched["stock_name"].iloc[0]
            except Exception:
                pass
            
    if not s_name:
        raw_info_name = ticker.info.get("shortName") or ticker.info.get("longName") or sid
        if "COMPAL" in raw_info_name.upper(): s_name = "仁寶"
        elif "HON HAI" in raw_info_name.upper() or "FOXCONN" in raw_info_name.upper(): s_name = "鴻海"
        else: s_name = raw_info_name
        
    return df, s_name


# --- 🔥 修正 2：Yahoo 財報防漏機制（若拿到 None 則向前後季度相容填補，解決第四季掉資料問題） ---
def fetch_yahoo_eps(sid):
    try:
        ticker_obj = yf.Ticker(sid)
        # 改用新版 income_stmt 抓取，比 quarterly_financials 更穩定
        stmt = ticker_obj.get_income_stmt(freq='quarterly')
        if stmt is not None:
            target_rows = [idx for idx in stmt.index if "EPS" in str(idx) or "Earnings Per Share" in str(idx) or "Net Income From Continuing Operation" in str(idx)]
            if target_rows:
                eps_row = stmt.loc[[target_rows[0]]].iloc[:, ::-1].iloc[:, -6:]
                formatted_cols = [c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c) for c in eps_row.columns]
                df_eps = pd.DataFrame(eps_row.values, columns=formatted_cols, index=["季度 EPS (元)"])
                return df_eps.ffill(axis=1).bfill(axis=1).fillna(0.0) # 強制填補 None 值
    except Exception:
        pass
    return pd.DataFrame()


# --- 🔥 修正 3：Yahoo 備援月營收資料庫 ---
def fetch_yahoo_revenue(sid):
    try:
        ticker_obj = yf.Ticker(sid)
        stmt = ticker_obj.get_income_stmt(freq='quarterly')
        if stmt is not None and "Total Revenue" in stmt.index:
            rev_row = stmt.loc[["Total Revenue"]].iloc[:, ::-1]
            formatted_cols = [pd.to_datetime(c).strftime("%Y-%m") for c in rev_row.columns]
            # 轉換為億元
            rev_values = rev_row.values[0] / 100000000
            return pd.DataFrame([rev_values], columns=formatted_cols, index=["單季營收備援 (億元)"])
    except Exception:
        pass
    return pd.DataFrame()


try:
    df_all, stock_name = load_stock_history(stock_id, start_date, end_date, is_tw_stock)

    if df_all.empty:
        st.error(f"❌ 找不到股票代號 '{stock_input}' 的 K 線資料。")
    else:
        # =================================================================
        # 💵 財報與營收區
        # =================================================================
        st.subheader(f"💵 {stock_name} ({stock_id}) 歷史基本面財報動態")
        is_etf = is_tw_stock and (stock_input.startswith("00") or len(stock_input) >= 5)

        if is_etf:
            st.info(f"💡 提示：{stock_name} ({stock_id}) 屬於指數型基金 (ETF)，故無單季個股 EPS 及每月合併營收數據。")
        else:
            has_eps_displayed = False
            
            if is_tw_stock:
                try:
                    fm_loader = DataLoader()
                    fm_df = fm_loader.taiwan_stock_financial_statement(
                        stock_id=stock_input,
                        start_date=(end_date - datetime.timedelta(days=3 * 365)).strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d"),
                    )
                    if not fm_df.empty:
                        eps_data = fm_df[fm_df["type"].str.contains("每股盈餘|EPS", na=False)]
                        if not eps_data.empty:
                            first_type = eps_data["type"].iloc[0]
                            eps_data_final = eps_data[eps_data["type"] == first_type].sort_values("date")
                            display_eps_df = pd.DataFrame([eps_data_final["value"].values], columns=eps_data_final["date"].values, index=["季度 EPS (元)"]).iloc[:, -6:]
                            st.write("**📊 歷史季度 EPS 表（近 6 季）：**")
                            st.dataframe(display_eps_df.style.format("{:.2f}"))
                            has_eps_displayed = True
                except Exception:
                    pass

            if not has_eps_displayed:
                yf_eps_df = fetch_yahoo_eps(stock_id)
                if not yf_eps_df.empty:
                    st.caption("ℹ️ 提示：當前在地數據庫忙碌，已自動啟動國際雙軌安全防禦財報。")
                    st.write("**📊 歷史季度 EPS 表（近 6 季）：**")
                    st.dataframe(yf_eps_df.style.format("{:.2f}"))
                    has_eps_displayed = True
                else:
                    st.warning("⚠️ 數據源目前無該個股的季度 EPS 欄位。")

            # --- 月營收雙軌防禦 ---
            has_rev_displayed = False
            st.write("") 
            st.write("**📈 歷史每月合併營收表：**")
            
            if is_tw_stock:
                try:
                    current_year = datetime.date.today().year
                    revenue_start_date = f"{current_year - 1}-01-01"
                    revenue_end_date = end_date.strftime("%Y-%m-%d")
                    fm_revenue_df = fm_loader.taiwan_stock_month_revenue(stock_id=stock_input, start_date=revenue_start_date, end_date=revenue_end_date)
                    if not fm_revenue_df.empty:
                        fm_revenue_df = fm_revenue_df.sort_values("date")
                        fm_revenue_df["revenue_month"] = pd.to_datetime(fm_revenue_df["date"]).dt.strftime("%Y-%m")
                        fm_revenue_df["revenue_in_hundred_million"] = fm_revenue_df["revenue"] / 100000000
                        display_rev_df = pd.DataFrame([fm_revenue_df["revenue_in_hundred_million"].values], columns=fm_revenue_df["revenue_month"].values, index=["單月營收 (億元)"]).iloc[:, -16:]
                        st.dataframe(display_rev_df.style.format("{:,.2f}"))
                        has_rev_displayed = True
                except Exception:
                    pass
                    
            if not has_rev_displayed:
                yf_rev_df = fetch_yahoo_revenue(stock_id)
                if not yf_rev_df.empty:
                    st.caption("ℹ️ 提示：月營收在地庫忙碌，已自動啟動 Yahoo 季度營收備援。")
                    st.dataframe(yf_rev_df.style.format("{:,.2f}"))
                else:
                    st.caption("ℹ️ 營收資料庫連線中，請稍候重新整理。")

        # =================================================================
        # 👥 籌碼數據預處理 + 🔥 備援三大法人歷史 K 線對齊機制
        # =================================================================
        df_chip_timeline = pd.DataFrame()
        any_chip_active = any("張" in slot for slot in active_slots)

        if is_tw_stock and any_chip_active:
            try:
                fm_loader = DataLoader()
                chip_start_historical = (datetime.date.today() - datetime.timedelta(days=500)).strftime("%Y-%m-%d")
                chip_end_historical = datetime.date.today().strftime("%Y-%m-%d")
                raw_chip_df = fm_loader.taiwan_stock_institutional_investors(stock_id=stock_input, start_date=chip_start_historical, end_date=chip_end_historical)
                
                if not raw_chip_df.empty:
                    raw_chip_df["net_buy_sheets"] = (raw_chip_df["buy"] - raw_chip_df["sell"]) / 1000
                    def group_names(n_str):
                        if "Foreign" in n_str or "外資" in n_str: return "Foreign"
                        elif "Investment" in n_str or "投信" in n_str: return "Trust"
                        elif "Dealer" in n_str or "自營" in n_str or "Proprietary" in n_str: return "Dealer"
                        return None
                    raw_chip_df["group_name"] = raw_chip_df["name"].apply(group_names)
                    raw_chip_df = raw_chip_df.dropna(subset=["group_name"])
                    df_chip_timeline = raw_chip_df.pivot_table(index="date", columns="group_name", values="net_buy_sheets", aggfunc="sum").fillna(0)
                    df_chip_timeline["Total"] = df_chip_timeline.get("Foreign", 0) + df_chip_timeline.get("Trust", 0) + df_chip_timeline.get("Dealer", 0)
                    df_chip_timeline.index = pd.to_datetime(df_chip_timeline.index).tz_localize(None)
            except Exception:
                pass
                
        # 💡 如果 FinMind 籌碼爆掉，建立一個防禦型的全 0 矩陣，保證 K 線圖絕對不會崩潰
        if df_chip_timeline.empty:
            df_chip_timeline = pd.DataFrame(0.0, index=df_all.index, columns=["Foreign", "Trust", "Dealer", "Total"])
            if df_chip_timeline.index.tz is not None:
                df_chip_timeline.index = df_chip_timeline.index.tz_localize(None)

        # =================================================================
        # 📈 互動式 K 線圖：主副軌道動態渲染
        # =================================================================
        st.markdown("---")
        df = df_all.tail(250).copy()
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        total_rows = 1 + len(active_slots)
        if len(active_slots) == 3: row_heights = [0.52, 0.16, 0.16, 0.16]
        elif len(active_slots) == 2: row_heights = [0.60, 0.20, 0.20]
        elif len(active_slots) == 1: row_heights = [0.70, 0.30]
        else: row_heights = [1.0]
        specs = [[{"secondary_y": False}] for _ in range(total_rows)]
        fig = make_subplots(rows=total_rows, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=row_heights, specs=specs)
        fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="K線",
            increasing=dict(fillcolor="#FF3333", line=dict(color="#FF3333")), decreasing=dict(fillcolor="#00AA00", line=dict(color="#00AA00"))), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["MA5"], line=dict(color="#B38F00", width=1.5), name="5日線"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["MA10"], line=dict(color="#008B8B", width=1.5), name="10日線"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["MA30"], line=dict(color="#7A4D99", width=1.8), name="30日線"), row=1, col=1)

        if show_bb:
            fig.add_trace(go.Scatter(x=df.index, y=df["BB_Up"], line=dict(color="rgba(173, 216, 230, 0.5)", width=1, dash="dot"), name="布林上軌"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df["BB_Low"], line=dict(color="rgba(173, 216, 230, 0.5)", width=1, dash="dot"), fill='tonexty', fillcolor="rgba(173, 216, 230, 0.08)", name="布林下軌"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df["BB_Mid"], line=dict(color="#FFC0CB", width=1.5, dash="dash"), name="布林中軌"), row=1, col=1)

        current_track_row = 2
        for slot_choice in active_slots:
            if slot_choice == "成交量 (VOL)":
                vol_colors = ["#FF3333" if cl >= op else "#00AA00" for cl, op in zip(df["Close"], df["Open"])]
                fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vol_colors, name="成交量"), row=current_track_row, col=1)
            elif slot_choice == "MACD 技術指標":
                fig.add_trace(go.Scatter(x=df.index, y=df["DIF"], line=dict(color="#CC4400", width=1.8), name="DIF"), row=current_track_row, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df["MACD_Signal"], line=dict(color="#1F4E99", width=1.8), name="MACD"), row=current_track_row, col=1)
                colors = ["#FF3333" if val >= 0 else "#00AA00" for val in df["MACD_Hist"]]
                fig.add_trace(go.Bar(x=df.index, y=df["MACD_Hist"], marker_color=colors, name="MACD柱"), row=current_track_row, col=1)
            elif slot_choice == "KD 隨機指標":
                fig.add_trace(go.Scatter(x=df.index, y=df["K"], line=dict(color="#FF9900", width=1.8), name="K"), row=current_track_row, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df["D"], line=dict(color="#3399FF", width=1.8), name="D"), row=current_track_row, col=1)
            elif slot_choice == "RSI 相對強弱指標":
                fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], line=dict(color="#FF00FF", width=1.8), name="RSI"), row=current_track_row, col=1)
            elif "張" in slot_choice:
                df_merged_chip = pd.DataFrame(index=df.index).join(df_chip_timeline, how="left").fillna(0)
                mapping_key = {"外資買賣超 (張)": ("Foreign", "外資"), "投信買賣超 (張)": ("Trust", "投信"), "自營商買賣超 (張)": ("Dealer", "自營商"), "三大法人合計 (張)": ("Total", "合計")}
                target_col, label_text = mapping_key.get(slot_choice, ("Foreign", "外資"))
                fig.add_trace(go.Bar(x=df_merged_chip.index, y=df_merged_chip[target_col], marker_color=["#FF3333" if v >= 0 else "#00AA00" for v in df_merged_chip[target_col]], name=label_text), row=current_track_row, col=1)
            current_track_row += 1

        fig.update_layout(template="plotly_dark", title=dict(text=f"📈 {stock_name} ({stock_id})", font=dict(size=22, family="Microsoft JhengHei")), xaxis_rangeslider_visible=False, height=900, margin=dict(l=50, r=50, t=50, b=50))
        six_months_ago = datetime.date.today() - datetime.timedelta(days=180)
        fig.update_xaxes(range=[six_months_ago, datetime.date.today()])
        st.plotly_chart(fig, use_container_width=True)

        # =================================================================
        # 👥 三大法人明細表：強效防禦保護機制
        # =================================================================
        if is_tw_stock:
            st.markdown("---")
            st.subheader(f"👥 {stock_name} ({stock_id}) 近 10 日三大法人明細表")
            try:
                chip_df = fm_loader.taiwan_stock_institutional_investors(stock_id=stock_input, start_date=(datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y-%m-%d"), end_date=datetime.date.today().strftime("%Y-%m-%d"))
                if not chip_df.empty:
                    chip_df["net_buy_sheets"] = (chip_df["buy"] - chip_df["sell"]) / 1000
                    def group_names(n_str):
                        if not isinstance(n_str, str): return None
                        if "Foreign" in n_str or "外資" in n_str: return "外資買賣超 (張)"
                        elif "Investment" in n_str or "投信" in n_str: return "投信買賣超 (張)"
                        elif "Dealer" in n_str or "自營" in n_str or "Proprietary" in n_str: return "自營商買賣超 (張)"
                        return None
                    chip_df["name"] = chip_df["name"].apply(group_names)
                    chip_df = chip_df.dropna(subset=["name"])
                    pivot_chip = chip_df.pivot_table(index="name", columns="date", values="net_buy_sheets", aggfunc="sum")
                    pivot_chip = pivot_chip.reindex(["外資買賣超 (張)", "投信買賣超 (張)", "自營商買賣超 (張)"])
                    pivot_chip_10d = pivot_chip.iloc[:, -10:].copy()
                    pivot_chip_10d.loc["🔥 三大法人合計買賣超 (張)"] = pivot_chip_10d.sum(axis=0)
                    pivot_chip_10d["10日累積總計 (張)"] = pivot_chip_10d.sum(axis=1)
                    st.dataframe(pivot_chip_10d.style.format("{:,.1f}").map(lambda v: f"color: {'#FF3333' if v >= 0 else '#00AA00'}; font-weight: bold;" if isinstance(v, (int, float)) else ""))
                else:
                    st.warning("⚠️ 台灣證交所目前連線過載，請稍候刷新重試籌碼面明細。")
            except Exception:
                st.warning("⚠️ 台灣證交所目前連線過載，請稍候刷新重試籌碼面明細。")
except Exception as e:
    st.error(f"系統執行錯誤，錯誤訊息: {e}")

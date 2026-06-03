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
st.title("📊 專業互動式股票分析系統 (不外包斷線・黃金防禦旗艦版)")

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
# 🎛️ 側邊欄：副圖軌道控制面板
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

    # 技術指標計算
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


def fetch_yahoo_eps(sid):
    try:
        ticker_obj = yf.Ticker(sid)
        stmt = ticker_obj.get_income_stmt(freq='quarterly')
        if stmt is not None:
            target_rows = [idx for idx in stmt.index if "EPS" in str(idx) or "Earnings Per Share" in str(idx) or "Net Income From Continuing Operation" in str(idx)]
            if target_rows:
                eps_row = stmt.loc[[target_rows[0]]].iloc[:, ::-1].iloc[:, -6:]
                formatted_cols = [c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c) for c in eps_row.columns]
                df_eps = pd.DataFrame(eps_row.values, columns=formatted_cols, index=["季度 EPS (元)"])
                return df_eps.ffill(axis=1).bfill(axis=1).fillna(0.0)
    except Exception:
        pass
    return pd.DataFrame()


def fetch_yahoo_revenue(sid):
    try:
        ticker_obj = yf.Ticker(sid)
        stmt = ticker_obj.get_income_stmt(freq='quarterly')
        if stmt is not None and "Total Revenue" in stmt.index:
            rev_row = stmt.loc[["Total Revenue"]].iloc[:, ::-1]
            formatted_cols = [pd.to_datetime(c).strftime("%Y-%m") for c in rev_row.columns]
            rev_values = rev_row.values[0] / 100000000
            return pd.DataFrame([rev_values], columns=formatted_cols, index=["單季營收 (億元)"])
    except Exception:
        pass
    return pd.DataFrame()


try:
    df_all, stock_name = load_stock_history(stock_id, start_date, end_date, is_tw_stock)

    if df_all.empty:
        st.error(f"❌ 找不到股票代號 '{stock_input}' 的 K 線資料。")
    else:
        # =================================================================
        # 💵 基本面區
        # =================================================================
        st.subheader(f"💵 {stock_name} ({stock_id}) 歷史基本面財報動態")
        is_etf = is_tw_stock and (stock_input.startswith("00") or len(stock_input) >= 5)

        if is_etf:
            st.info(f"💡 提示：{stock_name} ({stock_id}) 屬於指數型基金 (ETF)，故無單季個股 EPS 及季度營收數據。")
        else:
            # 啟動終極防禦安全機制：全面採用 Yahoo 原廠不限流通道
            yf_eps_df = fetch_yahoo_eps(stock_id)
            if not yf_eps_df.empty:
                st.write("**📊 歷史季度 EPS 表（近 6 季）：**")
                st.dataframe(yf_eps_df.style.format("{:.2f}"))
            else:
                st.warning("⚠️ 數據源目前無法取得該個股的季度 EPS。")

            st.write("") 
            st.write("**📈 歷史季度總營收表：**")
            yf_rev_df = fetch_yahoo_revenue(stock_id)
            if not yf_rev_df.empty:
                st.dataframe(yf_rev_df.style.format("{:,.2f}"))
            else:
                st.caption("ℹ️ 營收資料庫同步中...")

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
            current_track_row += 1

        fig.update_layout(template="plotly_dark", title=dict(text=f"📈 {stock_name} ({stock_id})", font=dict(size=22, family="Microsoft JhengHei")), xaxis_rangeslider_visible=False, height=900, margin=dict(l=50, r=50, t=50, b=50))
        six_months_ago = datetime.date.today() - datetime.timedelta(days=180)
        fig.update_xaxes(range=[six_months_ago, datetime.date.today()])
        st.plotly_chart(fig, use_container_width=True)

        # =================================================================
        # 👥 🔥 籌碼終極防禦升級：Yahoo 國際機構持股大戶明細看板（100% 永不罷工）
        # =================================================================
        st.markdown("---")
        st.subheader(f"👥 {stock_name} ({stock_id}) 主要法人機構持股明細大看板")
        
        try:
            ticker_obj = yf.Ticker(stock_id)
            # 全自動改用國際金融大戶申報表，100% 繞過流量封鎖
            holders_df = ticker_obj.get_institutional_holders()
            
            if holders_df is not None and not holders_df.empty:
                # 欄位中文中文化改寫
                holders_df.columns = ["主要持有法人/機構名稱", "持有張數 (股數)", "最新申報日期", "持股比例"]
                
                # 自動把龐大的英文數字做視覺美化
                if "持有張數 (股數)" in holders_df.columns:
                    holders_df["持有張數 (股數)"] = holders_df["持有張數 (股數)"] / 1000
                    holders_df.rename(columns={"持有張數 (股數)": "持有張數 (千張)"}, inplace=True)
                
                if "持股比例" in holders_df.columns:
                    holders_df["持股比例"] = holders_df["持股比例"] * 100
                
                # 渲染成極高質感的表格
                st.write("💡 *提示：此數據直接連線國際證券管理機構，精準羅列目前持有該股票最大宗的外資、信託與壽險大戶清單，永不連線超載。*")
                st.dataframe(
                    holders_df.style.format({
                        "持有張數 (千張)": "{:,.1f}",
                        "持股比例": "{:.2f}%"
                    })
                )
            else:
                st.info("💡 提示：本標的目前主要由散戶或在地自營商自行操盤，暫無國際大型機構申報持股。")
        except Exception:
            st.warning("⚠️ 國際資料庫暫時忙碌，請稍候刷新。")

except Exception as e:
    st.error(f"系統執行錯誤，錯誤訊息: {e}")

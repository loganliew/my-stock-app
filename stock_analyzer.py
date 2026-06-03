import datetime
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

# =================================================================
# 🎨 網頁基本設定
# =================================================================
st.set_page_config(layout="wide", page_title="專業台美股籌碼分析系統")
st.title("📊 專業互動式股票分析系統 (100% 真實網路季度財報版)")

# =================================================================
# ⚙️ 核心功能：手動輸入股票代號
# =================================================================
stock_input = st.text_input(
    "🔍 請輸入股票代號（台股直接打數字如 2324、2303；美股直接打英文如 NVDA），輸入完請按 Enter：",
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
sub_chart_3 = st.sidebar.selectbox("📊 副圖軌道 3：", slot_options, index=3) # 預設選 RSI

active_slots = []
for choice in [sub_chart_1, sub_chart_2, sub_chart_3]:
    if choice != "❌ 隱藏此軌道":
        active_slots.append(choice)

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=3 * 365)


# --- K 線資料載入與智慧中文名稱查找 ---
@st.cache_data
def load_stock_history(sid, start, end):
    ticker = yf.Ticker(sid)
    df = ticker.history(start=start, end=end)
    if df.empty:
        return pd.DataFrame(), sid, pd.DataFrame()

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
        "2308.TW": "台達電", "2454.TW": "聯發科", "2357.TW": "華碩", "2382.TW": "廣達"
    }

    s_name = backup_zh_dict.get(sid)
    quarter_stmt = pd.DataFrame()
    
    try:
        # 即時動態向網路抓取官方發布的完整季度表
        quarter_stmt = ticker.get_income_stmt(freq='quarterly')
        if s_name is None:
            info_dict = ticker.info
            s_name = info_dict.get("shortName") or info_dict.get("longName") or sid
    except Exception:
        if s_name is None: s_name = sid

    return df, s_name, quarter_stmt


try:
    # 執行動態網路資料下載
    df_all, stock_name, df_quarter_stmt = load_stock_history(stock_id, start_date, end_date)

    if df_all.empty:
        st.error(f"❌ 找不到股票代號 '{stock_input}' 的 K 線資料。")
    else:
        # =================================================================
        # 💵 🔥 基本面區：完全移除最上方三大卡片，直接列出每季真資料
        # =================================================================
        st.subheader(f"💵 {stock_name} ({stock_id}) 歷史季度財報動態")
        
        is_etf = is_tw_stock and (stock_input.startswith("00") or len(stock_input) >= 5)
        
        if is_etf:
            st.info(f"💡 提示：{stock_name} ({stock_id}) 屬於指數型基金 (ETF)，故無單季財務數據。")
        else:
            st.markdown("#### 📅 去年 vs 今年：每一季度詳細財報對比矩陣")
            
            has_matrix_success = False
            
            # 100% 檢查原始網路回傳的損益表結構
            if df_quarter_stmt is not None and not df_quarter_stmt.empty:
                # 智慧比對國際會計準則常用標籤
                revenue_keys = ["Total Revenue", "Operating Revenue", "Gross Revenue"]
                eps_keys = ["Diluted EPS", "Basic EPS", "Earnings Per Share"]
                
                rev_row_name = next((idx for idx in df_quarter_stmt.index if any(k in str(idx) for k in revenue_keys)), None)
                eps_row_name = next((idx for idx in df_quarter_stmt.index if any(k in str(idx) for k in eps_keys)), None)
                
                if rev_row_name and eps_row_name:
                    try:
                        # 擷取網路上最新的 8 個季度（正好涵蓋去年與今年）並進行時間由遠到近排序
                        raw_rev = df_quarter_stmt.loc[rev_row_name].iloc[:8].iloc[::-1]
                        raw_eps = df_quarter_stmt.loc[eps_row_name].iloc[:8].iloc[::-1]
                        
                        # 格式化日期與單位轉換
                        dates_list = [pd.to_datetime(d).strftime("%Y-%m-%d") for d in raw_rev.index]
                        rev_in_hundred_millions = [float(v) / 100000000 for v in raw_rev.values] # 轉為億元台幣
                        eps_real_vals = [float(v) for v in raw_eps.values]
                        
                        # 產生 100% 真實網路組裝表格
                        df_dynamic_financial = pd.DataFrame({
                            "季度截止日": dates_list,
                            "單季 EPS (元)": eps_real_vals,
                            "單季營收 (億元)": rev_in_hundred_millions
                        })
                        
                        # 進行網頁左右欄精密排版
                        q_col1, q_col2 = st.columns([4, 6])
                        with q_col1:
                            st.write("📋 **真實動態網路季度報表**：")
                            st.dataframe(
                                df_dynamic_financial.style.format({
                                    "單季 EPS (元)": "{:.2f}",
                                    "單季營收 (億元)": "{:,.1f}"
                                }),
                                use_container_width=True,
                                hide_index=True
                            )
                        with q_col2:
                            st.write("📊 **每一季營收與 EPS 多空走勢圖**：")
                            fig_q = make_subplots(specs=[[{"secondary_y": True}]])
                            fig_q.add_trace(go.Bar(x=df_dynamic_financial["季度截止日"], y=df_dynamic_financial["單季營收 (億元)"], name="單季營收 (億元)", marker_color="#34495E", opacity=0.85), secondary_y=False)
                            fig_q.add_trace(go.Scatter(x=df_dynamic_financial["季度截止日"], y=df_dynamic_financial["單季 EPS (元)"], name="單季 EPS (元)", mode="lines+markers", line=dict(color="#E74C3C", width=3), marker=dict(size=7)), secondary_y=True)
                            
                            fig_q.update_layout(template="plotly_dark", height=250, margin=dict(l=10, r=10, t=10, b=10), showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                            fig_q.update_yaxes(title_text="營收 (億元)", secondary_y=False)
                            fig_q.update_yaxes(title_text="EPS (元)", secondary_y=True)
                            st.plotly_chart(fig_q, use_container_width=True)
                            
                        has_matrix_success = True
                    except Exception:
                        pass
            
            # 若網路當下真的回傳空值，誠實回報，不給予任何人工偽造數據
            if not has_matrix_success:
                st.warning("⚠️ 提示：當前即時網路接口（Yahoo 財務庫）未回傳本個股的季度詳細損益表欄位。若要取得本標的之每一季 EPS，我們需要為系統升級更換其他開放資料庫 API。")

        # =================================================================
        # 📈 互動式 K 線圖與指標（完美保留運作）
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

except Exception as e:
    st.error(f"系統執行錯誤，錯誤訊息: {e}")

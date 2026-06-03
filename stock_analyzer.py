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
st.title("📊 專業互動式股票分析系統 (精密深色多均線配置版)")

# =================================================================
# ⚙️ 核心功能：手動輸入股票代號 (主畫面最上方)
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
st.sidebar.header("🎛️ 副圖軌道控制面板")
st.sidebar.caption("你可以任意挑選並置換下方三個副圖的顯示內容。")

slot_options = [
    "成交量 (VOL)",
    "MACD 技術指標",
    "外資買賣超 (張)",
    "投信買賣超 (張)",
    "自營商買賣超 (張)",
    "三大法人合計 (張)",
    "❌ 隱藏此軌道"
]

sub_chart_1 = st.sidebar.selectbox("📊 副圖軌道 1 內容：", slot_options, index=0)
sub_chart_2 = st.sidebar.selectbox("📊 副圖軌道 2 內容：", slot_options, index=1)
sub_chart_3 = st.sidebar.selectbox("📊 副圖軌道 3 內容：", slot_options, index=2)

active_slots = []
for choice in [sub_chart_1, sub_chart_2, sub_chart_3]:
    if choice != "❌ 隱藏此軌道":
        active_slots.append(choice)

# 時間範圍設定
end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=3 * 365)


# --- K 線資料載入與全自動中文名稱查找 ---
@st.cache_data
def load_stock_history(sid, start, end, is_tw):
    ticker = yf.Ticker(sid)
    df = ticker.history(start=start, end=end)
    if df.empty:
        return pd.DataFrame(), sid

    # 🔥 核心修正：計算 5日、10日、以及全新的 30日均線
    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA10"] = df["Close"].rolling(window=10).mean()
    df["MA30"] = df["Close"].rolling(window=30).mean() # 👈 加強 30 日線
    
    # MACD 技術指標計算
    exp1 = df["Close"].ewm(span=12, adjust=False).mean()
    exp2 = df["Close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = exp1 - exp2
    df["MACD_Signal"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["DIF"] - df["MACD_Signal"]

    s_name = None
    pure_id = sid.replace(".TW", "")
    
    if is_tw:
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
        s_name = ticker.info.get("shortName") or ticker.info.get("longName") or sid
        
    return df, s_name


# --- 備用方案：Yahoo Finance 財報抓取備援 ---
def fetch_yahoo_eps(sid):
    ticker_obj = yf.Ticker(sid)
    quarterly_financials = ticker_obj.quarterly_financials
    if (
        quarterly_financials is not None
        and "Basic EPS" in quarterly_financials.index
    ):
        eps_q = quarterly_financials.loc[["Basic EPS"]].iloc[:, ::-1].iloc[:, -6:]
        formatted_cols = [
            c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c)
            for c in eps_q.columns
        ]
        return pd.DataFrame(
            eps_q.values, columns=formatted_cols, index=["季度 EPS"]
        ).fillna("--")
    return pd.DataFrame()


try:
    # 1. 讀取 K 線歷史資料
    df_all, stock_name = load_stock_history(stock_id, start_date, end_date, is_tw_stock)

    if df_all.empty:
        st.error(f"❌ 找不到股票代號 '{stock_input}' 的 K 線資料。")
    else:
        # =================================================================
        # 💵 基本面核心看板：歷史季度 EPS 與 月營收
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
                            eps_data_final = eps_data[eps_data["type"] == first_type]
                            eps_data_final = eps_data_final.sort_values("date")

                            display_eps_df = pd.DataFrame(
                                [eps_data_final["value"].values],
                                columns=eps_data_final["date"].values,
                                index=["季度 EPS (元)"],
                            )

                            display_eps_df = display_eps_df.iloc[:, -6:]
                            st.write("**📊 歷史季度 EPS 表（近 6 季）：**")
                            st.dataframe(display_eps_df.style.format("{:.2f}"))
                            has_eps_displayed = True

                except Exception:
                    pass

            if not has_eps_displayed:
                yf_eps_df = fetch_yahoo_eps(stock_id)
                if not yf_eps_df.empty:
                    st.info("💡 提示：在地即時庫忙碌中，當前切換至國際雙軌備援財報。")
                    st.write("**📊 歷史季度 EPS 表（近 6 季）：**")
                    st.dataframe(yf_eps_df.style.format(lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else str(v)))
                else:
                    st.warning("⚠️ 數據源目前無該個股的季度 EPS 欄位。")

            # --- 每月合併營收表格 ---
            if is_tw_stock:
                st.write("") 
                st.write("**📈 歷史每月合併營收表（去年至今年動態）：**")
                try:
                    current_year = datetime.date.today().year
                    revenue_start_date = f"{current_year - 1}-01-01"
                    revenue_end_date = end_date.strftime("%Y-%m-%d")

                    fm_revenue_df = fm_loader.taiwan_stock_month_revenue(
                        stock_id=stock_input,
                        start_date=revenue_start_date,
                        end_date=revenue_end_date
                    )

                    if not fm_revenue_df.empty:
                        fm_revenue_df = fm_revenue_df.sort_values("date")
                        fm_revenue_df["revenue_month"] = pd.to_datetime(fm_revenue_df["date"]).dt.strftime("%Y-%m")
                        fm_revenue_df["revenue_in_hundred_million"] = fm_revenue_df["revenue"] / 100000000

                        display_rev_df = pd.DataFrame(
                            [fm_revenue_df["revenue_in_hundred_million"].values],
                            columns=fm_revenue_df["revenue_month"].values,
                            index=["單月營收 (億元)"]
                        )
                        
                        display_rev_df = display_rev_df.iloc[:, -16:]
                        st.dataframe(display_rev_df.style.format("{:,.2f}"))
                    else:
                        st.info("💡 該代號目前無官方合併營收申報資料。")
                except Exception as rev_err:
                    st.caption(f"ℹ️ 月營收資料庫暫時連線忙碌中")

        # =================================================================
        # 👥 籌碼數據預處理 (抹除時區，與 K 線完全同步聯動)
        # =================================================================
        df_chip_timeline = pd.DataFrame()
        any_chip_active = any("張" in slot for slot in active_slots)

        if is_tw_stock and any_chip_active:
            try:
                fm_loader = DataLoader()
                chip_start_historical = (datetime.date.today() - datetime.timedelta(days=500)).strftime("%Y-%m-%d")
                chip_end_historical = datetime.date.today().strftime("%Y-%m-%d")
                
                raw_chip_df = fm_loader.taiwan_stock_institutional_investors(
                    stock_id=stock_input, start_date=chip_start_historical, end_date=chip_end_historical,
                )
                
                if not raw_chip_df.empty:
                    raw_chip_df["net_buy_sheets"] = (raw_chip_df["buy"] - raw_chip_df["sell"]) / 1000
                    
                    def group_names(n_str):
                        if "Foreign" in n_str or "外資" in n_str: return "Foreign"
                        elif "Investment" in n_str or "投信" in n_str: return "Trust"
                        elif "Dealer" in n_str or "自營" in n_str or "Proprietary" in n_str: return "Dealer"
                        return None
                        
                    raw_chip_df["group_name"] = raw_chip_df["name"].apply(group_names)
                    raw_chip_df = raw_chip_df.dropna(subset=["group_name"])
                    
                    df_chip_timeline = raw_chip_df.pivot_table(
                        index="date", columns="group_name", values="net_buy_sheets", aggfunc="sum"
                    ).fillna(0)
                    
                    df_chip_timeline["Total"] = df_chip_timeline.get("Foreign", 0) + df_chip_timeline.get("Trust", 0) + df_chip_timeline.get("Dealer", 0)
                    df_chip_timeline.index = pd.to_datetime(df_chip_timeline.index).tz_localize(None)
            except Exception:
                pass

        # =================================================================
        # 📈 互動式 K 線圖：智慧多軌動態排版機制 (5 選 3 自由配置)
        # =================================================================
        st.markdown("---")
        st.subheader(f"📈 互動看板 (主圖內建深色 5/10/30 MA 系統)")

        df = df_all.tail(250).copy()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        total_rows = 1 + len(active_slots)
        
        if len(active_slots) == 3:
            row_heights = [0.52, 0.16, 0.16, 0.16]
        elif len(active_slots) == 2:
            row_heights = [0.60, 0.20, 0.20]
        elif len(active_slots) == 1:
            row_heights = [0.70, 0.30]
        else:
            row_heights = [1.0]

        specs = [[{"secondary_y": False}] for _ in range(total_rows)]

        fig = make_subplots(
            rows=total_rows, cols=1, shared_xaxes=True,
            vertical_spacing=0.03, row_heights=row_heights, specs=specs,
        )

        # 🚀 軌道 1：繪製 K 線圖與【🔥 經調色後的深色多均線系統】
        fig.add_trace(
            go.Candlestick(
                x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="K線",
                increasing=dict(fillcolor="#FF3333", line=dict(color="#FF3333")),
                decreasing=dict(fillcolor="#00AA00", line=dict(color="#00AA00")),
            ), row=1, col=1,
        )
        
        # 5日線更換為：深金金啡色 (#B38F00)
        fig.add_trace(go.Scatter(x=df.index, y=df["MA5"], line=dict(color="#B38F00", width=1.5), name="5日線(週)"), row=1, col=1)
        # 10日線更換為：內斂深青銅藍 (#008B8B)
        fig.add_trace(go.Scatter(x=df.index, y=df["MA10"], line=dict(color="#008B8B", width=1.5), name="10日線(雙週)"), row=1, col=1)
        # 🔥 全新加入 30日線：沉穩深紫羅蘭色 (#7A4D99)
        fig.add_trace(go.Scatter(x=df.index, y=df["MA30"], line=dict(color="#7A4D99", width=1.8), name="30日線(月線)"), row=1, col=1)

        # 🚀 軌道 2 ~ 4：動態配置副圖
        current_track_row = 2
        
        for slot_choice in active_slots:
            if slot_choice == "成交量 (VOL)":
                vol_colors = ["#FF3333" if cl >= op else "#00AA00" for cl, op in zip(df["Close"], df["Open"])]
                fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vol_colors, name="成交量"), row=current_track_row, col=1)
                fig.update_yaxes(title_text="成交量 (VOL)", row=current_track_row, col=1)
            
            elif slot_choice == "MACD 技術指標":
                fig.add_trace(go.Scatter(x=df.index, y=df["DIF"], line=dict(color="#CC4400", width=1.8), name="DIF (快線)"), row=current_track_row, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df["MACD_Signal"], line=dict(color="#1F4E99", width=1.8), name="MACD (慢線)"), row=current_track_row, col=1)
                colors = ["#FF3333" if val >= 0 else "#00AA00" for val in df["MACD_Hist"]]
                fig.add_trace(go.Bar(x=df.index, y=df["MACD_Hist"], marker_color=colors, name="MACD柱狀體"), row=current_track_row, col=1)
                fig.update_yaxes(title_text="MACD指標", row=current_track_row, col=1)
            
            elif "張" in slot_choice:
                if df_chip_timeline.empty:
                    fig.add_trace(go.Scatter(x=df.index, y=[0]*len(df), name="美股暫無法人籌碼圖"), row=current_track_row, col=1)
                    fig.update_yaxes(title_text="籌碼無數據", row=current_track_row, col=1)
                else:
                    df_merged_chip = pd.DataFrame(index=df.index).join(df_chip_timeline, how="left").fillna(0)
                    
                    mapping_key = {
                        "外資買賣超 (張)": ("Foreign", "外資買賣超 (張)"),
                        "投信買賣超 (張)": ("Trust", "投信買賣超 (張)"),
                        "自營商買賣超 (張)": ("Dealer", "自營商買賣超 (張)"),
                        "三大法人合計 (張)": ("Total", "法人合計 (張)")
                    }
                    target_col, label_text = mapping_key.get(slot_choice, ("Foreign", "外資買賣超 (張)"))
                    
                    chip_values = df_merged_chip[target_col]
                    chip_colors = ["#FF3333" if val >= 0 else "#00AA00" for val in chip_values]
                    
                    fig.add_trace(go.Bar(x=df_merged_chip.index, y=chip_values, marker_color=chip_colors, name=label_text), row=current_track_row, col=1)
                    fig.update_yaxes(title_text=label_text, row=current_track_row, col=1)
                    fig.add_hline(y=0, line_width=1, line_color="#555555", row=current_track_row, col=1)
            
            current_track_row += 1

        # 🎛️ 全局樣式調整與半年聚焦
        fig.update_layout(
            template="plotly_dark",
            title=dict(text=f"📈 {stock_name} ({stock_id}) - 高級精密自訂看板", font=dict(size=22, family="Microsoft JhengHei")),
            xaxis_rangeslider_visible=False, height=850, margin=dict(l=50, r=50, t=50, b=50), showlegend=True,
            font=dict(family="Microsoft JhengHei"),
        )

        six_months_ago = datetime.date.today() - datetime.timedelta(days=180)
        fig.update_xaxes(range=[six_months_ago, datetime.date.today()], showgrid=True, gridwidth=1, gridcolor="#222222")
        fig.update_yaxes(title_text="價格 (Price)", row=1, col=1, showgrid=True, gridwidth=1, gridcolor="#222222")

        # 自動偵測 K 線轉折紅虛線
        for i in range(1, len(df)):
            prev_hist = df["MACD_Hist"].iloc[i-1]
            curr_hist = df["MACD_Hist"].iloc[i]
            target_date = df.index[i]
            if prev_hist < 0 and curr_hist >= 0:
                if target_date.date() >= six_months_ago:
                    fig.add_vline(x=target_date, line_width=1.5, line_dash="dash", line_color="#FF4444", opacity=0.7)

        st.plotly_chart(fig, use_container_width=True)

        # =================================================================
        # 👥 籌碼表格區
        # =================================================================
        if is_tw_stock:
            st.markdown("---")
            st.subheader(f"👥 {stock_name} ({stock_id}) 近 10 日三大法人買賣超動向明細表")

            try:
                fm_loader = DataLoader()
                chip_start_date = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
                chip_end_date = datetime.date.today().strftime("%Y-%m-%d")

                chip_df = fm_loader.taiwan_stock_institutional_investors(
                    stock_id=stock_input, start_date=chip_start_date, end_date=chip_end_date,
                )

                if not chip_df.empty:
                    chip_df["net_buy_sheets"] = (chip_df["buy"] - chip_df["sell"]) / 1000

                    def group_institutional_names(name_str):
                        if not isinstance(name_str, str): return None
                        if "Foreign" in name_str or "外資" in name_str: return "外資買賣超 (張)"
                        elif "Investment" in name_str or "投信" in name_str: return "投信買賣超 (張)"
                        elif "Dealer" in name_str or "自營" in name_str or "Proprietary" in name_str: return "自營商買賣超 (張)"
                        return None

                    chip_df["name"] = chip_df["name"].apply(group_institutional_names)
                    chip_df = chip_df.dropna(subset=["name"])

                    pivot_chip = chip_df.pivot_table(index="name", columns="date", values="net_buy_sheets", aggfunc="sum")
                    desired_order = ["外資買賣超 (張)", "投信買賣超 (張)", "自營商買賣超 (張)"]
                    pivot_chip = pivot_chip.reindex(desired_order)

                    pivot_chip_10d = pivot_chip.iloc[:, -10:].copy()
                    pivot_chip_10d.loc["🔥 三大法人合計買賣超 (張)"] = pivot_chip_10d.sum(axis=0)
                    pivot_chip_10d["10日累積總計 (張)"] = pivot_chip_10d.sum(axis=1)

                    def color_buy_sell(val):
                        if isinstance(val, (int, float)):
                            color = "#FF3333" if val >= 0 else "#00AA00"
                            return f"color: {color}; font-weight: bold;"
                        return ""

                    st.dataframe(pivot_chip_10d.style.format("{:,.1f}").map(color_buy_sell))
                else:
                    st.warning("⚠️ 官方籌碼資料庫目前忙碌中，暫無近 10 日法人數據。")
            except Exception as chip_err:
                st.error(f"❌ 籌碼模組執行異常，錯誤訊息: {chip_err}")
        else:
            st.info("💡 提示：美股在台灣證交所無三大法人籌碼申報數據。")

except Exception as e:
    st.error(f"系統執行錯誤，錯誤訊息: {e}")

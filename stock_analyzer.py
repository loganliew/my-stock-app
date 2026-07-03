import streamlit as st
import pandas as pd
import os
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# 🔑 讀取名稱對照表專用的 API 通行證
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibG9nYW5saWV3IiwiZW1haWwiOiJzMjI3MDIyMjZAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.j2WUIuC7PJGNKSwAviyTbj0bwuq8AJUmd4rWVQ9rUOY" 

# =================================================================
# 🔍 0. 智慧快取：線上獲取股票代號與中文名稱對照表
# =================================================================
@st.cache(ttl=86400)
def load_stock_name_map():
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockInfo", "token": FINMIND_TOKEN}
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if data.get("msg") == "success":
            return {str(item['stock_id']): str(item['stock_name']) for item in data['data']}
    except Exception:
        pass
    return {}

# =================================================================
# 📂 1. 資料讀取與清洗區
# =================================================================
def load_and_clean_data():
    file_path = os.path.join("data", "tw_eps_revenue.csv")
    if not os.path.exists(file_path):
        return None

    encodings_to_try = ['utf-8-sig', 'utf-8', 'cp950']
    df = None
    for enc in encodings_to_try:
        try:
            df = pd.read_csv(file_path, encoding=enc, engine='python', on_bad_lines='skip')
            break
        except Exception:
            continue

    if df is None or df.empty:
        return None

    try:
        df['股票代號'] = df['股票代號'].astype(str)
        df = df.sort_values(by=['股票代號', '季度名稱'])
        latest_df = df.drop_duplicates(subset=['股票代號'], keep='last').copy()
        
        name_map = load_stock_name_map()
        if name_map:
            latest_df['股票代號'] = latest_df['股票代號'].apply(
                lambda x: f"{x} {name_map.get(x, '')}".strip()
            )
        return latest_df
    except Exception:
        return None

# =================================================================
# 🧮 2. 基本面分數計算機
# =================================================================
def calculate_fundamental_score(df):
    scored_df = df.copy()
    scored_df['Score'] = 0
    
    scored_df.loc[scored_df['單季 EPS (元)'] > 0, 'Score'] += 30
    scored_df.loc[scored_df['單季 EPS (元)'] >= 2, 'Score'] += 20
    scored_df.loc[scored_df['單季營收 (億元)'] > 50, 'Score'] += 20
    
    if '單季毛利率 (%)' in scored_df.columns:
        scored_df.loc[scored_df['單季毛利率 (%)'] > 20, 'Score'] += 30
        
    def get_recommendation(score):
        if score >= 90: return "🔥 強力買進"
        elif score >= 70: return "📈 買進"
        elif score >= 60: return "⚖️ 普通"
        elif score >= 30: return "📉 賣出"
        else: return "❌ 強力賣出"
            
    scored_df['投資建議'] = scored_df['Score'].apply(get_recommendation)
    
    cols = list(scored_df.columns)
    if '投資建議' in cols and 'Score' in cols:
        cols.remove('投資建議')
        score_idx = cols.index('Score')
        cols.insert(score_idx + 1, '投資建議')
        scored_df = scored_df[cols]
        
    return scored_df

# =================================================================
# 📊 3. 穩定版：FinMind 股價爬蟲
# =================================================================
def fetch_stock_price(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (datetime.now() - timedelta(days=250)).strftime('%Y-%m-%d')
    
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": str(stock_id),
        "start_date": start_date,
        "token": FINMIND_TOKEN
    }
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            df = pd.DataFrame(data["data"])
            df = df.rename(columns={'max': 'high', 'min': 'low'})
            return df
    except Exception:
        pass
    return pd.DataFrame()

# =================================================================
# 🖥️ 4. 前端介面展示 (Streamlit)
# =================================================================
def main():
    st.set_page_config(page_title="台股財報量化看盤", page_icon="📈", layout="wide")
    
    st.title("📈 台股量化看盤系統 (基本面 + 技術面)")
    st.write("資料來源：GitHub Actions 自動抓取之財報，搭配 FinMind 即時股價與技術分析")
    
    raw_df = load_and_clean_data()
    
    if raw_df is not None and not raw_df.empty:
        result_df = calculate_fundamental_score(raw_df)
        result_df = result_df.sort_values(by=['Score', '單季 EPS (元)'], ascending=[False, False]).reset_index(drop=True)
        high_score_df = result_df[result_df['Score'] >= 70]
        
        st.markdown("---")
        
        st.subheader(f"🏆 嚴選潛力股清單 (共 {len(high_score_df)} 檔)")
        if not high_score_df.empty:
            styled_high_score = high_score_df.style.format({
                "單季營收 (億元)": "{:.2f}",
                "單季 EPS (元)": "{:.2f}",
                "單季毛利率 (%)": "{:.2f}" if "單季毛利率 (%)" in high_score_df.columns else "{}"
            }).bar(subset=['Score'], color='#20c997', vmin=0, vmax=100)
            st.dataframe(styled_high_score)
        else:
            st.warning("目前沒有符合標準的標的。")

        st.markdown("---")

        with st.expander(f"📂 點擊展開：查看全市場 {len(result_df)} 檔股票評分總表"):
            all_market_df = result_df.sort_values(by='股票代號').reset_index(drop=True)
            styled_all = all_market_df.style.format({
                "單季營收 (億元)": "{:.2f}",
                "單季 EPS (元)": "{:.2f}",
                "單季毛利率 (%)": "{:.2f}" if "單季毛利率 (%)" in all_market_df.columns else "{}"
            }).bar(subset=['Score'], color='#6c757d', vmin=0, vmax=100)
            st.dataframe(styled_all)

        st.markdown("---")

        # ==========================================
        # 📈 第三區塊：個股技術面分析 (專業全指標版)
        # ==========================================
        st.header("📈 專業技術分析面版")
        
        st.write("⚙️ **個股查詢與指標開關**")
        
        # 💡 調整比例：放大均線選單的寬度，讓多選框有空間展開
        col_input, col_ma, col_bb, col_vol, col_macd = st.columns([1.5, 3, 1, 1, 1])
        
        with col_input:
            query_stock = st.text_input("🔍 輸入代號並按 Enter", "2330")
        with col_ma:
            # 💡 核心升級：使用 multiselect 替換 checkbox
            ma_options = st.multiselect(
                "📊 選擇顯示均線", 
                options=["5MA", "10MA", "20MA(月線)", "60MA(季線)"], 
                default=["5MA", "10MA", "20MA(月線)", "60MA(季線)"]
            )
        with col_bb:
            st.write(" ")
            show_bb = st.checkbox("顯示布林", value=False)
        with col_vol:
            st.write(" ")
            show_vol = st.checkbox("顯示成交量", value=True)
        with col_macd:
            st.write(" ")
            show_macd = st.checkbox("顯示 MACD", value=False)

        if query_stock:
            with st.spinner("載入專業線圖中..."):
                hist = fetch_stock_price(query_stock)
                
                if not hist.empty:
                    numeric_cols = ['open', 'high', 'low', 'close', 'Trading_Volume']
                    hist[numeric_cols] = hist[numeric_cols].apply(pd.to_numeric, errors='coerce')
                    hist['Trading_Volume'] = hist['Trading_Volume'].fillna(0)
                    
                    hist['date'] = pd.to_datetime(hist['date'])
                    hist = hist.sort_values('date').dropna(subset=['close']).reset_index(drop=True)
                    
                    hist['MA5'] = hist['close'].rolling(window=5).mean()
                    hist['MA10'] = hist['close'].rolling(window=10).mean()
                    hist['MA20'] = hist['close'].rolling(window=20).mean()
                    hist['MA60'] = hist['close'].rolling(window=60).mean()
                    
                    hist['BB_std'] = hist['close'].rolling(window=20).std()
                    hist['BB_upper'] = hist['MA20'] + (2 * hist['BB_std'])
                    hist['BB_lower'] = hist['MA20'] - (2 * hist['BB_std'])
                    
                    exp1 = hist['close'].ewm(span=12, adjust=False).mean()
                    exp2 = hist['close'].ewm(span=26, adjust=False).mean()
                    hist['MACD'] = exp1 - exp2
                    hist['Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
                    hist['MACD_Hist'] = hist['MACD'] - hist['Signal']
                    
                    display_df = hist.tail(120).copy()
                    
                    dates = display_df['date'].tolist()
                    open_p = display_df['open'].tolist()
                    high_p = display_df['high'].tolist()
                    low_p = display_df['low'].tolist()
                    close_p = display_df['close'].tolist()
                    volumes = display_df['Trading_Volume'].tolist()
                    
                    ma5 = display_df['MA5'].tolist()
                    ma10 = display_df['MA10'].tolist()
                    ma20 = display_df['MA20'].tolist()
                    ma60 = display_df['MA60'].tolist()
                    
                    bb_upper = display_df['BB_upper'].tolist()
                    bb_lower = display_df['BB_lower'].tolist()
                    
                    macd = display_df['MACD'].tolist()
                    signal = display_df['Signal'].tolist()
                    macd_hist = display_df['MACD_Hist'].tolist()
                    
                    stock_colors = ['#ef5350' if c >= o else '#26a69a' for c, o in zip(close_p, open_p)]
                    macd_colors = ['#ef5350' if val >= 0 else '#26a69a' for val in macd_hist]
                    
                    plot_rows = 1
                    row_heights = [0.6]
                    vol_row = macd_row = 0
                    
                    if show_vol:
                        plot_rows += 1
                        vol_row = plot_rows
                        row_heights.append(0.2)
                    if show_macd:
                        plot_rows += 1
                        macd_row = plot_rows
                        row_heights.append(0.2)
                        
                    total_height = sum(row_heights)
                    row_heights = [h/total_height for h in row_heights]

                    fig = make_subplots(rows=plot_rows, cols=1, shared_xaxes=True, 
                                        vertical_spacing=0.03, row_heights=row_heights)
                    
                    # 1. 畫主圖 (K線)
                    fig.add_trace(go.Candlestick(x=dates, open=open_p, high=high_p, low=low_p, close=close_p, name="K線",
                                  increasing_line_color='#ef5350', decreasing_line_color='#26a69a'), row=1, col=1)
                    
                    # 💡 動態畫均線：根據多選選單的結果，決定要畫哪幾條線
                    if "5MA" in ma_options:
                        fig.add_trace(go.Scatter(x=dates, y=ma5, line=dict(color='#ff9800', width=1.5), name='5MA'), row=1, col=1)
                    if "10MA" in ma_options:
                        fig.add_trace(go.Scatter(x=dates, y=ma10, line=dict(color='#e91e63', width=1.5), name='10MA'), row=1, col=1)
                    if "20MA(月線)" in ma_options:
                        fig.add_trace(go.Scatter(x=dates, y=ma20, line=dict(color='#2196f3', width=1.5), name='20MA(月線)'), row=1, col=1)
                    if "60MA(季線)" in ma_options:
                        fig.add_trace(go.Scatter(x=dates, y=ma60, line=dict(color='#9c27b0', width=2), name='60MA(季線)'), row=1, col=1)
                    
                    if show_bb:
                        fig.add_trace(go.Scatter(x=dates, y=bb_upper, line=dict(color='rgba(158,158,158,0.5)', width=1, dash='dash'), name='布林上軌'), row=1, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=bb_lower, line=dict(color='rgba(158,158,158,0.5)', width=1, dash='dash'), fill='tonexty', fillcolor='rgba(158,158,158,0.1)', name='布林下軌'), row=1, col=1)

                    if show_vol:
                        fig.add_trace(go.Bar(x=dates, y=volumes, marker_color=stock_colors, name='成交量', orientation='v'), row=vol_row, col=1)
                        fig.update_yaxes(title_text="成交量", row=vol_row, col=1)

                    if show_macd:
                        fig.add_trace(go.Bar(x=dates, y=macd_hist, marker_color=macd_colors, name='MACD 柱狀體', orientation='v'), row=macd_row, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=macd, line=dict(color='#2196f3', width=1.5), name='MACD 快線'), row=macd_row, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=signal, line=dict(color='#ff9800', width=1.5), name='MACD 慢線'), row=macd_row, col=1)
                        fig.update_yaxes(title_text="MACD", row=macd_row, col=1)

                    chart_height = 500 if plot_rows == 1 else (650 if plot_rows == 2 else 800)
                    
                    fig.update_layout(
                        title=f"{query_stock} 專業技術分析",
                        xaxis_rangeslider_visible=False,
                        height=chart_height,
                        margin=dict(l=0, r=0, t=40, b=0),
                        hovermode="x unified",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    
                    for i in range(1, plot_rows + 1):
                        fig.update_yaxes(type='linear', row=i, col=1)
                        fig.update_xaxes(type='date', row=i, col=1)
                        if i < plot_rows:
                            fig.update_xaxes(showticklabels=False, row=i, col=1)

                    all_dates = pd.date_range(start=display_df['date'].min(), end=display_df['date'].max())
                    missing_dates = all_dates.difference(display_df['date']).strftime("%Y-%m-%d").tolist()

                    for i in range(1, plot_rows + 1):
                        if missing_dates:
                            fig.update_xaxes(rangebreaks=[dict(values=missing_dates)], row=i, col=1)

                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning(f"找不到 {query_stock} 的技術資料，請確認代號是否正確。")

if __name__ == "__main__":
    main()

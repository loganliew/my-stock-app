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
        
        name_map = load_stock_name_map()
        if name_map:
            df['股票代號'] = df['股票代號'].apply(
                lambda x: f"{x} {name_map.get(x, '')}".strip()
            )
        return df
    except Exception:
        return None

def load_monthly_revenue_data():
    file_path = os.path.join("data", "tw_monthly_revenue.csv")
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
    df['股票代號'] = df['股票代號'].astype(str)
    return df

def calculate_monthly_mom_status(monthly_df):
    if monthly_df is None or monthly_df.empty:
        return {}
    
    mom_dict = {}
    monthly_df = monthly_df.sort_values(by=['股票代號', '年月'])
    
    for stock_id, group in monthly_df.groupby('股票代號'):
        valid_group = group[group['年月'] != '無資料']
        if len(valid_group) >= 2:
            curr_m = valid_group.iloc[-1]
            prev_m = valid_group.iloc[-2]
            
            is_growth = float(curr_m['單月營收 (億元)']) > float(prev_m['單月營收 (億元)'])
            mom_dict[str(stock_id)] = (is_growth, curr_m['年月'])
        elif len(valid_group) == 1:
            mom_dict[str(stock_id)] = (False, valid_group.iloc[-1]['年月'])
            
    return mom_dict

# =================================================================
# 🧮 2. 第一階段：基本面評分 (滿分 21 分)
# =================================================================
def calculate_fundamental_score(df, mom_dict):
    scores = []
    
    for stock, group in df.groupby('股票代號'):
        group = group.sort_values('季度名稱')
        if len(group) == 0: continue
        
        valid_group = group[group['季度名稱'] != '無資料']
        if valid_group.empty: continue
        
        curr = valid_group.iloc[-1] 
        prev = valid_group.iloc[-2] if len(valid_group) > 1 else None 
        
        score = 0
        details = [] 
        
        if curr['單季 EPS (元)'] > 0: 
            score += 5
            details.append("✅ EPS > 0 (+5分)")
        else: 
            score -= 5
            details.append("❌ EPS <= 0 (-5分)")
            
        if prev is not None and curr['單季營收 (億元)'] > prev['單季營收 (億元)']:
            score += 5
            details.append("✅ 季度營收呈季增 (+5分)")
        else:
            details.append("❌ 季度營收無季增 (0分)")
            
        if prev is not None and '單季毛利率 (%)' in curr and '單季毛利率 (%)' in prev:
            if curr['單季毛利率 (%)'] > prev['單季毛利率 (%)']:
                score += 5
                details.append("✅ 毛利率季增 (+5分)")
            else:
                details.append("❌ 毛利率無季增 (0分)")
        else:
            details.append("❌ 缺毛利率資料 (0分)")
            
        raw_stock_id = stock.split()[0]
        if raw_stock_id in mom_dict:
            is_growth, month_name = mom_dict[raw_stock_id]
            if is_growth:
                score += 6
                details.append(f"✅ 月營收動能：{month_name} 營收 > 前月 (+6分)")
            else:
                details.append(f"❌ 月營收動能：{month_name} 營收 <= 前月 (0分)")
        else:
            details.append("❌ 缺最新月營收對比資料 (0分)")
                
        scores.append({
            '股票代號': stock,
            '季度名稱': curr['季度名稱'],
            '單季 EPS (元)': curr['單季 EPS (元)'],
            '單季營收 (億元)': curr['單季營收 (億元)'],
            '單季毛利率 (%)': curr.get('單季毛利率 (%)', 0),
            '基本面評分 (滿分21)': score,
            '給分明細': " | ".join(details) 
        })
        
    if not scores:
        return pd.DataFrame()
        
    scored_df = pd.DataFrame(scores)
    
    def get_fund_rec(s):
        if s >= 18: return "🔥 強力買進"
        elif s >= 12: return "📈 買進"
        elif s >= 6: return "⚖️ 普通"
        elif s >= 0: return "📉 賣出"
        else: return "❌ 強力賣出"
            
    scored_df['基本面初評'] = scored_df['基本面評分 (滿分21)'].apply(get_fund_rec)
    
    cols = list(scored_df.columns)
    cols.insert(cols.index('基本面初評') + 1, cols.pop(cols.index('給分明細')))
    scored_df = scored_df[cols]
    
    return scored_df

# =================================================================
# 📊 3. 穩定版：FinMind 股價爬蟲 (新增限流警告與防呆)
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
        
        # 💡 新增：老實告訴使用者是不是 API 爆掉了
        if "Too Many Requests" in data.get("msg", ""):
            st.error("🛑 【系統提示】您的 FinMind API 查詢次數已達每小時上限！這通常是因為後端爬蟲正在大量抓資料，請稍候一小時再查詢技術線圖。")
            return pd.DataFrame()
            
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            df = pd.DataFrame(data["data"])
            df = df.rename(columns={'max': 'high', 'min': 'low'})
            return df
    except Exception as e:
        st.error(f"連線異常: {e}")
        pass
        
    return pd.DataFrame()

# =================================================================
# 🖥️ 4. 前端介面展示 (Streamlit)
# =================================================================
def main():
    st.set_page_config(page_title="台股 41 分量化評分系統", page_icon="🎯", layout="wide")
    
    st.title("🎯 台股 41 分量化評分系統")
    st.write("📊 評分邏輯：基本面與月營收動能 (21分) + 技術面籌碼 (20分) = 總分 41 分")
    
    raw_df = load_and_clean_data()
    monthly_df = load_monthly_revenue_data()
    mom_dict = calculate_monthly_mom_status(monthly_df)
    
    result_df = pd.DataFrame()
    
    if raw_df is not None and not raw_df.empty:
        result_df = calculate_fundamental_score(raw_df, mom_dict)
        
        if not result_df.empty:
            result_df = result_df.sort_values(by=['基本面評分 (滿分21)', '單季 EPS (元)'], ascending=[False, False]).reset_index(drop=True)
            high_score_df = result_df[result_df['基本面評分 (滿分21)'] >= 12]
            
            st.markdown("---")
            
            st.subheader(f"🏆 基本面與月營收優等生 (滿分 21 分，共 {len(high_score_df)} 檔 >= 12 分)")
            if not high_score_df.empty:
                styled_high_score = high_score_df.style.format({
                    "單季營收 (億元)": "{:.2f}",
                    "單季 EPS (元)": "{:.2f}",
                    "單季毛利率 (%)": "{:.2f}"
                }).bar(subset=['基本面評分 (滿分21)'], color='#20c997', vmin=-5, vmax=21)
                st.dataframe(styled_high_score)

            with st.expander(f"📂 點擊展開：查看全市場 {len(result_df)} 檔基本面初評總表"):
                st.dataframe(result_df)
        else:
            st.warning("無有效財報數據可供評分。")

        st.markdown("---")

        st.header("📈 個股 41 分總結算與技術分析")
        
        st.write("⚙️ **個股查詢與指標開關**")
        col_input, col_ma, col_bb, col_vol, col_macd = st.columns([1.5, 3, 1, 1, 1])
        
        with col_input:
            query_stock_raw = st.text_input("🔍 輸入代號並按 Enter", "2330")
            # 💡 防呆機制：不管使用者輸入 "2303 " 還是 "2303 聯電"，自動過濾只留下純數字 2303
            query_stock = query_stock_raw.split()[0].strip() if query_stock_raw else ""
            
        with col_ma:
            ma_options = st.multiselect(
                "📊 選擇顯示均線", 
                options=["5MA", "10MA", "20MA(月線)", "60MA(季線)"], 
                default=["5MA", "10MA", "20MA(月線)", "60MA(季線)"]
            )
        with col_bb:
            st.write(" ")
            show_bb = st.checkbox("顯示布林", value=True)
        with col_vol:
            st.write(" ")
            show_vol = st.checkbox("顯示成交量", value=True)
        with col_macd:
            st.write(" ")
            show_macd = st.checkbox("顯示 MACD", value=True)

        if query_stock:
            with st.spinner("即時運算技術指標與總分中..."):
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
                    
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2]
                    
                    tech_score = 0
                    t_details = []
                    
                    if latest['MACD_Hist'] > 0:
                        tech_score += 5
                        t_details.append("✅ MACD 柱狀體為紅色 (+5分)")
                    else:
                        t_details.append("❌ MACD 柱狀體非紅色 (0分)")
                        
                    if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal']:
                        tech_score += 10
                        t_details.append("🔥 MACD 出現黃金交叉 (+10分)")
                    else:
                        t_details.append("❌ MACD 未出現黃金交叉 (0分)")
                        
                    dist_upper = (latest['BB_upper'] - latest['close']) / latest['BB_upper']
                    dist_lower = (latest['close'] - latest['BB_lower']) / latest['BB_lower']
                    
                    if dist_upper <= 0.05 or dist_lower <= 0.05:
                        t_details.append("❌ 股價靠近布林通道邊緣 5% 內 (0分)")
                    else:
                        tech_score += 5
                        t_details.append("✅ 股價處於布林通道安全區間 (+5分)")

                    fund_score = 0
                    fund_details_str = "❌ 無基本面資料"
                    match_df = result_df[result_df['股票代號'].str.startswith(query_stock)]
                    
                    if not match_df.empty:
                        fund_score = match_df.iloc[0]['基本面評分 (滿分21)']
                        fund_details_str = match_df.iloc[0]['給分明細']
                        
                    total_score = fund_score + tech_score
                    
                    def get_final_rec(s):
                        if s >= 35: return "🔥 強力買進"
                        elif s >= 24: return "📈 買進"
                        elif s >= 12: return "⚖️ 普通"
                        elif s >= 0: return "📉 賣出"
                        else: return "❌ 強力賣出"

                    st.markdown(f"### 🏆 {query_stock} 綜合 41 分總結算報告")
                    colA, colB, colC = st.columns(3)
                    colA.metric("📊 基本面與月營收得分", f"{fund_score} / 21 分")
                    colB.metric("📈 技術面得分", f"{tech_score} / 20 分")
                    colC.metric("🎯 最終總評級", f"{total_score} 分", get_final_rec(total_score))
                    
                    with st.expander("📝 點此查看【基本面】與【技術面】給分明細"):
                        st.markdown("**【📊 基本面給分明細】**")
                        for item in fund_details_str.split(" | "):
                            st.write(item)
                            
                        st.markdown("---")
                        st.markdown("**【📈 技術面給分明細】**")
                        for item in t_details:
                            st.write(item)
                            
                    st.markdown("---")

                    display_df = hist.tail(120).copy()
                    dates = display_df['date'].tolist()
                    open_p, high_p, low_p, close_p = display_df['open'].tolist(), display_df['high'].tolist(), display_df['low'].tolist(), display_df['close'].tolist()
                    volumes = display_df['Trading_Volume'].tolist()
                    
                    ma5, ma10, ma20, ma60 = display_df['MA5'].tolist(), display_df['MA10'].tolist(), display_df['MA20'].tolist(), display_df['MA60'].tolist()
                    bb_upper, bb_lower = display_df['BB_upper'].tolist(), display_df['BB_lower'].tolist()
                    macd, signal, macd_hist = display_df['MACD'].tolist(), display_df['Signal'].tolist(), display_df['MACD_Hist'].tolist()
                    
                    stock_colors = ['#ef5350' if c >= o else '#26a69a' for c, o in zip(close_p, open_p)]
                    macd_colors = ['#ef5350' if val >= 0 else '#26a69a' for val in macd_hist]
                    
                    plot_rows = 1
                    row_heights = [0.6]
                    vol_row = macd_row = 0
                    
                    if show_vol:
                        plot_rows += 1; vol_row = plot_rows; row_heights.append(0.2)
                    if show_macd:
                        plot_rows += 1; macd_row = plot_rows; row_heights.append(0.2)
                        
                    total_height = sum(row_heights)
                    row_heights = [h/total_height for h in row_heights]

                    fig = make_subplots(rows=plot_rows, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=row_heights)
                    
                    fig.add_trace(go.Candlestick(x=dates, open=open_p, high=high_p, low=low_p, close=close_p, name="K線", increasing_line_color='#ef5350', decreasing_line_color='#26a69a'), row=1, col=1)
                    
                    if "5MA" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma5, line=dict(color='#ff9800', width=1.5), name='5MA'), row=1, col=1)
                    if "10MA" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma10, line=dict(color='#e91e63', width=1.5), name='10MA'), row=1, col=1)
                    if "20MA(月線)" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma20, line=dict(color='#2196f3', width=1.5), name='20MA'), row=1, col=1)
                    if "60MA(季線)" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma60, line=dict(color='#9c27b0', width=2), name='60MA'), row=1, col=1)
                    
                    if show_bb:
                        fig.add_trace(go.Scatter(x=dates, y=bb_upper, line=dict(color='rgba(158,158,158,0.5)', width=1, dash='dash'), name='布林上軌'), row=1, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=bb_lower, line=dict(color='rgba(158,158,158,0.5)', width=1, dash='dash'), fill='tonexty', fillcolor='rgba(158,158,158,0.1)', name='布林下軌'), row=1, col=1)

                    if show_vol:
                        fig.add_trace(go.Bar(x=dates, y=volumes, marker_color=stock_colors, name='成交量', orientation='v'), row=vol_row, col=1)
                        fig.update_yaxes(title_text="成交量", row=vol_row, col=1)

                    if show_macd:
                        fig.add_trace(go.Bar(x=dates, y=macd_hist, marker_color=macd_colors, name='MACD柱', orientation='v'), row=macd_row, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=macd, line=dict(color='#2196f3', width=1.5), name='快線'), row=macd_row, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=signal, line=dict(color='#ff9800', width=1.5), name='慢線'), row=macd_row, col=1)
                        fig.update_yaxes(title_text="MACD", row=macd_row, col=1)

                    fig.update_layout(
                        title=f"{query_stock} 技術線圖", xaxis_rangeslider_visible=False,
                        height=500 if plot_rows == 1 else (650 if plot_rows == 2 else 800),
                        margin=dict(l=0, r=0, t=40, b=0), hovermode="x unified",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    
                    for i in range(1, plot_rows + 1):
                        fig.update_yaxes(type='linear', row=i, col=1)
                        fig.update_xaxes(type='date', row=i, col=1)
                        if i < plot_rows: fig.update_xaxes(showticklabels=False, row=i, col=1)

                    all_dates = pd.date_range(start=display_df['date'].min(), end=display_df['date'].max())
                    missing_dates = all_dates.difference(display_df['date']).strftime("%Y-%m-%d").tolist()
                    for i in range(1, plot_rows + 1):
                        if missing_dates: fig.update_xaxes(rangebreaks=[dict(values=missing_dates)], row=i, col=1)

                    st.plotly_chart(fig, use_container_width=True)
                else:
                    # 如果不是額度滿了，就給這個一般錯誤
                    if not "Too Many Requests" in globals().get('data', {}).get("msg", ""):
                        st.warning(f"找不到 {query_stock} 的技術資料，請確認代號是否正確。")

if __name__ == "__main__":
    main()

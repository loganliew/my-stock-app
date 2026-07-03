import streamlit as st
import pandas as pd
import os
import requests
import plotly.graph_objects as go
from datetime import datetime, timedelta

# 🔑 讀取名稱對照表專用的 API 通行證
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibG9nYW5saWV3IiwiZW1haWwiOiJzMjI3MDIyMjZAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.j2WUIuC7PJGNKSwAviyTbj0bwuq8AJUmd4rWVQ9rUOY" 

# =================================================================
# 🔍 0. 智慧快取：線上獲取股票代號與中文名稱對照表
# =================================================================
@st.cache(ttl=86400) # 快取 24 小時
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
        st.error(f"找不到檔案：{file_path}，請確認資料存在。")
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
        st.warning("檔案讀取失敗或裡面沒有有效資料。")
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
        
    except Exception as e:
        st.error(f"資料清洗時發生錯誤：{e}")
        return None

# =================================================================
# 🧮 2. 基本面分數計算機 (加入毛利率與操作建議)
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
        if score >= 90:
            return "🔥 強力買進"
        elif score >= 70:
            return "📈 買進"
        elif score >= 60:
            return "⚖️ 普通"
        elif score >= 30:
            return "📉 賣出"
        else:
            return "❌ 強力賣出"
            
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
    """使用 FinMind 抓取股價，完全避開 yfinance 的不穩定與 IP 封鎖問題"""
    url = "https://api.finmindtrade.com/api/v4/data"
    # 往回抓 200 天，確保有足夠的資料來算出 60 日季線
    start_date = (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')
    
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
            # 將 FinMind 的欄位名稱轉換為畫圖需要的格式
            df = df.rename(columns={'max': 'high', 'min': 'low'})
            return df
    except Exception as e:
        st.error(f"股價 API 請求錯誤: {e}")
    return pd.DataFrame()

# =================================================================
# 🖥️ 4. 前端介面展示 (Streamlit)
# =================================================================
def main():
    st.set_page_config(page_title="台股財報量化看盤", page_icon="📈", layout="wide")
    
    st.title("📈 台股量化看盤系統 (基本面 + 技術面)")
    st.write("資料來源：GitHub Actions 自動抓取之 `tw_eps_revenue.csv` (已自動對接中文名稱與評級標籤)")
    
    raw_df = load_and_clean_data()
    
    if raw_df is not None and not raw_df.empty:
        result_df = calculate_fundamental_score(raw_df)
        result_df = result_df.sort_values(by=['Score', '單季 EPS (元)'], ascending=[False, False]).reset_index(drop=True)
        high_score_df = result_df[result_df['Score'] >= 70]
        
        st.markdown("---")
        
        # 🏆 第一區塊：高分強勢股
        st.subheader(f"🏆 嚴選潛力股清單 (共 {len(high_score_df)} 檔)")
        st.write("💡 **過濾條件**：綜合評分 >= 70 分 (對應【強力買進】與【買進】級別)。")
        
        if not high_score_df.empty:
            styled_high_score = high_score_df.style.format({
                "單季營收 (億元)": "{:.2f}",
                "單季 EPS (元)": "{:.2f}",
                "單季毛利率 (%)": "{:.2f}" if "單季毛利率 (%)" in high_score_df.columns else "{}"
            }).bar(subset=['Score'], color='#20c997', vmin=0, vmax=100)
            st.dataframe(styled_high_score)
        else:
            st.warning("目前最新一季沒有符合 >= 70 分標準的標的。")

        st.markdown("---")

        # 📊 第二區塊：全市場總表
        with st.expander(f"📂 點擊展開：查看全市場 {len(result_df)} 檔股票評分總表"):
            st.write("這裡是所有抓取到的股票資料，已為您依【股票代號】排序，並完整標註五大建議等級：")
            all_market_df = result_df.sort_values(by='股票代號').reset_index(drop=True)
            styled_all = all_market_df.style.format({
                "單季營收 (億元)": "{:.2f}",
                "單季 EPS (元)": "{:.2f}",
                "單季毛利率 (%)": "{:.2f}" if "單季毛利率 (%)" in all_market_df.columns else "{}"
            }).bar(subset=['Score'], color='#6c757d', vmin=0, vmax=100)
            st.dataframe(styled_all)

        st.markdown("---")

        # ==========================================
        # 📈 第三區塊：個股技術面分析 (FinMind 互動線圖)
        # ==========================================
        st.header("📈 個股技術面分析 (K線與均線)")
        st.write("輸入股票代號並 **按下 Enter (回車鍵)**，即時抓取最新近半年的技術線圖：")
        
        col1, col2 = st.columns([1, 3])
        with col1:
            query_stock = st.text_input("🔍 輸入代號 (例如：2330)", "2330")
            
        if query_stock:
            with st.spinner("載入線圖中..."):
                # 改呼叫我們自己寫好的 FinMind 爬蟲
                hist = fetch_stock_price(query_stock)
                
                if not hist.empty:
                    # 計算均線
                    hist['MA20'] = hist['close'].rolling(window=20).mean()
                    hist['MA60'] = hist['close'].rolling(window=60).mean()
                    
                    # 只取最後 120 天(約半年)的資料來畫圖，畫面最乾淨好看
                    display_df = hist.tail(120).copy()
                    
                    dates = display_df['date'].tolist()
                    open_p = display_df['open'].tolist()
                    high_p = display_df['high'].tolist()
                    low_p = display_df['low'].tolist()
                    close_p = display_df['close'].tolist()
                    ma20 = display_df['MA20'].tolist()
                    ma60 = display_df['MA60'].tolist()
                    
                    fig = go.Figure(data=[go.Candlestick(x=dates,
                                    open=open_p, high=high_p, low=low_p, close=close_p,
                                    name="K線")])
                    
                    fig.add_trace(go.Scatter(x=dates, y=ma20, line=dict(color='orange', width=1.5), name='月線 (20MA)'))
                    fig.add_trace(go.Scatter(x=dates, y=ma60, line=dict(color='blue', width=1.5), name='季線 (60MA)'))
                    
                    fig.update_layout(
                        title=f"{query_stock} 近半年走勢圖", 
                        xaxis_rangeslider_visible=False,
                        xaxis_type='category', # 👈 強制設定為類別，讓 K 線連續不中斷，完美略過六日
                        height=550,
                        margin=dict(l=0, r=0, t=40, b=0)
                    )
                    
                    # 避免下方日期標籤全部擠在一起
                    fig.update_xaxes(nticks=10)
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning(f"找不到 {query_stock} 的技術資料，請確認代號是否正確。")

if __name__ == "__main__":
    main()

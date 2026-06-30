import streamlit as st
import pandas as pd
import os
import requests

# 🔑 讀取名稱對照表專用的 API 通行證 (對接你的 Token)
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibG9nYW5saWV3IiwiZW1haWwiOiJzMjI3MDIyMjZAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.j2WUIuC7PJGNKSwAviyTbj0bwuq8AJUmd4rWVQ9rUOY" 

# =================================================================
# 🔍 0. 智慧快取：線上獲取股票代號與中文名稱對照表
# =================================================================
@st.cache(ttl=86400) # 快取 24 小時，確保網頁重新整理時不用重複向 API 要資料，速度極快
def load_stock_name_map():
    """從 FinMind API 獲取最新的台股代號與中文名稱對照字典"""
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockInfo", "token": FINMIND_TOKEN}
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if data.get("msg") == "success":
            # 建立一個 { "2330": "台積電", "2317": "鴻海" } 的對照字典
            return {str(item['stock_id']): str(item['stock_name']) for item in data['data']}
    except Exception:
        pass # 如果 API 暫時斷線，優雅略過，不影響網頁開啟
    return {}

# =================================================================
# 📂 1. 資料讀取與清洗區
# =================================================================
def load_and_clean_data():
    """讀取 Github Actions 爬下來的真實財報資料並融合中文名稱"""
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
        # 確保代號為字串格式
        df['股票代號'] = df['股票代號'].astype(str)
        df = df.sort_values(by=['股票代號', '季度名稱'])
        latest_df = df.drop_duplicates(subset=['股票代號'], keep='last').copy()
        
        # 💡 【核心修改】: 自動查表並把中文名稱融入「股票代號」框框中
        name_map = load_stock_name_map()
        if name_map:
            # 將原本的 "2330" 變成 "2330 台積電"
            latest_df['股票代號'] = latest_df['股票代號'].apply(
                lambda x: f"{x} {name_map.get(x, '')}".strip()
            )
            
        return latest_df
        
    except Exception as e:
        st.error(f"資料清洗時發生錯誤：{e}")
        return None

# =================================================================
# 🧮 2. 基本面分數計算機 (基於 EPS 與營收)
# =================================================================
def calculate_fundamental_score(df):
    """根據最新的 EPS 與 營收 計算總分 (滿分 100)"""
    scored_df = df.copy()
    scored_df['Score'] = 0
    
    scored_df.loc[scored_df['單季 EPS (元)'] > 0, 'Score'] += 40
    scored_df.loc[scored_df['單季 EPS (元)'] >= 2, 'Score'] += 30
    scored_df.loc[scored_df['單季營收 (億元)'] > 50, 'Score'] += 30
    
    return scored_df

# =================================================================
# 🖥️ 3. 前端介面展示 (Streamlit)
# =================================================================
def main():
    st.set_page_config(page_title="台股財報量化看盤", page_icon="📈", layout="wide")
    
    st.title("📈 台股財報量化看盤系統")
    st.header("📊 最新季度財報分析與評分")
    st.write("資料來源：GitHub Actions 自動抓取之 `tw_eps_revenue.csv` (已自動對接中文名稱)")
    
    raw_df = load_and_clean_data()
    
    if raw_df is not None and not raw_df.empty:
        result_df = calculate_fundamental_score(raw_df)
        result_df = result_df.sort_values(by=['Score', '單季 EPS (元)'], ascending=[False, False]).reset_index(drop=True)
        
        high_score_df = result_df[result_df['Score'] >= 70]
        
        st.markdown("---")
        
        # ==========================================
        # 🏆 第一區塊：高分強勢股
        # ==========================================
        st.subheader(f"🏆 嚴選潛力股清單 (共 {len(high_score_df)} 檔)")
        st.write("💡 **過濾條件**：綜合評分 >= 70 分。以下清單已自動依據 EPS 高低為您排序。")
        
        if not high_score_df.empty:
            styled_high_score = high_score_df.style.format({
                "單季營收 (億元)": "{:.2f}",
                "單季 EPS (元)": "{:.2f}"
            }).bar(
                subset=['Score'], 
                color='#20c997', 
                vmin=0, 
                vmax=100
            )
            st.dataframe(styled_high_score)
        else:
            st.warning("目前最新一季沒有符合 >= 70 分標準的標的。")

        st.markdown("---")

        # ==========================================
        # 📊 第二區塊：全市場總表
        # ==========================================
        with st.expander(f"📂 點擊展開：查看全市場 {len(result_df)} 檔股票評分總表"):
            st.write("這裡是所有抓取到的股票資料，已為您改為【依股票代號排序】，方便您尋找特定標的：")
            
            # 💡 關鍵修正：把全市場的表格改回用「股票代號」從小到大排序
            all_market_df = result_df.sort_values(by='股票代號').reset_index(drop=True)
            
            styled_all = all_market_df.style.format({
                "單季營收 (億元)": "{:.2f}",
                "單季 EPS (元)": "{:.2f}"
            }).bar(
                subset=['Score'], 
                color='#6c757d', 
                vmin=0, 
                vmax=100
            )
            st.dataframe(styled_all)

if __name__ == "__main__":
    main()

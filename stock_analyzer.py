import streamlit as st
import pandas as pd
import os
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# 🔑 讀取名稱對照表與即時資料專用的 API 通行證
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibG9nYW5saWV3IiwiZW1haWwiOiJsb2dhbl9saWFvQGNvbXBhbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.SDAxrNB7rCB7svBIRokVAzwbk3Ib3V82HP-ulzQbFbo" 

# =================================================================
# 🔍 0. 智慧快取：線上獲取股票代號與中文名稱對照表
# =================================================================
@st.cache(ttl=86400, allow_output_mutation=True)
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
# 🧮 2. 第一階段：基本面評分 (動態權重版)
# =================================================================
def calculate_fundamental_score(df, mom_dict, w):
    scores = []
    
    for stock, group in df.groupby('股票代號'):
        group = group.sort_values('季度名稱')
        if len(group) == 0: continue
        
        valid_group = group[group['季度名稱'] != '無資料']
        if valid_group.empty: continue
        
        curr = valid_group.iloc[-1] 
        prev = valid_group.iloc[-2] if len(valid_group) > 1 else None 
        
        ttm_eps = valid_group['單季 EPS (元)'].tail(4).sum()
        
        score = 0
        details = [] 
        
        if curr['單季 EPS (元)'] > 0: 
            score += w['eps_p']; details.append(f"✅ EPS > 0 (+{w['eps_p']}分)")
        else: 
            score += w['eps_f']; details.append(f"❌ EPS <= 0 ({w['eps_f']}分)")
            
        if prev is not None and curr['單季營收 (億元)'] > prev['單季營收 (億元)']:
            score += w['rev_qoq']; details.append(f"✅ 季度營收呈季增 (+{w['rev_qoq']}分)")
        else:
            details.append("❌ 季度營收無季增 (0分)")
            
        if prev is not None and '單季毛利率 (%)' in curr and '單季毛利率 (%)' in prev:
            if curr['單季毛利率 (%)'] > prev['單季毛利率 (%)']:
                score += w['gm_qoq']; details.append(f"✅ 毛利率季增 (+{w['gm_qoq']}分)")
            else:
                details.append("❌ 毛利率無季增 (0分)")
        else:
            details.append("❌ 缺毛利率資料 (0分)")
            
        raw_stock_id = stock.split()[0]
        if raw_stock_id in mom_dict:
            is_growth, month_name = mom_dict[raw_stock_id]
            if is_growth:
                score += w['rev_mom']; details.append(f"✅ 月營收動能：{month_name} 營收 > 前月 (+{w['rev_mom']}分)")
            else:
                details.append(f"❌ 月營收動能：{month_name} 營收 <= 前月 (0分)")
        else:
            details.append("❌ 缺最新月營收對比資料 (0分)")
                
        scores.append({
            '股票代號': stock,
            '季度名稱': curr['季度名稱'],
            '單季 EPS (元)': curr['單季 EPS (元)'],
            '近四季EPS總和': ttm_eps, 
            '單季營收 (億元)': curr['單季營收 (億元)'],
            '單季毛利率 (%)': curr.get('單季毛利率 (%)', 0),
            '基本面評分': score,
            '給分明細': " | ".join(details) 
        })
        
    if not scores:
        return pd.DataFrame()
        
    scored_df = pd.DataFrame(scores)
    
    # 依據動態權重決定基本面初評門檻
    max_fund = w['eps_p'] + w['rev_qoq'] + w['gm_qoq'] + w['rev_mom']
    def get_fund_rec(s):
        if s >= max_fund * 0.8: return "🔥 強力買進"
        elif s >= max_fund * 0.5: return "📈 買進"
        elif s >= max_fund * 0.2: return "⚖️ 普通"
        elif s >= 0: return "📉 賣出"
        else: return "❌ 強力賣出"
            
    scored_df['基本面初評'] = scored_df['基本面評分'].apply(get_fund_rec)
    
    cols = list(scored_df.columns)
    cols.insert(cols.index('基本面初評') + 1, cols.pop(cols.index('給分明細')))
    scored_df = scored_df[cols]
    
    return scored_df

# =================================================================
# 📊 3. API 爬蟲區 
# =================================================================
@st.cache(ttl=43200, allow_output_mutation=True)
def fetch_stock_price(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (datetime.now() - timedelta(days=3650)).strftime('%Y-%m-%d')
    params = {"dataset": "TaiwanStockPrice", "data_id": str(stock_id), "start_date": start_date, "token": FINMIND_TOKEN}
    try:
        res = requests.get(url, params=params, timeout=15) 
        if res.status_code == 402: return pd.DataFrame(), "HTTP 402：API 額度已耗盡！"
        if res.status_code != 200: return pd.DataFrame(), f"HTTP {res.status_code} 錯誤"
        data = res.json()
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            df = pd.DataFrame(data["data"]).rename(columns={'max': 'high', 'min': 'low'})
            return df, "success"
        return pd.DataFrame(), "無近期交易資料"
    except Exception as e:
        return pd.DataFrame(), f"連線異常: {e}"

@st.cache(ttl=43200, allow_output_mutation=True)
def fetch_chip_data(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d')
    params = {"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": str(stock_id), "start_date": start_date, "token": FINMIND_TOKEN}
    try:
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 402: return pd.DataFrame(), "HTTP 402：API 額度已耗盡！"
        if res.status_code != 200: return pd.DataFrame(), f"HTTP {res.status_code} 錯誤"
        data = res.json()
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            return pd.DataFrame(data["data"]), "success"
        return pd.DataFrame(), "無近期籌碼資料"
    except Exception as e:
        return pd.DataFrame(), f"連線異常: {e}"

# =================================================================
# 🖥️ 4. 前端介面展示 (Streamlit)
# =================================================================
def main():
    st.set_page_config(page_title="台股量化策略實驗室", page_icon="🎯", layout="wide")
    
    # ==========================================
    # ⚙️ 側邊欄：自訂權重參數設定區
    # ==========================================
    st.sidebar.header("⚙️ 策略權重設定面板")
    st.sidebar.write("自由調整各項指標分數，打造你的專屬策略！")
    
    w = {} # 裝載所有權重的字典
    
    with st.sidebar.expander("📊 基本面與營收動能", expanded=False):
        w['eps_p'] = st.number_input("✅ EPS > 0 加分", value=5, step=1)
        w['eps_f'] = st.number_input("❌ EPS <= 0 扣分", value=-5, step=1)
        w['rev_qoq'] = st.number_input("✅ 營收季增 加分", value=5, step=1)
        w['gm_qoq'] = st.number_input("✅ 毛利季增 加分", value=5, step=1)
        w['rev_mom'] = st.number_input("✅ 月營收月增 加分", value=6, step=1)

    with st.sidebar.expander("📈 估值、大底與技術面", expanded=False):
        st.write("**估值判斷**")
        w['pe_safe'] = st.number_input("✅ 本益比 < 20 加分", value=10, step=1)
        w['pe_warn'] = st.number_input("✅ 本益比 20~25 加分", value=3, step=1)
        st.write("**歷史大底判定**")
        w['btm_break'] = st.number_input("🚀 突破 10年大底 加分", value=25, step=1)
        w['btm_above'] = st.number_input("✅ 在 10年大底之上 加分", value=2, step=1)
        w['btm_below'] = st.number_input("⚠️ 跌破 10年大底 扣分", value=-5, step=1)
        st.write("**短期技術面**")
        w['macd_hist'] = st.number_input("✅ MACD 紅柱 加分", value=5, step=1)
        w['macd_gc'] = st.number_input("🔥 MACD 黃金交叉 加分", value=10, step=1)
        w['bb_safe'] = st.number_input("✅ 布林安全區 加分", value=5, step=1)

    with st.sidebar.expander("🏦 法人籌碼動向", expanded=False):
        st.write("**外資動向**")
        w['fb_10'] = st.number_input("外資連買 >= 10天 加分", value=10, step=1)
        w['fb_5'] = st.number_input("外資連買 >= 5天 加分", value=5, step=1)
        w['fb_3'] = st.number_input("外資連買 >= 3天 加分", value=2, step=1)
        w['fs_10'] = st.number_input("外資連賣 >= 10天 扣分", value=-10, step=1)
        w['fs_5'] = st.number_input("外資連賣 >= 5天 扣分", value=-5, step=1)
        w['fs_3'] = st.number_input("外資連賣 >= 3天 扣分", value=-2, step=1)
        st.write("**投信動向**")
        w['tb_10'] = st.number_input("投信連買 >= 10天 加分", value=7, step=1)
        w['tb_5'] = st.number_input("投信連買 >= 5天 加分", value=3, step=1)
        w['tb_3'] = st.number_input("投信連買 >= 3天 加分", value=1, step=1)
        w['ts_10'] = st.number_input("投信連賣 >= 10天 扣分", value=-7, step=1)
        w['ts_5'] = st.number_input("投信連賣 >= 5天 扣分", value=-3, step=1)
        w['ts_3'] = st.number_input("投信連賣 >= 3天 扣分", value=-1, step=1)

    # 動態計算理論滿分
    max_fund = w['eps_p'] + w['rev_qoq'] + w['gm_qoq'] + w['rev_mom']
    max_tech = w['pe_safe'] + w['btm_break'] + w['macd_hist'] + w['macd_gc'] + w['bb_safe']
    max_chip = w['fb_10'] + w['tb_10']
    total_max = max_fund + max_tech + max_chip

    st.sidebar.markdown("---")
    st.sidebar.success(f"🏆 當前策略理論滿分：**{total_max} 分**")

    # ==========================================
    # 🎯 主畫面區塊
    # ==========================================
    st.title(f"🎯 台股 {total_max} 分自訂量化策略實驗室")
    st.write(f"📊 動態配分：基本面({max_fund}) + 估值與技術({max_tech}) + 籌碼({max_chip}) = 總分 {total_max} 分")
    
    raw_df = load_and_clean_data()
    monthly_df = load_monthly_revenue_data()
    mom_dict = calculate_monthly_mom_status(monthly_df)
    
    result_df = pd.DataFrame()
    
    if raw_df is not None and not raw_df.empty:
        result_df = calculate_fundamental_score(raw_df, mom_dict, w)
        
        if not result_df.empty:
            result_df = result_df.sort_values(by=['基本面評分', '單季 EPS (元)'], ascending=[False, False]).reset_index(drop=True)
            # 動態快篩門檻：基本面拿滿分的 60% 才入選
            filter_threshold = int(max_fund * 0.6)
            high_score_df = result_df[result_df['基本面評分'] >= filter_threshold]
            
            st.markdown("---")
            
            st.subheader(f"🏆 策略優等生快篩 (門檻 {filter_threshold} 分，共 {len(high_score_df)} 檔達標)")
            if not high_score_df.empty:
                styled_high_score = high_score_df.style.format({
                    "單季營收 (億元)": "{:.2f}",
                    "單季 EPS (元)": "{:.2f}",
                    "單季毛利率 (%)": "{:.2f}",
                    "近四季EPS總和": "{:.2f}"
                }).bar(subset=['基本面評分'], color='#20c997', vmin=0, vmax=max_fund)
                
                styled_high_score = styled_high_score.hide(subset=["近四季EPS總和"], axis="columns")
                st.dataframe(styled_high_score)

            with st.expander(f"📂 點擊展開：查看全市場 {len(result_df)} 檔基本面初評總表"):
                st.dataframe(result_df.drop(columns=['近四季EPS總和']))
        else:
            st.warning("無有效財報數據可供評分。")

        st.markdown("---")

        st.header(f"📈 個股 {total_max} 分總結算與技術籌碼分析")
        
        st.write("⚙️ **個股查詢與指標開關**")
        col_input, col_ma, col_bb, col_vol, col_macd, col_lt = st.columns([1.5, 2.5, 0.8, 1, 0.8, 1.5])
        
        with col_input:
            query_stock_raw = st.text_input("🔍 輸入代號並按 Enter", "2324")
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
            show_macd = st.checkbox("顯示 MACD", value=False)
        with col_lt:
            st.write(" ")
            show_long_term = st.checkbox("顯示10年大底/成本", value=True)

        if query_stock:
            with st.spinner("即時調閱歷史數據，運算大底突破與技術指標中..."):
                hist_raw, api_msg = fetch_stock_price(query_stock)
                chip_raw, chip_msg = fetch_chip_data(query_stock) 
                
                if not hist_raw.empty:
                    hist = hist_raw.copy()
                    
                    numeric_cols = ['open', 'high', 'low', 'close', 'Trading_Volume']
                    hist[numeric_cols] = hist[numeric_cols].apply(pd.to_numeric, errors='coerce')
                    hist['Trading_Volume'] = hist['Trading_Volume'].fillna(0)
                    
                    hist['date'] = pd.to_datetime(hist['date'])
                    hist = hist.sort_values('date').dropna(subset=['close']).reset_index(drop=True)
                    
                    ten_year_low = hist['low'].min()
                    
                    clean_hist = hist.dropna(subset=['close', 'Trading_Volume'])
                    if not clean_hist.empty:
                        hist_bins = pd.cut(clean_hist['close'], bins=50)
                        vol_by_bin = clean_hist.groupby(hist_bins, observed=False)['Trading_Volume'].sum()
                        max_vol_bin = vol_by_bin.idxmax()
                        poc_price = max_vol_bin.mid
                    else:
                        poc_price = hist['close'].mean()
                    
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
                    
                    # === 【1. 估值計算】 ===
                    match_df = result_df[result_df['股票代號'].str.startswith(query_stock)]
                    ttm_eps = match_df.iloc[0]['近四季EPS總和'] if not match_df.empty else 0
                    close_price = latest['close']
                    
                    if ttm_eps > 0:
                        pe_ratio = close_price / ttm_eps
                        if pe_ratio < 20:
                            tech_score += w['pe_safe']; t_details.append(f"✅ 估值安全：本益比 {pe_ratio:.1f} 倍 < 20 (+{w['pe_safe']}分)")
                        elif pe_ratio < 25:
                            tech_score += w['pe_warn']; t_details.append(f"✅ 估值合理：本益比 {pe_ratio:.1f} 倍介於 20~25 (+{w['pe_warn']}分)")
                        else:
                            t_details.append(f"❌ 估值偏高：本益比 {pe_ratio:.1f} 倍 >= 25 (0分)")
                    else:
                        t_details.append("❌ 近四季 EPS 為負值或無資料，無法計算本益比 (0分)")
                        
                    # === 【2. 大底突破判定】 ===
                    is_breakout = False
                    for line in [ten_year_low, poc_price]:
                        if prev['close'] <= line and latest['close'] > line:
                            is_breakout = True
                            break
                            
                    if is_breakout:
                        tech_score += w['btm_break']
                        t_details.append(f"🚀 絕佳買點：股價今日強勢突破 10 年大底/成本線！(+{w['btm_break']}分)")
                    elif latest['close'] < poc_price:
                        tech_score += w['btm_below']
                        t_details.append(f"⚠️ 破底危機：股價落入 10 年大底成本區以下 ({w['btm_below']}分)")
                    elif latest['close'] > max(ten_year_low, poc_price):
                        tech_score += w['btm_above']
                        t_details.append(f"✅ 長線多頭：股價穩居 10 年大底與主力成本之上 (+{w['btm_above']}分)")
                    else:
                        t_details.append("➖ 底部震盪：股價正處於歷史谷底與成本線之間 (0分)")
                    
                    # === 【3. 技術面計算】 ===
                    if latest['MACD_Hist'] > 0:
                        tech_score += w['macd_hist']; t_details.append(f"✅ 技術動能：MACD 柱狀體為紅色 (+{w['macd_hist']}分)")
                    else:
                        t_details.append("❌ 技術動能：MACD 柱狀體非紅色 (0分)")
                        
                    if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal']:
                        tech_score += w['macd_gc']; t_details.append(f"🔥 技術訊號：MACD 出現黃金交叉 (+{w['macd_gc']}分)")
                    else:
                        t_details.append("❌ 技術訊號：MACD 未出現黃金交叉 (0分)")
                        
                    dist_upper = (latest['BB_upper'] - latest['close']) / latest['BB_upper']
                    dist_lower = (latest['close'] - latest['BB_lower']) / latest['BB_lower']
                    if dist_upper <= 0.05 or dist_lower <= 0.05:
                        t_details.append("❌ 技術位置：股價靠近布林通道邊緣 5% 內 (0分)")
                    else:
                        tech_score += w['bb_safe']; t_details.append(f"✅ 技術位置：股價處於布林通道安全區間 (+{w['bb_safe']}分)")

                    # === 【4. 籌碼面計算】 ===
                    chip_score = 0
                    c_details = []
                    
                    if not chip_raw.empty:
                        chip_df = chip_raw.copy()
                        
                        chip_df['buy'] = pd.to_numeric(chip_df['buy'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                        chip_df['sell'] = pd.to_numeric(chip_df['sell'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                        chip_df['date'] = pd.to_datetime(chip_df['date'])
                        chip_df['net'] = chip_df['buy'] - chip_df['sell']
                        
                        f_df = chip_df[chip_df['name'].astype(str).str.contains('外資|陸資|Foreign', case=False, na=False)]
                        t_df = chip_df[chip_df['name'].astype(str).str.contains('投信|Trust|Investment', case=False, na=False)]
                        
                        f_daily = f_df.groupby('date')['net'].sum().sort_index(ascending=False)
                        t_daily = t_df.groupby('date')['net'].sum().sort_index(ascending=False)
                        
                        def count_consecutive(daily_series):
                            if daily_series.empty: return 0, 'none'
                            latest_net = daily_series.iloc[0]
                            if latest_net == 0: return 0, 'none'
                            direction = 'buy' if latest_net > 0 else 'sell'
                            count = 0
                            for val in daily_series:
                                if direction == 'buy' and val > 0: count += 1
                                elif direction == 'sell' and val < 0: count += 1
                                else: break
                            return count, direction
                        
                        f_count, f_dir = count_consecutive(f_daily)
                        t_count, t_dir = count_consecutive(t_daily)
                        
                        if f_dir == 'buy':
                            if f_count >= 10: chip_score += w['fb_10']; c_details.append(f"🔥 外資連續買超 {f_count} 天 (+{w['fb_10']}分)")
                            elif f_count >= 5: chip_score += w['fb_5']; c_details.append(f"✅ 外資連續買超 {f_count} 天 (+{w['fb_5']}分)")
                            elif f_count >= 3: chip_score += w['fb_3']; c_details.append(f"✅ 外資連續買超 {f_count} 天 (+{w['fb_3']}分)")
                            else: c_details.append(f"➖ 外資連續買超 {f_count} 天 (未達3天，0分)")
                        elif f_dir == 'sell':
                            if f_count >= 10: chip_score += w['fs_10']; c_details.append(f"❌ 外資連續賣超 {f_count} 天 ({w['fs_10']}分)")
                            elif f_count >= 5: chip_score += w['fs_5']; c_details.append(f"❌ 外資連續賣超 {f_count} 天 ({w['fs_5']}分)")
                            elif f_count >= 3: chip_score += w['fs_3']; c_details.append(f"❌ 外資連續賣超 {f_count} 天 ({w['fs_3']}分)")
                            else: c_details.append(f"➖ 外資連續賣超 {f_count} 天 (未達3天，0分)")
                        else: c_details.append("➖ 外資近期無連續買賣超 (0分)")
                            
                        if t_dir == 'buy':
                            if t_count >= 10: chip_score += w['tb_10']; c_details.append(f"🔥 投信連續買超 {t_count} 天 (+{w['tb_10']}分)")
                            elif t_count >= 5: chip_score += w['tb_5']; c_details.append(f"✅ 投信連續買超 {t_count} 天 (+{w['tb_5']}分)")
                            elif t_count >= 3: chip_score += w['tb_3']; c_details.append(f"✅ 投信連續買超 {t_count} 天 (+{w['tb_3']}分)")
                            else: c_details.append(f"➖ 投信連續買超 {t_count} 天 (未達3天，0分)")
                        elif t_dir == 'sell':
                            if t_count >= 10: chip_score += w['ts_10']; c_details.append(f"❌ 投信連續賣超 {t_count} 天 ({w['ts_10']}分)")
                            elif t_count >= 5: chip_score += w['ts_5']; c_details.append(f"❌ 投信連續賣超 {t_count} 天 ({w['ts_5']}分)")
                            elif t_count >= 3: chip_score += w['ts_3']; c_details.append(f"❌ 投信連續賣超 {t_count} 天 ({w['ts_3']}分)")
                            else: c_details.append(f"➖ 投信連續賣超 {t_count} 天 (未達3天，0分)")
                        else: c_details.append("➖ 投信近期無連續買賣超 (0分)")
                    else:
                        c_details.append("⚠️ 無近期法人籌碼資料，或 API 額度耗盡 (0分)")

                    fund_score = match_df.iloc[0]['基本面評分'] if not match_df.empty else 0
                    fund_details_str = match_df.iloc[0]['給分明細'] if not match_df.empty else "❌ 無基本面資料"
                        
                    total_score = fund_score + tech_score + chip_score
                    
                    # 💡 自動依照你設定的總分比例，計算出嚴格的評級標準
                    def get_final_rec(s):
                        if s >= total_max * 0.8: return "🔥 強力買進"
                        elif s >= total_max * 0.55: return "📈 買進"
                        elif s >= total_max * 0.3: return "⚖️ 普通"
                        elif s >= 0: return "📉 賣出"
                        else: return "❌ 強力賣出"

                    st.markdown(f"### 🏆 {query_stock} 綜合 {total_max} 分總結算報告")
                    
                    colA, colB, colC, colD = st.columns(4)
                    colA.metric("📊 基本面動能", f"{fund_score} / {max_fund} 分")
                    colB.metric("📈 估值與技術", f"{tech_score} / {max_tech} 分")
                    colC.metric("🏦 法人籌碼", f"{chip_score} / {max_chip} 分")
                    colD.metric("🎯 最終總評級", f"{total_score} 分", get_final_rec(total_score))
                    
                    with st.expander("📝 點此查看【基本面】、【大底與技術面】與【籌碼面】給分明細"):
                        col_dt1, col_dt2 = st.columns(2)
                        with col_dt1:
                            st.markdown("**【📊 基本面與營收動能】**")
                            for item in fund_details_str.split(" | "): st.write(item)
                        with col_dt2:
                            st.markdown("**【📈 估值、大底與技術面】**")
                            for item in t_details: st.write(item)
                            st.markdown("---")
                            st.markdown("**【🏦 三大法人籌碼面】**")
                            for item in c_details: st.write(item)
                            
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
                    
                    plot_rows = 1; row_heights = [0.6]; vol_row = macd_row = 0
                    if show_vol: plot_rows += 1; vol_row = plot_rows; row_heights.append(0.2)
                    if show_macd: plot_rows += 1; macd_row = plot_rows; row_heights.append(0.2)
                        
                    total_height = sum(row_heights); row_heights = [h/total_height for h in row_heights]
                    fig = make_subplots(rows=plot_rows, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=row_heights)
                    
                    fig.add_trace(go.Candlestick(x=dates, open=open_p, high=high_p, low=low_p, close=close_p, name="K線", increasing_line_color='#ef5350', decreasing_line_color='#26a69a'), row=1, col=1)
                    
                    if "5MA" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma5, line=dict(color='#ff9800', width=1.5), name='5MA'), row=1, col=1)
                    if "10MA" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma10, line=dict(color='#e91e63', width=1.5), name='10MA'), row=1, col=1)
                    if "20MA(月線)" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma20, line=dict(color='#2196f3', width=1.5), name='20MA'), row=1, col=1)
                    if "60MA(季線)" in ma_options: fig.add_trace(go.Scatter(x=dates, y=ma60, line=dict(color='#9c27b0', width=2), name='60MA'), row=1, col=1)
                    
                    if show_bb:
                        fig.add_trace(go.Scatter(x=dates, y=bb_upper, line=dict(color='rgba(158,158,158,0.5)', width=1, dash='dash'), name='布林上軌'), row=1, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=bb_lower, line=dict(color='rgba(158,158,158,0.5)', width=1, dash='dash'), fill='tonexty', fillcolor='rgba(158,158,158,0.1)', name='布林下軌'), row=1, col=1)

                    if show_long_term:
                        fig.add_trace(go.Scatter(x=dates, y=[ten_year_low]*len(dates), line=dict(color='#00e676', width=2, dash='dashdot'), name=f'10年歷史大底 ({ten_year_low:.2f})'), row=1, col=1)
                        fig.add_trace(go.Scatter(x=dates, y=[poc_price]*len(dates), line=dict(color='#d50000', width=2, dash='dashdot'), name=f'10年主力成本區 ({poc_price:.2f})'), row=1, col=1)

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
                    if "402" in api_msg or "limit" in api_msg.lower() or "too many" in api_msg.lower():
                        st.error(f"🛑 【系統提示】{api_msg}")
                    elif api_msg == "該股票代號無近期交易資料":
                        st.warning(f"找不到 {query_stock} 的技術資料，請確認該代號是否正確。")
                    else:
                        st.warning(f"無法獲取 {query_stock} 的技術資料 (伺服器回傳: {api_msg})")

if __name__ == "__main__":
    main()

import requests
import pandas as pd
import time
import os
import sys
from datetime import datetime

# =================================================================
# 📂 1. 設定存檔路徑
# =================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
CSV_FILE_PATH = os.path.join(DATA_DIR, 'tw_eps_revenue.csv')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibG9nYW5saWV3IiwiZW1haWwiOiJzMjI3MDIyMjZAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.j2WUIuC7PJGNKSwAviyTbj0bwuq8AJUmd4rWVQ9rUOY" 

# =================================================================
# 🤖 2. 獲取全市場名單 & 智慧輪詢決策 (Round-Robin)
# =================================================================
def get_all_tw_stocks():
    print("🔍 正在獲取最新台股上市櫃公司名單...")
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockInfo"}
    if FINMIND_TOKEN: params["token"] = FINMIND_TOKEN
        
    res = requests.get(url, params=params, timeout=10)
    data = res.json()
    if data.get("msg") == "success":
        df = pd.DataFrame(data["data"])
        df_stocks = df[df["stock_id"].str.match(r'^\d{4}$')]
        return df_stocks["stock_id"].astype(str).unique().tolist()
    else:
        print(f"❌ 獲取名單失敗，API 回傳訊息: {data}") 
        return []

def get_todo_list(all_stocks):
    """讀取現有 CSV，找出最久未更新的股票優先抓取"""
    if os.path.exists(CSV_FILE_PATH):
        try:
            df = pd.read_csv(CSV_FILE_PATH)
            df['股票代號'] = df['股票代號'].astype(str)
            
            # 如果舊資料沒有時間戳記，先幫它補上一個超級舊的時間
            if '最後更新時間' not in df.columns:
                df['最後更新時間'] = "2000-01-01 00:00:00"
            
            # 找出每檔股票「最新」的更新時間
            last_updates = df.groupby('股票代號')['最後更新時間'].max().to_dict()
            
            stock_update_list = []
            for s in all_stocks:
                # 如果這檔股票沒在 CSV 裡，給它一個超舊的時間讓它排第一
                last_time = last_updates.get(s, "2000-01-01 00:00:00")
                stock_update_list.append((s, last_time))
                
            # 💡 核心邏輯：依照最後更新時間由舊到新排序
            stock_update_list.sort(key=lambda x: x[1])
            
            # 抽出排序後的股票代號清單
            todo = [x[0] for x in stock_update_list]
            
            print(f"📊 資料庫目前涵蓋 {len(last_updates)} 檔。系統已啟動輪詢機制，將優先更新最舊的資料。")
            return todo
        except Exception as e:
            print(f"⚠️ 讀取現有 CSV 失敗 ({e})，將重新開始。")
            return all_stocks
    else:
        print("📊 尚未建立資料庫，將執行首次全面抓取！")
        return all_stocks

# =================================================================
# 🚀 3. 核心爬蟲與清洗邏輯
# =================================================================
def fetch_finmind_data(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockFinancialStatements",
        "data_id": stock_id,
        "start_date": "2023-01-01",
    }
    if FINMIND_TOKEN: params["token"] = FINMIND_TOKEN
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if "Too Many Requests" in data.get("msg", ""):
            print(f"🛑 遭到伺服器限流 (Rate Limit)！")
            return pd.DataFrame()
            
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            return pd.DataFrame(data["data"])
        return pd.DataFrame()
    except Exception as e:
        print(f"⚠️ {stock_id} 請求錯誤: {e}")
        return pd.DataFrame()

def fetch_and_transform(target_stocks):
    all_data = []
    total = len(target_stocks)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for idx, stock_id in enumerate(target_stocks, 1):
        print(f"⏳ [{idx}/{total}] 正在抓取 {stock_id} 財報...")
        df_raw = fetch_finmind_data(stock_id)
        
        if not df_raw.empty:
            unique_dates = sorted(df_raw['date'].unique())
            for d in unique_dates:
                year, month = d.split("-")[0], d.split("-")[1]
                if month in ['03', '04', '05']: season = "Q1"
                elif month in ['06', '07', '08']: season = "Q2"
                elif month in ['09', '10', '11']: season = "Q3"
                elif month in ['12', '01', '02']: season = "Q4"
                else: season = "Q?"
                
                eps_df = df_raw[(df_raw['date'] == d) & (df_raw['type'] == 'EPS')]
                eps_val = eps_df['value'].values[0] if not eps_df.empty else 0.0
                
                rev_df = df_raw[(df_raw['date'] == d) & (df_raw['origin_name'].str.contains('營業收入', na=False, regex=False))]
                rev_val = rev_df['value'].values[0] if not rev_df.empty else 0.0
                
                gp_df = df_raw[(df_raw['date'] == d) & (df_raw['origin_name'].str.contains('營業毛利', na=False, regex=False))]
                gp_val = gp_df['value'].values[0] if not gp_df.empty else 0.0
                
                gross_margin = 0.0
                if rev_val > 0:
                    gross_margin = round((float(gp_val) / float(rev_val)) * 100, 2)
                
                all_data.append({
                    "股票代號": stock_id,
                    "季度名稱": f"{year} {season}",
                    "單季 EPS (元)": float(eps_val),
                    "單季營收 (億元)": round(float(rev_val) / 100000000, 2),
                    "單季毛利率 (%)": gross_margin,
                    "最後更新時間": current_time # 👈 押上時間戳記
                })
        
        time.sleep(1)
        
    return pd.DataFrame(all_data)

# =================================================================
# 🏁 4. 執行與存檔 (無縫覆蓋)
# =================================================================
def main():
    print("啟動【長期維護版】台股財報 ETL 任務 (含毛利率自動輪詢)...")
    
    all_stocks = get_all_tw_stocks()
    if not all_stocks: 
        print("❌ 無法獲取股票名單，強制中止執行並回報錯誤狀態給 GitHub！")
        sys.exit(1)
    
    todo_list = get_todo_list(all_stocks)
        
    # 永遠只抓前 300 檔最久沒更新的股票
    batch_stocks = todo_list[:300]
    print(f"🚀 本次排程將更新 {len(batch_stocks)} 檔股票...")
    
    new_data_df = fetch_and_transform(batch_stocks)
    
    if not new_data_df.empty:
        new_data_df['股票代號'] = new_data_df['股票代號'].astype(str)
        
        if os.path.exists(CSV_FILE_PATH):
            old_df = pd.read_csv(CSV_FILE_PATH)
            old_df['股票代號'] = old_df['股票代號'].astype(str)
            final_df = pd.concat([old_df, new_data_df], ignore_index=True)
        else:
            final_df = new_data_df
            
        # 💡 核心覆蓋：依照代號與季度去重複，保留「最後一筆」(也就是我們剛剛抓到、有最新時間戳記的那筆)
        final_df = final_df.drop_duplicates(subset=["股票代號", "季度名稱"], keep="last")
        final_df = final_df.sort_values(by=["股票代號", "季度名稱"]).reset_index(drop=True)
        
        final_df.to_csv(CSV_FILE_PATH, index=False, encoding='utf-8-sig')
        print(f"🎉 本回合輪詢更新成功！目前資料庫共涵蓋 {len(final_df['股票代號'].unique())} 檔股票。")
    else:
        print("❌ 本回合未抓取到有效資料。")

if __name__ == "__main__":
    main()

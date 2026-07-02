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
CSV_FILE_PATH = os.path.join(DATA_DIR, 'tw_monthly_revenue.csv')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 🔑 你的專屬 API 通行證
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
    """讀取現有月營收 CSV，找出最久未更新的股票優先抓取"""
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
            
            todo = [x[0] for x in stock_update_list]
            
            print(f"📊 [月營收] 資料庫目前涵蓋 {len(last_updates)} 檔。系統已啟動輪詢機制，將優先更新最舊的資料。")
            return todo
        except Exception as e:
            print(f"⚠️ 讀取現有月營收 CSV 失敗 ({e})，將重新開始。")
            return all_stocks
    else:
        print("📊 [月營收] 尚未建立資料庫，這將是第一次抓取！")
        return all_stocks

# =================================================================
# 🚀 3. 核心爬蟲與清洗邏輯 (月營收)
# =================================================================
def fetch_finmind_monthly_revenue(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockMonthRevenue",
        "data_id": stock_id,
        "start_date": "2024-01-01", # 抓取 2024 年至今的每月營收
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
        print(f"⚠️ {stock_id} 月營收請求錯誤: {e}")
        return pd.DataFrame()

def fetch_and_transform(target_stocks):
    all_data = []
    total = len(target_stocks)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for idx, stock_id in enumerate(target_stocks, 1):
        print(f"⏳ [{idx}/{total}] 正在抓取 {stock_id} 月營收...")
        df_raw = fetch_finmind_monthly_revenue(stock_id)
        
        if not df_raw.empty:
            for _, row in df_raw.iterrows():
                raw_date = row.get("date", "")
                if raw_date:
                    year_month = raw_date[:7] # 只要 "2024-01" 
                else:
                    year_month = "未知"
                
                rev_val = row.get("revenue", 0.0)      # 當月營收
                yoy_val = row.get("revenue_year_growth_rate", 0.0) # 年增率 YoY (%)
                mom_val = row.get("revenue_month_growth_rate", 0.0) # 月增率 MoM (%)
                
                all_data.append({
                    "股票代號": stock_id,
                    "年月": year_month,
                    "單月營收 (億元)": round(float(rev_val) / 100000000, 2), # 換算成億元
                    "營收年增率 (YoY%)": round(float(yoy_val) * 100, 2) if yoy_val else 0.0,
                    "營收月增率 (MoM%)": round(float(mom_val) * 100, 2) if mom_val else 0.0,
                    "最後更新時間": current_time # 👈 押上時間戳記
                })
        
        # 🛡️ 每次請求完停 1 秒
        time.sleep(1)
        
    return pd.DataFrame(all_data)

# =================================================================
# 🏁 4. 執行與存檔 (無縫覆蓋 + 空檔免疫)
# =================================================================
def main():
    print("啟動【長期維護版】台股【月營收】ETL 任務 (自動輪詢)...")
    
    all_stocks = get_all_tw_stocks()
    if not all_stocks: 
        print("❌ 無法獲取股票名單，強制中止執行並回報錯誤狀態給 GitHub！")
        sys.exit(1)
    
    todo_list = get_todo_list(all_stocks)
        
    # 本次排程抓取最久沒更新的 300 檔
    batch_stocks = todo_list[:300]
    print(f"🚀 本次排程將更新 {len(batch_stocks)} 檔股票的月營收...")
    
    new_data_df = fetch_and_transform(batch_stocks)
    
    if not new_data_df.empty:
        new_data_df['股票代號'] = new_data_df['股票代號'].astype(str)
        
        # 🛡️ 加入空檔免疫力機制
        old_df = pd.DataFrame()
        if os.path.exists(CSV_FILE_PATH):
            try:
                old_df = pd.read_csv(CSV_FILE_PATH)
                old_df['股票代號'] = old_df['股票代號'].astype(str)
            except pd.errors.EmptyDataError:
                print("⚠️ 發現舊 CSV 是空檔案，將直接寫入新資料。")
            except Exception as e:
                print(f"⚠️ 讀取舊 CSV 發生未知錯誤：{e}")

        # 如果舊資料成功讀取且不是空的，才進行合併
        if not old_df.empty:
            final_df = pd.concat([old_df, new_data_df], ignore_index=True)
        else:
            final_df = new_data_df
            
        # 💡 核心覆蓋：依照代號與年月去重複，保留「最後一筆」(也就是剛剛抓到、有最新時間戳記的那筆)
        final_df = final_df.drop_duplicates(subset=["股票代號", "年月"], keep="last")
        final_df = final_df.sort_values(by=["股票代號", "年月"]).reset_index(drop=True)
        
        final_df.to_csv(CSV_FILE_PATH, index=False, encoding='utf-8-sig')
        print(f"🎉 月營收輪詢更新成功！目前資料庫共涵蓋 {len(final_df['股票代號'].unique())} 檔股票。")
    else:
        print("❌ 本回合未抓取到有效月營收資料。")

if __name__ == "__main__":
    main()

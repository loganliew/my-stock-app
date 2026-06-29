import requests
import pandas as pd
import time
import os
import sys

# =================================================================
# 📂 1. 設定存檔路徑
# =================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
CSV_FILE_PATH = os.path.join(DATA_DIR, 'tw_monthly_revenue.csv')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 🔑 你的專屬 API 通行證 (請確認這裡有填寫你的 Token)
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibG9nYW5saWV3IiwiZW1haWwiOiJzMjI3MDIyMjZAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.j2WUIuC7PJGNKSwAviyTbj0bwuq8AJUmd4rWVQ9rUOY" 

# =================================================================
# 🤖 2. 獲取全市場名單 & 檢查已完成進度
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
        return df_stocks["stock_id"].unique().tolist()
    else:
        # 加上這行！如果失敗，把 FinMind 罵了什麼印出來
        print(f"❌ 獲取名單失敗，API 回傳訊息: {data}") 
        return []

def get_todo_list(all_stocks):
    """讀取現有月營收 CSV，比對出還沒抓過的股票清單"""
    if os.path.exists(CSV_FILE_PATH):
        try:
            existing_df = pd.read_csv(CSV_FILE_PATH)
            existing_stocks = existing_df['股票代號'].astype(str).unique().tolist()
            todo = [s for s in all_stocks if s not in existing_stocks]
            print(f"📊 [月營收] 目前資料庫已有 {len(existing_stocks)} 檔，剩餘 {len(todo)} 檔待處理。")
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
    
    for idx, stock_id in enumerate(target_stocks, 1):
        print(f"⏳ [{idx}/{total}] 正在抓取 {stock_id} 月營收...")
        df_raw = fetch_finmind_monthly_revenue(stock_id)
        
        if not df_raw.empty:
            for _, row in df_raw.iterrows():
                # FinMind 的 date 通常是 2024-01-01 代表 1 月營收
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
                    "營收月增率 (MoM%)": round(float(mom_val) * 100, 2) if mom_val else 0.0
                })
        
        # 🛡️ 每次請求完停 1 秒
        time.sleep(1)
        
    return pd.DataFrame(all_data)

# =================================================================
# 🏁 4. 執行與存檔 (智慧接力)
# =================================================================
def main():
    print("啟動【二號工人】，開始執行台股【月營收】ETL 任務...")
    
    all_stocks = get_all_tw_stocks()
    if not all_stocks: 
        print("❌ 無法獲取股票名單，強制中止執行並回報錯誤狀態給 GitHub！")
        sys.exit(1) # 👈 這行就是讓 GitHub 亮紅燈的終極武器
    
    todo_list = get_todo_list(all_stocks)
    if not todo_list:
        print("🎉 太棒了！全市場所有股票的歷史月營收皆已入庫。")
        return
        
    # 本次一樣只抓前 300 檔，不超過限制
    batch_stocks = todo_list[:300]
    print(f"🚀 本次排程將執行 {len(batch_stocks)} 檔股票的月營收抓取...")
    
    new_data_df = fetch_and_transform(batch_stocks)
    
    if not new_data_df.empty:
        if os.path.exists(CSV_FILE_PATH):
            old_df = pd.read_csv(CSV_FILE_PATH)
            final_df = pd.concat([old_df, new_data_df], ignore_index=True)
        else:
            final_df = new_data_df
            
        final_df = final_df.drop_duplicates(subset=["股票代號", "年月"], keep="last")
        final_df = final_df.sort_values(by=["股票代號", "年月"]).reset_index(drop=True)
        
        final_df.to_csv(CSV_FILE_PATH, index=False, encoding='utf-8-sig')
        print(f"🎉 月營收接力成功！目前資料庫已有 {len(final_df['股票代號'].unique())} 檔股票。")
    else:
        print("❌ 本回合未抓取到有效月營收資料。")

if __name__ == "__main__":
    main()

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
CSV_FILE_PATH = os.path.join(DATA_DIR, 'tw_eps_revenue.csv')

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
        print(f"❌ 獲取名單失敗，API 回傳訊息: {data}") 
        return []

def get_todo_list(all_stocks):
    """讀取現有 CSV，比對出還沒抓過的股票清單"""
    if os.path.exists(CSV_FILE_PATH):
        try:
            existing_df = pd.read_csv(CSV_FILE_PATH)
            existing_stocks = existing_df['股票代號'].astype(str).unique().tolist()
            todo = [s for s in all_stocks if s not in existing_stocks]
            print(f"📊 目前資料庫已有 {len(existing_stocks)} 檔，剩餘 {len(todo)} 檔待處理。")
            return todo
        except Exception as e:
            print(f"⚠️ 讀取現有 CSV 失敗 ({e})，將重新開始。")
            return all_stocks
    else:
        print("📊 尚未建立資料庫，這將是第一次抓取！")
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
                
                # 1. 抓取 EPS
                eps_df = df_raw[(df_raw['date'] == d) & (df_raw['type'] == 'EPS')]
                eps_val = eps_df['value'].values[0] if not eps_df.empty else 0.0
                
                # 2. 抓取營業收入
                rev_df = df_raw[(df_raw['date'] == d) & (df_raw['origin_name'].str.contains('營業收入', na=False, regex=False))]
                rev_val = rev_df['value'].values[0] if not rev_df.empty else 0.0
                
                # 💡 3. 新增：抓取營業毛利並計算毛利率
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
                    "單季毛利率 (%)": gross_margin  # 👈 新增寫入這個欄位
                })
        
        time.sleep(1)
        
    return pd.DataFrame(all_data)

# =================================================================
# 🏁 4. 執行與存檔 (智慧接力)
# =================================================================
def main():
    print("啟動【智慧接力版】台股財報 ETL 任務 (含毛利率)...")
    
    all_stocks = get_all_tw_stocks()
    if not all_stocks: 
        print("❌ 無法獲取股票名單，強制中止執行並回報錯誤狀態給 GitHub！")
        sys.exit(1)
    
    todo_list = get_todo_list(all_stocks)
    if not todo_list:
        print("🎉 太棒了！全市場所有股票的歷史財報皆已入庫，無須更新。")
        return
        
    batch_stocks = todo_list[:300]
    print(f"🚀 本次排程將執行 {len(batch_stocks)} 檔股票的抓取...")
    
    new_data_df = fetch_and_transform(batch_stocks)
    
    if not new_data_df.empty:
        if os.path.exists(CSV_FILE_PATH):
            old_df = pd.read_csv(CSV_FILE_PATH)
            final_df = pd.concat([old_df, new_data_df], ignore_index=True)
        else:
            final_df = new_data_df
            
        final_df = final_df.drop_duplicates(subset=["股票代號", "季度名稱"], keep="last")
        final_df = final_df.sort_values(by=["股票代號", "季度名稱"]).reset_index(drop=True)
        
        final_df.to_csv(CSV_FILE_PATH, index=False, encoding='utf-8-sig')
        print(f"🎉 本回合接力成功！資料庫已擴充至 {len(final_df['股票代號'].unique())} 檔股票。")
    else:
        print("❌ 本回合未抓取到有效資料。")

if __name__ == "__main__":
    main()

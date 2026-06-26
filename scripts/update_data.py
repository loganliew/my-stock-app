import requests
import pandas as pd
import time
import os

# =================================================================
# 📂 1. 設定存檔路徑
# =================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
CSV_FILE_PATH = os.path.join(DATA_DIR, 'tw_eps_revenue.csv')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 🔑 你的專屬 API 通行證 (目前留空，註冊後填入)
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibG9nYW5saWV3IiwiZW1haWwiOiJzMjI3MDIyMjZAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.j2WUIuC7PJGNKSwAviyTbj0bwuq8AJUmd4rWVQ9rUOY" 

# =================================================================
# 🤖 2. 動態獲取全市場股票名單
# =================================================================
def get_all_tw_stocks():
    print("🔍 正在獲取最新台股上市櫃公司名單...")
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockInfo"
    }
    # 若有 token 則帶入
    if FINMIND_TOKEN: params["token"] = FINMIND_TOKEN
        
    res = requests.get(url, params=params, timeout=10)
    data = res.json()
    
    if data.get("msg") == "success":
        df = pd.DataFrame(data["data"])
        # 條件過濾：排除 ETF 等，只保留代號是 4 碼數字的普通股
        df_stocks = df[df["stock_id"].str.match(r'^\d{4}$')]
        stock_list = df_stocks["stock_id"].unique().tolist()
        print(f"✅ 成功獲取 {len(stock_list)} 檔普通股代號！")
        return stock_list
    else:
        print("❌ 獲取股票名單失敗。")
        return []

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
        
        # 遇到頻率限制的防禦提示
        if "Too Many Requests" in data.get("msg", ""):
            print(f"🛑 遭到伺服器限流 (Rate Limit)！請確認 Token 或增加暫停時間。")
            return pd.DataFrame()
            
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            return pd.DataFrame(data["data"])
        else:
            return pd.DataFrame()
    except Exception as e:
        print(f"⚠️ {stock_id} 請求發生錯誤: {e}")
        return pd.DataFrame()

def fetch_and_transform(target_stocks):
    all_data = []
    total = len(target_stocks)
    
    for idx, stock_id in enumerate(target_stocks, 1):
        print(f"⏳ [{idx}/{total}] 正在抓取 {stock_id} 的財報資料...")
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
                
                label = f"{year} {season}"
                df_q = df_raw[df_raw['date'] == d]
                
                eps_df = df_q[df_q['type'] == 'EPS']
                eps_val = eps_df['value'].values[0] if not eps_df.empty else 0.0
                
                rev_df = df_q[df_q['origin_name'].str.contains('營業收入', na=False, regex=False)]
                rev_val = rev_df['value'].values[0] if not rev_df.empty else 0.0
                
                all_data.append({
                    "股票代號": stock_id,
                    "季度名稱": label,
                    "單季 EPS (元)": float(eps_val),
                    "單季營收 (億元)": round(float(rev_val) / 100000000, 2)
                })
        
        # 🛡️ 每檔股票之間暫停 1.5 秒 (全市場 1800 檔大約需耗時 45 分鐘)
        time.sleep(1.5)
        
    return pd.DataFrame(all_data)

# =================================================================
# 🏁 4. 執行與存檔
# =================================================================
def main():
    print("啟動搬磚工人，開始執行【全市場】台股財報 ETL 任務...")
    
    # 1. 取得全市場名單
    target_stocks = get_all_tw_stocks()
    
    # 【開發測試用】：如果你還沒申請 Token，先把這行註解解開，只抓前 10 檔測試就好！
    # target_stocks = target_stocks[:10] 
    
    if not target_stocks: return
    
    # 2. 抓取財報
    final_df = fetch_and_transform(target_stocks)
    
    if not final_df.empty:
        final_df = final_df.drop_duplicates(subset=["股票代號", "季度名稱"], keep="last")
        final_df = final_df.sort_values(by=["股票代號", "季度名稱"]).reset_index(drop=True)
        final_df.to_csv(CSV_FILE_PATH, index=False, encoding='utf-8-sig')
        print(f"🎉 全市場任務大功告成！資料已成功寫入：{CSV_FILE_PATH}")
    else:
        print("❌ 任務失敗：沒有抓取到任何資料。")

if __name__ == "__main__":
    main()

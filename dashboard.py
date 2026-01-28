import streamlit as st
import pandas as pd
import yfinance as yf
import datetime
import time

# --- 1. 頁面設定 ---
st.set_page_config(page_title="總柴終極版", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #FFFFFF; }
    .card { background-color: #262730; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #555; }
    .card-buy { border-left-color: #FF4B4B !important; }
    .card-sell { border-left-color: #00FF00 !important; }
    .big-text { font-size: 1.2rem; font-weight: bold; }
    .sub-text { font-size: 0.9rem; color: #aaa; }
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴終極篩選 (Yahoo Finance 核心)")
st.caption("改用國際線路，保證數據絕對讀取得到。")

# --- 2. 監控清單 (熱門股 + 權值股) ---
# 這些股票代號會自動加上 .TW
WATCHLIST = [
    '2330', '2317', '2454', '2308', '2382', '3231', '2357', '2376', '2356', '3037', # 電子
    '1513', '1519', '1503', '1605', '1504', # 重電
    '2603', '2609', '2615', '2618', '2610', # 航運
    '2881', '2882', '2891', '2886', # 金融
    '4743', '1795', '3293', # 生技
    '2313', '2344', '3006', '3481', '2409'  # 熱門
]

# 側邊欄
with st.sidebar:
    st.header("設定")
    inv_input = st.text_input("庫存代號 (免加.TW)", "8131")
    user_inv = [x.strip() for x in inv_input.split(",") if x.strip()]
    
    # 合併清單
    all_targets = list(set(WATCHLIST + user_inv))

# --- 3. 核心功能：透過 yfinance 抓取 ---
def get_stock_data_yf(sid):
    try:
        # Yahoo Finance 台股代號需要加 .TW
        ticker_sym = f"{sid}.TW"
        stock = yf.Ticker(ticker_sym)
        
        # 抓取最近 2 個月的資料 (確保有足夠天數算 MA20)
        # period='2mo' 比指定日期更穩
        hist = stock.history(period="2mo")
        
        if hist.empty or len(hist) < 20:
            return None
            
        # 最新一筆資料 (可能是今天收盤，或盤中即時)
        latest = hist.iloc[-1]
        prev = hist.iloc[-2]
        
        price = latest['Close']
        prev_close = prev['Close']
        
        # 計算 MA20 (取最後 20 筆收盤價平均)
        ma20 = hist['Close'].tail(20).mean()
        
        # 計算漲跌
        pct = ((price - prev_close) / prev_close) * 100
        
        # 取得名稱 (Yahoo 有時名稱會是英文或亂碼，這裡做簡單處理，若無則顯示代號)
        # 為了速度，我們直接用代號就好，或者簡單映射幾個重要的
        name = sid 
        
        return {
            'code': sid,
            'price': round(price, 2),
            'pct': round(pct, 2),
            'ma20': round(ma20, 2),
            'vol': latest['Volume'],
            'is_inv': sid in user_inv
        }
    except Exception as e:
        return None

# --- 4. 執行掃描 ---
if st.button("🔄 立即啟動 (Yahoo 國際線路)", type="primary"):
    
    results = []
    my_bar = st.progress(0, text="🐕 總柴正在連線 Yahoo Finance...")
    
    total = len(all_targets)
    
    for i, sid in enumerate(all_targets):
        data = get_stock_data_yf(sid)
        if data:
            # --- 麻紗/旺大 策略 ---
            signal = "觀望"
            reason = "盤整"
            tag = "normal"
            
            price = data['price']
            ma20 = data['ma20']
            pct = data['pct']
            
            # 判斷多空
            if price >= ma20:
                # 多頭
                if pct > 3.0:
                    signal = "🔥 飆股訊號"
                    reason = f"站上月線({ma20}) + 爆量長紅"
                    tag = "card-buy"
                elif pct > 0:
                    signal = "🔴 多頭排列"
                    reason = f"站穩月線({ma20})"
                    tag = "card-buy"
                else:
                    signal = "🛡️ 多頭回檔"
                    reason = f"月線({ma20})有撐"
                    tag = "normal"
            else:
                # 空頭
                if pct < -3.0:
                    signal = "❄️ 避雷訊號"
                    reason = f"跌破月線({ma20}) + 重挫"
                    tag = "card-sell"
                elif pct < 0:
                    signal = "🟢 轉弱"
                    reason = f"被月線({ma20})壓制"
                    tag = "normal" # 台灣綠色是跌，但我這裡用 normal 灰色顯示，只強調大跌
                else:
                    signal = "🌤️ 反彈"
                    reason = "空頭反彈"
                    tag = "normal"
            
            data['signal'] = signal
            data['reason'] = reason
            data['tag'] = tag
            results.append(data)
            
        my_bar.progress((i+1)/total)
    
    my_bar.empty()
    
    # --- 5. 顯示結果 ---
    
    # A. 庫存區 (最重要)
    st.subheader("💼 我的庫存")
    inv_data = [r for r in results if r['is_inv']]
    if inv_data:
        for r in inv_data:
            color = "#FF4444" if r['pct'] > 0 else "#00FF00"
            st.markdown(f"""
            <div class="card {r['tag']}">
                <div class="big-text">{r['code']} {r['signal']}</div>
                <div>現價：{r['price']} (<span style='color:{color}'>{r['pct']}%</span>)</div>
                <div class="sub-text">MA20月線：{r['ma20']} | {r['reason']}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.error(f"庫存代號 {inv_input} 資料讀取失敗，請確認代號正確 (如 8131)。")
        
    st.divider()
    
    # B. 篩選區
    t1, t2 = st.tabs(["🔥 推薦買進 / 觀察", "❄️ 推薦賣出 / 避開"])
    
    with t1:
        # 篩選：站上月線 且 漲幅 > 2%
        buys = [r for r in results if r['price'] >= r['ma20'] and r['pct'] > 2.0]
        buys.sort(key=lambda x: x['pct'], reverse=True)
        
        if buys:
            for r in buys:
                st.markdown(f"""
                <div class="card card-buy">
                    <div class="big-text">{r['code']} 🔥 +{r['pct']}%</div>
                    <div>現價：{r['price']} | MA20：{r['ma20']}</div>
                    <div class="sub-text">{r['reason']}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("今日無符合「站上月線+大漲」的標的。")
            
    with t2:
        # 篩選：跌破月線 且 跌幅 < -2%
        sells = [r for r in results if r['price'] < r['ma20'] and r['pct'] < -2.0]
        sells.sort(key=lambda x: x['pct'])
        
        if sells:
            for r in sells:
                st.markdown(f"""
                <div class="card card-sell">
                    <div class="big-text">{r['code']} ❄️ {r['pct']}%</div>
                    <div>現價：{r['price']} | MA20：{r['ma20']}</div>
                    <div class="sub-text">{r['reason']}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("今日無符合「跌破月線+重挫」的標的。")

else:
    st.info("👋 系統準備就緒，請點擊上方按鈕開始掃描 (使用 Yahoo Finance 數據源)")

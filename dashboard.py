import streamlit as st
import pandas as pd
import twstock
import time
import requests
import urllib3

# --- 1. 系統設定 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# 修正 SSL 憑證問題 (這是為了讓你在雲端環境也能連到證交所)
old_merge = requests.Session.merge_environment_settings
def new_merge(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url: verify = False
    return old_merge(self, url, proxies, stream, verify, cert)
requests.Session.merge_environment_settings = new_merge

st.set_page_config(page_title="總柴真實篩選", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #FFFFFF; }
    .metric-card { background-color: #262730; padding: 15px; border-radius: 5px; margin-bottom: 10px; border-left: 5px solid #555; }
    .buy-signal { border-left-color: #FF4B4B !important; } /* 紅色買訊 */
    .sell-signal { border-left-color: #00FF00 !important; } /* 綠色賣訊 */
    .hold-signal { border-left-color: #FFA500 !important; } /* 黃色續抱 */
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴真實篩選器 (麻紗+旺大策略)")
st.caption("數據來源：證交所 (TWSE) | 篩選邏輯：MA20 月線戰法")

# --- 2. 設定監控清單 ---
# 為了不跑太久，這裡精選市場最熱門的成交重心股 (可自行增加)
# 包含：台積電、鴻海、AI股、重電、航運、生技
WATCHLIST = [
    '2330', '2317', '2454', '2382', '3231', '2357', '2376', '2356', '3037', '3035', # 權值/AI
    '1513', '1519', '1503', '1504', '1605', # 重電/電纜
    '2603', '2609', '2615', '2618', '2610', # 航運
    '4743', '1795', '3293', '6472', # 生技
    '2313', '2344', '3006', '3481', '2409', # 熱門電子
    '8131' # 你的庫存
]

# 側邊欄設定
with st.sidebar:
    st.header("設定")
    inv_input = st.text_input("庫存代號", "8131")
    user_inv = [x.strip() for x in inv_input.split(",")]
    # 合併清單並去重
    target_stocks = list(set(WATCHLIST + user_inv))

# --- 3. 核心運算函式 ---

def get_real_data(sid):
    """抓取即時(或收盤)股價 + 計算 MA20"""
    try:
        # 1. 抓歷史資料算 MA20
        stock = twstock.Stock(sid)
        # 抓最近 31 天 (確保假日扣除後夠算 20MA)
        hist = stock.fetch_from(2025, 12) # 這裡年份設稍早確保抓得到，twstock會自動補正
        if not hist or len(hist) < 5: 
            # 如果年份設太死可能抓不到，改用 fetch_31
            hist = stock.fetch_31()
        
        if len(hist) < 20:
            return None # 資料不足無法計算
            
        ma20 = sum([x.close for x in hist[-20:]]) / 20
        
        # 2. 抓即時/今日收盤資料
        real = twstock.realtime.get(sid)
        if not real['success']:
            return None
            
        rt = real['realtime']
        name = real['info']['name']
        
        # 價格容錯 (有些股票沒有成交價，改抓買賣價)
        try: price = float(rt['latest_trade_price'])
        except: 
            try: price = float(rt['best_bid_price'][0])
            except: price = 0
            
        if price == 0: return None # 沒交易
        
        # 漲跌幅
        try: prev = float(rt['previous_close'])
        except: prev = price
        pct = round(((price - prev) / prev) * 100, 2)
        
        return {
            "code": sid,
            "name": name,
            "price": price,
            "pct": pct,
            "ma20": round(ma20, 2),
            "is_inv": sid in user_inv
        }
    except Exception as e:
        return None

# --- 4. 執行篩選 ---
if st.button("🔄 立即掃描真實股價", type="primary"):
    
    results = []
    progress_text = "正在連線證交所抓取數據..."
    my_bar = st.progress(0, text=progress_text)
    
    total = len(target_stocks)
    
    for i, sid in enumerate(target_stocks):
        data = get_real_data(sid)
        if data:
            # --- 麻紗/旺大 篩選邏輯 ---
            signal = "觀望"
            tag = "normal" # 用來標記顏色
            desc = "盤整中"
            
            price = data['price']
            ma20 = data['ma20']
            pct = data['pct']
            
            # A. 多方邏輯 (站上月線)
            if price >= ma20:
                if pct > 3.0: # 旺大: 爆量長紅
                    signal = "🔥 強力買進"
                    tag = "buy-signal"
                    desc = f"強勢噴出！站上月線({ma20})且大漲"
                elif pct > 0:
                    signal = "🔴 多頭格局"
                    tag = "hold-signal"
                    desc = f"股價在月線({ma20})之上，趨勢向上"
                else:
                    signal = "🛡️ 多頭回檔"
                    tag = "normal"
                    desc = f"守在月線({ma20})之上"
            
            # B. 空方邏輯 (跌破月線)
            else:
                if pct < -3.0:
                    signal = "❄️ 強力賣出"
                    tag = "sell-signal"
                    desc = f"危險！跌破月線({ma20})且重挫"
                else:
                    signal = "🟢 空頭格局"
                    tag = "normal"
                    desc = f"股價被月線({ma20})壓著打"

            data['signal'] = signal
            data['tag'] = tag
            data['desc'] = desc
            results.append(data)
        
        # 更新進度條
        my_bar.progress((i + 1) / total)
        time.sleep(0.05) # 稍微緩衝避免被證交所封鎖
        
    my_bar.empty()
    
    # --- 5. 顯示結果 ---
    
    # 庫存專區
    st.subheader(f"💼 我的庫存 ({len(user_inv)}檔)")
    inv_data = [r for r in results if r['is_inv']]
    if inv_data:
        for r in inv_data:
            color = "red" if r['pct'] > 0 else "green"
            st.markdown(f"""
            <div class="metric-card {r['tag']}">
                <h4>{r['name']} ({r['code']}) - {r['signal']}</h4>
                <p>現價：<b>{r['price']}</b> (<span style='color:{color}'>{r['pct']}%</span>)</p>
                <p>MA20月線：{r['ma20']} | 狀態：{r['desc']}</p>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("庫存抓取失敗或無資料")

    st.divider()

    # 篩選結果
    tab1, tab2 = st.tabs(["🔥 推薦買進 / 觀察", "❄️ 推薦賣出 / 避開"])
    
    with tab1:
        # 篩選條件：Tag是 buy 或 hold 且 漲幅>0
        buys = [r for r in results if r['price'] >= r['ma20'] and r['pct'] > 2.0]
        # 排序：漲幅由大到小
        buys.sort(key=lambda x: x['pct'], reverse=True)
        
        if buys:
            for r in buys:
                st.markdown(f"""
                <div class="metric-card buy-signal">
                    <b>{r['name']} ({r['code']})</b> <span style='float:right; color:red'>+{r['pct']}%</span><br>
                    現價: {r['price']} | MA20: {r['ma20']}<br>
                    <span style='color:#ccc'>{r['desc']}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("今日盤勢較弱，無符合「站上月線+漲幅>2%」的股票。")

    with tab2:
        # 篩選條件：跌破月線 且 跌幅 < -2%
        sells = [r for r in results if r['price'] < r['ma20'] and r['pct'] < -2.0]
        sells.sort(key=lambda x: x['pct'])
        
        if sells:
            for r in sells:
                st.markdown(f"""
                <div class="metric-card sell-signal">
                    <b>{r['name']} ({r['code']})</b> <span style='float:right; color:#00FF00'>{r['pct']}%</span><br>
                    現價: {r['price']} | MA20: {r['ma20']}<br>
                    <span style='color:#ccc'>{r['desc']}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("今日無符合「跌破月線+跌幅<-2%」的重挫股。")

else:
    st.info("👋 請點擊上方按鈕，總柴會立刻連線證交所幫你算 MA20！")

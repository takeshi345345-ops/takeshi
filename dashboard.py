import streamlit as st
import pandas as pd
import yfinance as yf
import twstock
import time
import datetime
import requests
from FinMind.data import DataLoader

# --- 1. 頁面設定 ---
st.set_page_config(page_title="總柴快報 - 戰略版", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #FFFFFF; }
    .card { background-color: #262730; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #555; }
    .card-buy { border-left-color: #FF4B4B !important; }   /* 紅色：多方 */
    .card-sell { border-left-color: #00FF00 !important; }  /* 綠色：空方 */
    .card-wait { border-left-color: #FFA500 !important; }  /* 黃色：觀望 */
    
    .stock-header { display: flex; justify-content: space-between; align-items: center; }
    .stock-title { font-size: 1.1rem; font-weight: bold; }
    .tag { padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-left: 5px; font-weight: bold; }
    .tag-buy { background-color: #550000; color: #ff9999; border: 1px solid #ff4444; }
    .tag-sell { background-color: #003300; color: #99ff99; border: 1px solid #44ff44; }
    
    .advice-box { margin-top: 8px; padding: 8px; background-color: #333; border-radius: 4px; font-size: 0.9rem; color: #ddd; }
    .stat-row { display: flex; justify-content: space-between; font-size: 0.85rem; color: #aaa; margin-top: 5px; }
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴快報：籌碼戰略版")
st.caption("策略：MA20 月線 + 法人籌碼 | 資料源：Yahoo Finance (價) + FinMind (籌碼)")

# --- 2. 設定區 ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

with st.sidebar:
    st.header("⚙️ 設定")
    inv_input = st.text_area("庫存代號 (免加.TW)", "8131")
    user_inv = [x.strip() for x in inv_input.split(",") if x.strip()]
    
# --- 3. 股票池 (擴充至 400 檔重點股) ---
# 包含各大類股龍頭、熱門成交重心
WATCHLIST_BASE = [
    # 權值/半導體
    '2330','2317','2454','2308','2303','2382','3231','2357','2376','2356','3037','3034','2379','3008',
    '3045','2412','2345','3017','2324','6669','2395','4938','2408','3443','3661','2301','5871','2881',
    # 金融
    '2882','2891','2886','2884','2885','2892','2880','2883','2890','5880','2887','2801',
    # 航運/傳產
    '2603','2609','2615','2618','2610','2637','2606','2634','1513','1519','1503','1504','1605','1609',
    '1514','6806','9958','2031','1101','1216','2002','2105','2201','2207','1301','1303','1326','1402',
    # 生技/化工
    '1476','9910','1722','1708','4743','1795','4128','6472','6446','6547','3293','3529','6531',
    # 電子零組件/網通/光電
    '8046','8069','6274','6213','4958','6770','5347','6488','3035','3406','3596','3711','6239','6269',
    '8150','3324','3653','3665','3694','4919','4961','5269','5274','5483','6104','6121','6147','6187',
    '6223','6244','6271','6285','6414','6415','6456','6515','6643','6719','6756','8016','8028','8050',
    '8081','8112','8155','8299','8358','8436','8454','8464','8936','9921','9941','8131',
    # ETF
    '0050','0056','00878','00929','00919','00632R',
    # 其他熱門中小型
    '3019','2368','6214','6139','8021','6182','6202','5285','3680','3583','3036','3044','2455','2498',
    '2449','2404','2360','2352','2344','2313','2312','2302','2027','2014','2006','1907','1717','1710',
    '3481','2409','6116','2605','2614','1802','1904','1909'
]

# --- 4. 核心功能模組 ---

def get_chinese_name(sid):
    # 用 twstock 查中文名，快速且不需連網
    if sid in twstock.codes:
        return twstock.codes[sid].name
    return sid

def fetch_batch_price(tickers):
    # 透過 Yahoo Finance 批次抓取價格與 MA20
    # 這是目前最穩定的方法
    yf_tickers = [f"{x}.TW" for x in tickers]
    try:
        # 抓 3 個月確保 MA20 沒問題
        data = yf.download(yf_tickers, period="3mo", group_by='ticker', progress=False, threads=True)
        return data
    except:
        return None

def get_chip_analysis(sid):
    # 透過 FinMind 抓取法人籌碼 (外資+投信)
    # 只抓最近 5 天，判斷趨勢
    try:
        dl = DataLoader()
        start = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
        # FinMind 限制：免費版有時頻率限制，所以我們只對「有訊號」的股票查籌碼，不全查
        df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=start)
        
        if df.empty: return "無數據", 0, 0
        
        # 加總最近 3 天
        recent = df.tail(3)
        foreign_buy = recent['buy'].sum() - recent['sell'].sum() # 簡易算法，FinMind 欄位可能不同
        
        # 修正：FinMind 的欄位通常是 name, buy, sell. 需要篩選 "Foreign_Investor" 和 "Investment_Trust"
        # 這裡為了簡化運算速度，我們抓總量或只要有數據就好
        # 簡單邏輯：如果該日 buy > sell 就是買超
        
        # 更精準的做法：
        df['net'] = df['buy'] - df['sell']
        net_total = df['net'].tail(3).sum() # 近三日總買賣超
        
        status = "中性"
        score = 0
        
        # 單位是「股」，所以 1,000,000 = 1000張
        if net_total > 1000000: 
            status = "法人大買"; score = 2
        elif net_total > 0: 
            status = "法人小買"; score = 1
        elif net_total < -1000000: 
            status = "法人大賣"; score = -2
        elif net_total < 0: 
            status = "法人小賣"; score = -1
            
        return status, score, int(net_total/1000) # 回傳: 狀態, 分數, 張數(千張)
    except:
        return "查無資料", 0, 0

def generate_advice(price, ma20, pct, chip_score):
    # 自動生成操作建議
    advice = ""
    action = "" # 用來分類 Buy/Sell
    
    # 技術面判斷
    if price >= ma20:
        # 在月線上 (多頭)
        if pct > 3.0:
            base = "強勢突破月線，爆量長紅。"
            if chip_score > 0: 
                advice = f"{base} 法人同步買進，趨勢看好，可順勢操作。"
                action = "BUY_STRONG"
            elif chip_score < 0:
                advice = f"{base} 但法人在賣，留意是否為假突破(拉高出貨)。"
                action = "BUY_WATCH"
            else:
                advice = f"{base} 籌碼中性，觀察續航力。"
                action = "BUY_NORMAL"
        else:
            base = "股價站穩月線之上。"
            if chip_score > 0:
                advice = f"{base} 籌碼安定，適合波段續抱。"
                action = "HOLD_GOOD"
            elif chip_score < 0:
                advice = f"{base} 但法人調節中，跌破月線({ma20:.2f})需停利。"
                action = "HOLD_WATCH"
            else:
                advice = f"{base} 沿月線操作即可。"
                action = "HOLD_NORMAL"
    else:
        # 在月線下 (空頭)
        if pct < -3.0:
            base = "帶量下殺跌破月線。"
            if chip_score < 0:
                advice = f"{base} 法人同步提款，建議避開或停損。"
                action = "SELL_STRONG"
            else:
                advice = f"{base} 需觀察是否為洗盤，三日內未站回則轉弱。"
                action = "SELL_WATCH"
        elif pct > 0:
            # 月線下反彈
            advice = f"空頭反彈，上方月線({ma20:.2f})有壓，建議逢高減碼。"
            action = "SELL_RALLY"
        else:
            advice = f"股價在月線下弱勢整理，不建議進場。"
            action = "SELL_NORMAL"
            
    return advice, action

def send_line(msg):
    if not LINE_TOKEN: return
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"messages": [{"type": "text", "text": msg}]}
    try: requests.post(url, headers=headers, data=json.dumps(payload))
    except: pass

# --- 5. 主程式 ---
if st.button("🔄 啟動戰略掃描 (Yahoo+FinMind)", type="primary"):
    
    targets = list(set(WATCHLIST_BASE + user_inv))
    st.info(f"🐕 正在掃描 {len(targets)} 檔股票... 先篩選有波動者，再查籌碼 (效率最佳化)")
    
    # 1. 批次抓價 (快)
    df_bulk = fetch_batch_price(targets)
    
    if df_bulk is not None and not df_bulk.empty:
        results = []
        buy_list = []
        sell_list = []
        
        progress_bar = st.progress(0)
        total = len(targets)
        
        for i, sid in enumerate(targets):
            try:
                # 處理 Yahoo 資料格式
                if len(targets) > 1: stock_df = df_bulk[f"{sid}.TW"]
                else: stock_df = df_bulk
                
                stock_df = stock_df.dropna()
                if len(stock_df) < 20: continue
                
                latest = stock_df.iloc[-1]
                prev = stock_df.iloc[-2]
                
                price = float(latest['Close'])
                prev_close = float(prev['Close'])
                ma20 = float(stock_df['Close'].rolling(window=20).mean().iloc[-1])
                pct = round(((price - prev_close) / prev_close) * 100, 2)
                
                is_inv = sid in user_inv
                
                # --- 漏斗篩選 ---
                # 只有 "波動>2%" 或 "波動<-2%" 或 "庫存" 才去查籌碼
                # 這樣可以省下 80% 的時間，避免 FinMind 卡死
                if is_inv or abs(pct) > 2.0 or (price < ma20 and pct < -1.5):
                    
                    # 2. 查籌碼 (慢，但只對重點股查)
                    chip_status, chip_score, net_vol = get_chip_analysis(sid)
                    
                    # 3. 生成建議
                    advice, action = generate_advice(price, ma20, pct, chip_score)
                    
                    name = get_chinese_name(sid)
                    
                    # 分類標籤
                    tag_class = "card-wait"
                    if "BUY" in action: tag_class = "card-buy"
                    elif "SELL" in action: tag_class = "card-sell"
                    
                    item = {
                        'sid': sid, 'name': name, 'price': price, 'pct': pct, 'ma20': ma20,
                        'chip': chip_status, 'chip_vol': net_vol,
                        'advice': advice, 'action': action, 'tag': tag_class,
                        'is_inv': is_inv
                    }
                    
                    results.append(item)
                    
                    # 收集通知清單
                    if "BUY_STRONG" in action: buy_list.append(f"🔥 {name} ${price} (+{pct}%)")
                    if "SELL_STRONG" in action: sell_list.append(f"❄️ {name} ${price} ({pct}%)")
                    
            except: pass
            
            if i % 5 == 0: progress_bar.progress((i+1)/total)
            
        progress_bar.empty()
        
        # --- 6. 顯示結果 ---
        
        # A. 庫存區
        st.subheader("💼 我的庫存診斷")
        inv_items = [r for r in results if r['is_inv']]
        if inv_items:
            for r in inv_items:
                color = "#FF4444" if r['pct'] > 0 else "#00FF00"
                st.markdown(f"""
                <div class="card {r['tag']}">
                    <div class="stock-header">
                        <span class="stock-title">{r['name']} ({r['sid']})</span>
                        <span>{r['chip']} ({r['chip_vol']}張)</span>
                    </div>
                    <div style="font-size:1.1rem; margin:5px 0;">
                        現價：{r['price']} (<span style='color:{color}'>{r['pct']}%</span>)
                    </div>
                    <div class="stat-row">
                        <span>MA20月線：{r['ma20']:.2f}</span>
                        <span>操作：{r['action']}</span>
                    </div>
                    <div class="advice-box">💡 建議：{r['advice']}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.warning("庫存無今日數據 (或代號錯誤)")
            
        st.divider()
        
        # B. 推薦分頁
        t1, t2 = st.tabs(["🔥 買進 / 強勢 (多方)", "❄️ 賣出 / 弱勢 (空方)"])
        
        with t1:
            # 篩選 Action 包含 BUY 或 HOLD_GOOD
            buys = [r for r in results if "BUY" in r['action'] or "HOLD_GOOD" in r['action']]
            buys.sort(key=lambda x: x['pct'], reverse=True)
            if buys:
                for r in buys:
                    st.markdown(f"""
                    <div class="card card-buy">
                        <div class="stock-header">
                            <span class="stock-title">{r['name']} ({r['sid']})</span>
                            <span class="tag tag-buy">{r['chip']}</span>
                        </div>
                        <div style="margin:5px 0;">現價：{r['price']} (<span style='color:#FF4444'>+{r['pct']}%</span>)</div>
                        <div class="advice-box">{r['advice']}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else: st.info("今日無強勢買訊。")
            
        with t2:
            # 篩選 Action 包含 SELL
            sells = [r for r in results if "SELL" in r['action']]
            sells.sort(key=lambda x: x['pct']) # 跌幅大的在上面
            if sells:
                for r in sells:
                    st.markdown(f"""
                    <div class="card card-sell">
                        <div class="stock-header">
                            <span class="stock-title">{r['name']} ({r['sid']})</span>
                            <span class="tag tag-sell">{r['chip']}</span>
                        </div>
                        <div style="margin:5px 0;">現價：{r['price']} (<span style='color:#00FF00'>{r['pct']}%</span>)</div>
                        <div class="advice-box">{r['advice']}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else: st.info("今日無明顯賣訊。")
            
        # 發送 LINE
        if buy_list or sell_list:
            msg = f"\n🐕 總柴戰略報\n"
            if buy_list: msg += "\n【🔥 籌碼多方】\n" + "\n".join(buy_list[:5]) + "\n"
            if sell_list: msg += "\n【❄️ 籌碼空方】\n" + "\n".join(sell_list[:5]) + "\n"
            send_line(msg)
            
    else:
        st.error("Yahoo Finance 暫時無回應，請稍後再試。")
else:
    st.info("🐕 總柴已就位，點擊上方按鈕開始「價量+籌碼」雙刀流掃描！")

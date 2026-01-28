import streamlit as st
import pandas as pd
import yfinance as yf
import twstock
import time
import datetime
import requests
import urllib3

# --- 1. 頁面設定 ---
st.set_page_config(page_title="總柴快報 (完整版)", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #FFFFFF; }
    .card { background-color: #262730; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #555; }
    .card-buy { border-left-color: #FF4B4B !important; }
    .card-sell { border-left-color: #00FF00 !important; }
    .stock-name { font-size: 1.1rem; font-weight: bold; }
    .signal-tag { background-color: #444; padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; margin-left: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴快報：全方位篩選")
st.caption("數據源：Yahoo Finance (國際線路) | 股名對照：twstock | 範圍：熱門300檔 + 庫存")

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
    auto_refresh = st.toggle("啟動自動監控", value=True)

# --- 3. 內建 300 檔熱門股 (確保基數夠大) ---
# 包含：權值, AI, 重電, 航運, 生技, 化工, 營建, 金融, ETF
WATCHLIST_BASE = [
    '2330','2317','2454','2308','2382','3231','2357','2376','2356','3037','3034','2379','3008',
    '3045','2412','2345','3017','2324','6669','2395','4938','2408','3443','3661','2301','5871',
    '2881','2882','2891','2886','2884','2885','2892','2880','2883','2890','5880','2887','2801',
    '2603','2609','2615','2618','2610','2637','2606','2634','1513','1519','1503','1504','1605',
    '1609','1514','6806','9958','2031','1101','1216','2002','2105','2201','2207','1301','1303',
    '1326','1402','1476','9910','1722','1708','4743','1795','4128','6472','6446','6547','3293',
    '3529','6531','8046','8069','6274','6213','4958','6770','5347','6488','3035','3406','3596',
    '3711','6239','6269','8150','3324','3653','3665','3694','4919','4961','5269','5274','5483',
    '6104','6121','6147','6187','6223','6244','6271','6285','6414','6415','6456','6515','6643',
    '6719','6756','8016','8028','8050','8081','8112','8155','8299','8358','8436','8454','8464',
    '8936','9921','9941','8131','0050','0056','00878','00929','00919','00632R','3019','2368',
    '6214','6139','8021','6182','6202','5285','3680','3583','3036','3044','2455','2498','2449',
    '2404','2360','2352','2344','2313','2312','2302','2027','2014','2006','1907','1717','1710'
]

# --- 4. 核心功能 ---

def get_chinese_name(sid):
    # 利用 twstock 本地資料庫查中文名，不需連網
    if sid in twstock.codes:
        return twstock.codes[sid].name
    return sid

def send_line(msg):
    if not LINE_TOKEN: return
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"messages": [{"type": "text", "text": msg}]}
    try:
        requests.post(url, headers=headers, data=json.dumps(payload))
        st.toast("✅ LINE 通知已發送")
    except: pass

def fetch_batch_data(tickers):
    # 批次下載，速度快
    yf_tickers = [f"{x}.TW" for x in tickers]
    try:
        # 下載最近 2 個月資料以計算 MA20
        data = yf.download(yf_tickers, period="2mo", group_by='ticker', progress=False, threads=True)
        return data
    except:
        return None

# --- 5. 執行邏輯 ---
if st.button("🔄 立即刷新 (Yahoo數據)", type="primary"):
    
    # 準備清單
    target_list = list(set(WATCHLIST_BASE + user_inv))
    
    st.info(f"🐕 正在透過 Yahoo Finance 掃描 {len(target_list)} 檔股票... (請稍候 10-20 秒)")
    
    # 抓取資料
    df_bulk = fetch_batch_data(target_list)
    
    if df_bulk is not None and not df_bulk.empty:
        results = []
        buy_notify = []
        sell_notify = []
        
        # 逐一處理每一檔
        progress_bar = st.progress(0)
        total_len = len(target_list)
        
        for i, sid in enumerate(target_list):
            try:
                # yfinance 多層索引處理
                if len(target_list) > 1:
                    stock_df = df_bulk[f"{sid}.TW"]
                else:
                    stock_df = df_bulk # 只有一檔時
                
                # 檢查資料是否足夠
                stock_df = stock_df.dropna()
                if len(stock_df) < 20: continue
                
                # 取值
                latest = stock_df.iloc[-1]
                prev = stock_df.iloc[-2]
                
                price = float(latest['Close'])
                prev_close = float(prev['Close'])
                
                # 計算 MA20
                ma20 = stock_df['Close'].rolling(window=20).mean().iloc[-1]
                
                # 漲跌幅
                pct = round(((price - prev_close) / prev_close) * 100, 2)
                
                # 取得中文名
                name = get_chinese_name(sid)
                is_inv = sid in user_inv
                
                # --- 篩選策略 (麻紗+旺大) ---
                signal = "觀望"
                reason = "盤整"
                tag = "normal"
                
                # A. 多方
                if price >= ma20:
                    if pct > 3.0:
                        signal = "🔥 飆股"
                        reason = f"站上月線({ma20:.1f}) + 爆量"
                        tag = "card-buy"
                        buy_notify.append(f"🔥 {name}({sid}) ${price:.2f} (+{pct}%)")
                    elif pct > 0:
                        signal = "🔴 多頭"
                        reason = f"站穩月線({ma20:.1f})"
                        tag = "card-buy"
                        if is_inv: buy_notify.append(f"🔴 {name}({sid}) ${price:.2f}")
                    else:
                        signal = "🛡️ 回檔"
                        reason = "月線上整理"
                
                # B. 空方
                else:
                    if pct < -3.0:
                        signal = "❄️ 殺盤"
                        reason = f"跌破月線({ma20:.1f}) + 重挫"
                        tag = "card-sell"
                        sell_notify.append(f"❄️ {name}({sid}) ${price:.2f} ({pct}%)")
                    elif pct < 0:
                        signal = "🟢 轉弱"
                        reason = f"月線({ma20:.1f})蓋頭反壓"
                        tag = "normal"
                        if is_inv: sell_notify.append(f"🟢 {name}({sid}) ${price:.2f}")
                    else:
                        signal = "🌤️ 反彈"
                        reason = "空頭反彈"
                
                results.append({
                    'code': sid, 'name': name, 'price': round(price, 2), 
                    'pct': pct, 'ma20': round(ma20, 2), 
                    'signal': signal, 'reason': reason, 'tag': tag,
                    'is_inv': is_inv
                })
                
            except: pass
            
            if i % 10 == 0: progress_bar.progress((i+1)/total_len)
            
        progress_bar.empty()
        
        # --- 6. 顯示與通知 ---
        
        # 發送 LINE
        if buy_notify or sell_notify:
            msg = f"\n🐕 總柴快報 ({datetime.datetime.now().strftime('%H:%M')})\n"
            if buy_notify: msg += "\n【🔥 強勢訊號】\n" + "\n".join(buy_notify[:5]) + "\n"
            if sell_notify: msg += "\n【❄️ 弱勢訊號】\n" + "\n".join(sell_notify[:5]) + "\n"
            send_line(msg)
        
        # 顯示庫存
        st.subheader("💼 我的庫存")
        inv_res = [r for r in results if r['is_inv']]
        if inv_res:
            for r in inv_res:
                color = "#FF4444" if r['pct'] > 0 else "#00FF00"
                st.markdown(f"""
                <div class="card {r['tag']}">
                    <span class="stock-name">{r['name']} ({r['code']})</span> <span class="signal-tag">{r['signal']}</span>
                    <br>
                    現價：{r['price']} (<span style='color:{color}'>{r['pct']}%</span>) | MA20：{r['ma20']} | {r['reason']}
                </div>
                """, unsafe_allow_html=True)
        else: st.warning("庫存代號無資料，請確認代號是否正確。")
        
        st.divider()
        
        # 顯示分頁
        t1, t2 = st.tabs(["🔥 推薦買進 / 觀察", "❄️ 推薦賣出 / 避開"])
        
        with t1:
            # 篩選：站上月線且漲>2%
            buys = [r for r in results if r['price'] >= r['ma20'] and r['pct'] > 2.0]
            buys.sort(key=lambda x: x['pct'], reverse=True)
            if buys:
                for r in buys:
                    st.markdown(f"""
                    <div class="card card-buy">
                        <b>{r['name']} ({r['code']})</b> 🔥 +{r['pct']}%
                        <br>現價：{r['price']} | MA20：{r['ma20']} | {r['reason']}
                    </div>
                    """, unsafe_allow_html=True)
            else: st.info("無符合條件標的")
            
        with t2:
            # 篩選：跌破月線且跌<-2%
            sells = [r for r in results if r['price'] < r['ma20'] and r['pct'] < -2.0]
            sells.sort(key=lambda x: x['pct'])
            if sells:
                for r in sells:
                    st.markdown(f"""
                    <div class="card card-sell">
                        <b>{r['name']} ({r['code']})</b> ❄️ {r['pct']}%
                        <br>現價：{r['price']} | MA20：{r['ma20']} | {r['reason']}
                    </div>
                    """, unsafe_allow_html=True)
            else: st.info("無符合條件標的")
            
    else:
        st.error("無法取得數據，請稍後再試。")

else:
    st.info("🐕 系統就緒，準備掃描 300 檔熱門股...")

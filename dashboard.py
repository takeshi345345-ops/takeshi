import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
from FinMind.data import DataLoader

# --- 1. 系統設定 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# 修正 SSL
old_merge = requests.Session.merge_environment_settings
def new_merge(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url: verify = False
    return old_merge(self, url, proxies, stream, verify, cert)
requests.Session.merge_environment_settings = new_merge

st.set_page_config(page_title="總柴快報", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #FFFFFF; }
    .status-box { padding: 10px; border-radius: 5px; background: #222; text-align: center; margin-bottom: 10px; border: 1px solid #444; color: #FFD700; }
    .chip-buy { color: #FF4444; font-weight: bold; background: #330000; padding: 2px 6px; border-radius: 4px; border: 1px solid #FF4444; }
    .chip-sell { color: #00FF00; font-weight: bold; background: #003300; padding: 2px 6px; border-radius: 4px; border: 1px solid #00FF00; }
    thead tr th:first-child {display:none}
    tbody th {display:none}
</style>
""", unsafe_allow_html=True)

# --- 2. 內建 150 檔重點監控 (保證有資料) ---
WATCHLIST = [
    '2330','2317','2454','2308','2303','2382','3231','2357','2376','2356','3037','3034','2379','3008',
    '3045','2412','2345','3017','2324','6669','2395','4938','2408','3443','3661','2301','5871','2881',
    '2882','2891','2886','2884','2885','2892','2880','2883','2890','5880','2887','2801','2603','2609',
    '2615','2618','2610','2637','2606','2634','1513','1519','1503','1504','1605','1609','1514','6806',
    '9958','2031','1101','1216','2002','2105','2201','2207','1301','1303','1326','1402','1476','9910',
    '1722','1708','4743','1795','4128','6472','6446','6547','3293','3529','6531','8046','8069','6274',
    '6213','4958','6770','5347','6488','3035','3406','3596','3711','6239','6269','8150','3324','3653',
    '3665','3694','4919','4961','5269','5274','5483','6104','6121','6147','6187','6223','6244','6271',
    '6285','6414','6415','6456','6515','6643','6719','6756','8016','8028','8050','8081','8112','8155'
]

# --- 3. 設定 ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

with st.sidebar:
    st.header("⚙️ 設定")
    inv_input = st.text_area("庫存代號", "8131")
    portfolio = [x.strip() for x in inv_input.split(",") if x.strip()]
    auto_refresh = st.toggle("啟動自動監控", value=True)

# --- 4. 核心功能 ---
def get_time_status():
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    if now.weekday() >= 5: return "🌙 假日休市 (結算數據)"
    if datetime.time(9,0) <= now.time() <= datetime.time(13,35):
        return "☀️ 盤中即時 (Live)"
    return "🌙 盤後結算 (Final)"

# 取得 MA20
def get_ma20(sid):
    try:
        stock = twstock.Stock(sid)
        hist = stock.fetch_from(2024, 1)
        if len(hist) < 20: return None
        return sum([x.close for x in hist[-20:]]) / 20
    except: return None

# 取得籌碼
def get_chips(sid):
    try:
        dl = DataLoader()
        start = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=start)
        if df.empty: return "-", 0
        recent = df.tail(6)
        net = recent['buy'].sum() - recent['sell'].sum()
        if net > 500000: return "法人大買", 2
        if net > 0: return "法人小買", 1
        if net < -500000: return "法人大賣", -2
        if net < 0: return "法人小賣", -1
        return "-", 0
    except: return "-", 0

# --- 5. 掃描引擎 (無差別全掃描) ---
def run_scanner(user_port):
    results = []
    buy_notify = []
    sell_notify = []
    
    # 1. 準備清單
    targets = list(set(user_port + WATCHLIST))
    total = len(targets)
    
    st.toast(f"🐕 啟動無差別掃描！目標 {total} 檔 (請稍候)...")
    
    bar = st.progress(0)
    status_text = st.empty()
    
    # 2. 批次抓取 (改成極小批次，避免漏抓)
    BATCH = 5
    
    for i in range(0, total, BATCH):
        batch_codes = targets[i:i+BATCH]
        progress = min((i + BATCH) / total, 0.99)
        bar.progress(progress)
        status_text.text(f"正在分析第 {i+1}~{min(i+BATCH, total)} 檔...")
        
        try:
            stocks = twstock.realtime.get(batch_codes)
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        rt = data['realtime']
                        try: price = float(rt['latest_trade_price'])
                        except: 
                            try: price = float(rt['best_bid_price'][0])
                            except: continue
                        if price == 0: continue
                        
                        try: prev = float(rt['previous_close'])
                        except: prev = price
                        
                        pct = round(((price-prev)/prev)*100, 2)
                        name = data['info']['name']
                        is_inv = sid in user_port
                        
                        # === 修正重點：全部都要算 MA20，不做任何過濾 ===
                        # 雖然這樣慢一點，但保證資料完整
                        
                        ma20 = get_ma20(sid)
                        if not ma20: ma20 = prev # 防呆
                        
                        # 只有當波動大或庫存時，才去查籌碼 (節省時間)
                        chip_msg = "-"
                        chip_score = 0
                        if is_inv or abs(pct) > 2.0:
                            chip_msg, chip_score = get_chips(sid)
                        
                        signal = "➖ 觀望"
                        reason = "-"
                        code_val = 0
                        
                        # A. 買方邏輯
                        if pct > 0:
                            if price >= ma20: # 站上月線
                                if pct > 3.0:
                                    signal = "🔥 推薦買進"
                                    reason = f"站穩月線({ma20:.1f})+爆量"
                                    code_val = 10
                                    if chip_score < 0: signal = "⚠️ 小心誘多"
                                    else: buy_notify.append(f"🔥 {name} ${price} (+{pct}%)")
                                else:
                                    signal = "🔴 多頭排列"
                                    reason = "站穩月線"
                                    code_val = 5
                                    if is_inv: buy_notify.append(f"🔴 {name} ${price} (+{pct}%)")
                            else:
                                signal = "🌤️ 反彈"
                                reason = "月線下"
                                code_val = 1
                        
                        # B. 賣方邏輯
                        elif pct < 0:
                            if price < ma20: # 破月線
                                if pct < -3.0:
                                    signal = "❄️ 推薦賣出"
                                    reason = f"跌破月線({ma20:.1f})+重挫"
                                    code_val = -10
                                    sell_notify.append(f"❄️ {name} ${price} ({pct}%)")
                                else:
                                    signal = "🟢 轉弱"
                                    reason = "跌破月線"
                                    code_val = -5
                                    if is_inv: sell_notify.append(f"🟢 {name} ${price} ({pct}%)")
                            else:
                                signal = "📉 回檔"
                                reason = "月線上"
                                code_val = -1
                        
                        # 只要有抓到，全部列入！不准過濾！
                        results.append({
                            "代號": sid, "名稱": name, "現價": price, "漲幅": pct,
                            "訊號": signal, "理由": reason, "籌碼": chip_msg,
                            "MA20": round(ma20, 2), "code": code_val, "is_inv": is_inv
                        })
            
            time.sleep(0.1) # 休息一下
            
        except: pass

    bar.empty()
    status_text.empty()
    return pd.DataFrame(results), buy_notify, sell_notify

def send_line_notify(buys, sells):
    if not LINE_TOKEN: return
    msg = f"\n🐕 總柴快報 ({get_time_status()})\n"
    has_msg = False
    
    if buys:
        msg += "\n【🔥 強勢訊號】\n" + "\n".join(buys[:5]) + "\n"
        has_msg = True
    if sells:
        msg += "\n【❄️ 弱勢訊號】\n" + "\n".join(sells[:5]) + "\n"
        has_msg = True
        
    if has_msg:
        url = "https://api.line.me/v2/bot/message/broadcast"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
        requests.post(url, headers=headers, data=json.dumps({"messages": [{"type": "text", "text": msg}]}))
        st.toast("LINE 通知已發送")

# --- 6. 主介面 ---
status_now = get_time_status()
st.title("🐕 總柴快報")
st.markdown(f"<div class='status-box'>{status_now}</div>", unsafe_allow_html=True)

if 'data' not in st.session_state: st.session_state.data = pd.DataFrame()

run = False
if st.session_state.data.empty: run = True
if st.button("🔄 立即刷新 (全無過濾)"): run = True

if run:
    df, buys, sells = run_scanner(portfolio)
    st.session_state.data = df
    if buys or sells: send_line_notify(buys, sells)

# 顯示表格
df_show = st.session_state.data
if not df_show.empty:
    
    if portfolio:
        st.subheader("💼 我的庫存")
        inv_df = df_show[df_show['is_inv'] == True]
        if not inv_df.empty:
            for r in inv_df.to_dict('records'):
                color = "#FF4444" if r['漲幅'] > 0 else "#00FF00"
                st.markdown(f"**{r['名稱']} ({r['代號']})**: {r['訊號']} <span style='color:#ccc'>({r['理由']})</span><br>${r['現價']} (<span style='color:{color}'>{r['漲幅']}%</span>) | MA20: {r['MA20']}", unsafe_allow_html=True)
        else: st.info("庫存無資料")
            
    st.divider()
    
    t1, t2, t3 = st.tabs(["🔥 推薦買進", "❄️ 推薦賣出", "📋 全部清單 (150檔)"])
    cols = ['代號', '名稱', '現價', '漲幅', '訊號', '籌碼', '理由']
    
    with t1:
        d1 = df_show[df_show['code'] >= 5].sort_values('漲幅', ascending=False)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
        
    with t2:
        d2 = df_show[df_show['code'] <= -5].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
        
    with t3:
        # 這裡就是你要的：所有 150 檔全部列出來，沒過濾！
        st.dataframe(df_show, column_order=cols, use_container_width=True, hide_index=True)

else:
    st.info("🐕 準備掃描中...")

if auto_refresh and "盤中" in status_now:
    time.sleep(300)
    st.rerun()

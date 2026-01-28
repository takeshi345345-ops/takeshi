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
# 修復 SSL 問題
old_merge = requests.Session.merge_environment_settings
def new_merge(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url: verify = False
    return old_merge(self, url, proxies, stream, verify, cert)
requests.Session.merge_environment_settings = new_merge

st.set_page_config(page_title="總柴快報", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #FFFFFF; }
    .status-box { padding: 10px; border-radius: 5px; background: #222; text-align: center; margin-bottom: 10px; border: 1px solid #444; }
    .chip-buy { color: #FF4444; font-weight: bold; background: #330000; padding: 2px 6px; border-radius: 4px; border: 1px solid #FF4444; }
    .chip-sell { color: #00FF00; font-weight: bold; background: #003300; padding: 2px 6px; border-radius: 4px; border: 1px solid #00FF00; }
    thead tr th:first-child {display:none}
    tbody th {display:none}
</style>
""", unsafe_allow_html=True)

# --- 2. 參數設定 ---
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

# --- 3. 核心功能模組 ---

def get_time_status():
    # 判斷是盤中還是盤後
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    if now.weekday() >= 5: return "🌙 假日休市 (查看收盤數據)"
    
    t = now.time()
    if datetime.time(9,0) <= t <= datetime.time(13,35):
        return "☀️ 盤中即時 (Live)"
    return "🌙 盤後結算 (Final)"

@st.cache_data(ttl=300) # 快取 5 分鐘，避免頻繁爬蟲被鎖
def scrape_yahoo_candidates():
    # 策略：直接抓 Yahoo 漲跌幅排行前 60 名，作為「候選人」
    # 這比掃描全市場快 100 倍
    candidates = []
    try:
        # 抓上漲
        df_up = pd.read_html("https://tw.stock.yahoo.com/rank/change-up?exchange=TAI")[0]
        # 抓下跌
        df_down = pd.read_html("https://tw.stock.yahoo.com/rank/change-down?exchange=TAI")[0]
        
        # 統一處理函數
        def process_yahoo_df(df, trend):
            cols = [c for c in df.columns if '股號' in c or '代號' in c or '名稱' in c or '成交' in c or '漲跌幅' in c]
            df = df[cols]
            # 重新命名以方便處理
            df.columns = ['info', 'price', 'pct'] if len(df.columns) == 3 else df.columns # 簡易防呆
            
            extracted = []
            for i, row in df.head(40).iterrows(): # 只取前40名
                try:
                    # 解析代號與名稱 (Yahoo 有時會黏在一起)
                    raw_info = str(row.iloc[0]) # 第一欄通常是代號/名稱
                    sid = ''.join(filter(str.isdigit, raw_info))
                    if len(sid) == 4:
                        name = raw_info.replace(sid, '').strip()
                        price = float(row.iloc[1]) # 第二欄是價格
                        pct_raw = str(row.iloc[-1]).replace('%','').replace('+','') # 最後一欄是漲跌幅
                        pct = float(pct_raw)
                        extracted.append({'sid': sid, 'name': name, 'price': price, 'pct': pct})
                except: continue
            return extracted

        candidates.extend(process_yahoo_df(df_up, 'up'))
        candidates.extend(process_yahoo_df(df_down, 'down'))
        
    except Exception as e:
        print(f"Yahoo 爬蟲錯誤: {e}")
        
    return candidates

def get_stock_technical(sid):
    # 計算 MA20
    try:
        stock = twstock.Stock(sid)
        hist = stock.fetch_from(2024, 1)
        if len(hist) < 20: return None
        return sum([x.close for x in hist[-20:]]) / 20
    except: return None

def get_stock_chips(sid):
    # 計算法人籌碼 (近3日)
    try:
        dl = DataLoader()
        start = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=start)
        if df.empty: return "無資料", 0
        
        recent = df.tail(6) # 外資+投信 * 3天
        net = recent['buy'].sum() - recent['sell'].sum()
        
        if net > 500000: return "法人大買", 2
        if net > 0: return "法人小買", 1
        if net < -500000: return "法人大賣", -2
        if net < 0: return "法人小賣", -1
        return "中性", 0
    except: return "查詢失敗", 0

# --- 4. 主邏輯引擎 ---
def run_analysis(user_port):
    results = []
    buy_notify = []
    sell_notify = []
    
    # 1. 取得候選名單 (Yahoo 排行榜 + 庫存)
    # 先轉成 Dict 去重
    candidates_map = {item['sid']: item for item in scrape_yahoo_candidates()}
    
    # 確保庫存有被加入 (如果庫存沒上榜，要去補抓它的即時價)
    for port_sid in user_port:
        if port_sid not in candidates_map:
            try:
                s = twstock.realtime.get(port_sid)
                if s[port_sid]['success']:
                    rt = s[port_sid]['realtime']
                    p = float(rt['latest_trade_price'])
                    try: pre = float(rt['previous_close'])
                    except: pre = p
                    pct = round(((p-pre)/pre)*100, 2)
                    candidates_map[port_sid] = {'sid': port_sid, 'name': s[port_sid]['info']['name'], 'price': p, 'pct': pct}
            except: pass

    check_list = list(candidates_map.values())
    total = len(check_list)
    
    # 2. 開始深度篩選
    status_text = st.empty()
    bar = st.progress(0)
    
    for i, stock in enumerate(check_list):
        # 更新進度
        bar.progress((i+1)/total)
        status_text.text(f"正在分析第 {i+1}/{total} 檔：{stock['name']}...")
        
        sid = stock['sid']
        price = stock['price']
        pct = stock['pct']
        name = stock['name']
        is_inv = sid in user_port
        
        # 篩選漏斗：只分析「庫存」或「漲跌幅 > 2.5%」的股票
        # 節省時間，不重要的盤整股直接跳過
        if not is_inv and abs(pct) < 2.5:
            continue
            
        # 3. 深度運算 (MA20 + 籌碼)
        ma20 = get_stock_technical(sid)
        if not ma20: ma20 = price # 防呆
        
        chip_msg, chip_score = get_stock_chips(sid)
        
        # 4. 判斷訊號
        signal = "➖ 觀望"
        reason = "-"
        code_val = 0
        
        # [買方邏輯]
        if pct > 0:
            if price >= ma20: # 站上月線
                if pct > 3.0: 
                    signal = "🔥 推薦買進"
                    reason = f"站穩月線({ma20:.1f})+爆量"
                    code_val = 10
                    # 如果法人在賣，扣分
                    if chip_score < 0: 
                        signal = "⚠️ 小心誘多"
                        reason += " (但法人賣)"
                        code_val = 2
                    else:
                        buy_notify.append(f"🔥 {name} ${price} (+{pct}%) | {chip_msg}")
                else:
                    signal = "🔴 多頭排列"
                    reason = "月線之上"
                    code_val = 5
            else: # 月線下
                signal = "🌤️ 反彈"
                reason = "空頭反彈(月線下)"
                code_val = 2
        
        # [賣方邏輯]
        elif pct < 0:
            if price < ma20: # 跌破月線
                if pct < -3.0:
                    signal = "❄️ 推薦賣出"
                    reason = f"跌破月線({ma20:.1f})+重挫"
                    code_val = -10
                    sell_notify.append(f"❄️ {name} ${price} ({pct}%) | {chip_msg}")
                else:
                    signal = "🟢 轉弱"
                    reason = "月線之下"
                    code_val = -5
            else: # 月線上回檔
                signal = "📉 回檔"
                reason = "多頭回測"
                code_val = -1

        results.append({
            "代號": sid, "名稱": name, "現價": price, "漲幅": pct,
            "訊號": signal, "理由": reason, "籌碼": chip_msg,
            "MA20": round(ma20, 2), "code": code_val, "is_inv": is_inv
        })
        
        time.sleep(0.05) # 避免 API 鎖死

    bar.empty()
    status_text.empty()
    return pd.DataFrame(results), buy_notify, sell_notify

def send_line_notify(buys, sells, inv_list):
    if not LINE_TOKEN: return
    
    msg = f"\n🐕 總柴快報 ({get_time_status()})\n"
    has_msg = False
    
    # 庫存
    inv_msgs = [x['msg'] for x in buys if x['is_inv']] # 這裡簡化邏輯，庫存另外處理較好，但先共用結構
    # 為了簡化，直接重組
    
    if buys:
        msg += "\n【🔥 飆股訊號】\n" + "\n".join(buys[:5]) + "\n"
        has_msg = True
    if sells:
        msg += "\n【❄️ 避雷訊號】\n" + "\n".join(sells[:5]) + "\n"
        has_msg = True
        
    if has_msg:
        url = "https://api.line.me/v2/bot/message/broadcast"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
        payload = {"messages": [{"type": "text", "text": msg}]}
        requests.post(url, headers=headers, data=json.dumps(payload))
        st.toast("LINE 通知已發送")

# --- 5. 介面呈現 ---
status_now = get_time_status()
st.title("🐕 總柴快報")
st.markdown(f"<div class='status-box'>{status_now}</div>", unsafe_allow_html=True)

# Session State 管理
if 'data' not in st.session_state: st.session_state.data = pd.DataFrame()

# 觸發邏輯
run = False
if st.session_state.data.empty: run = True
if st.button("🔄 立即刷新"): run = True

if run:
    df, buys, sells = run_analysis(portfolio)
    st.session_state.data = df
    # 這裡發送通知 (可加入時間判斷，避免一直發)
    if buys or sells:
        # 簡單做：庫存只要有在清單裡就挑出來發
        # 這裡為了展示，先發送前幾名
        send_line_notify(buys, sells, portfolio)

# 顯示表格
df_show = st.session_state.data
if not df_show.empty:
    
    # 庫存區
    if portfolio:
        st.subheader("💼 我的庫存")
        inv_df = df_show[df_show['is_inv'] == True]
        if not inv_df.empty:
            for r in inv_df.to_dict('records'):
                color = "#FF4444" if r['漲幅'] > 0 else "#00FF00"
                chip_cls = "chip-buy" if "買" in r['籌碼'] else ("chip-sell" if "賣" in r['籌碼'] else "")
                chip_tag = f"<span class='{chip_cls}'>{r['籌碼']}</span>"
                st.markdown(f"**{r['名稱']} ({r['代號']})**: {r['訊號']} {chip_tag}<br>${r['現價']} (<span style='color:{color}'>{r['漲幅']}%</span>) | MA20: {r['MA20']}", unsafe_allow_html=True)
        else:
            st.info("庫存今日無波動，未進入分析清單。")
            
    st.divider()
    
    t1, t2, t3 = st.tabs(["🔥 推薦買進", "❄️ 推薦賣出", "全部清單"])
    
    cols = ['代號', '名稱', '現價', '漲幅', '訊號', '籌碼', '理由']
    
    with t1:
        # 篩選 code > 5 的 (推薦買進)
        d1 = df_show[df_show['code'] >= 5].sort_values('漲幅', ascending=False)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
        
    with t2:
        # 篩選 code < -5 的 (推薦賣出)
        d2 = df_show[df_show['code'] <= -5].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
        
    with t3:
        st.dataframe(df_show, column_order=cols, use_container_width=True, hide_index=True)

else:
    st.info("請點擊刷新按鈕開始分析...")

if auto_refresh and "盤中" in status_now:
    time.sleep(300)
    st.rerun()

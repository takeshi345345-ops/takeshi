import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
from FinMind.data import DataLoader

# --- 1. SSL 修正 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
old_merge_environment_settings = requests.Session.merge_environment_settings

def merge_environment_settings(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url:
        verify = False
    return old_merge_environment_settings(self, url, proxies, stream, verify, cert)

requests.Session.merge_environment_settings = merge_environment_settings

# --- 2. 頁面設定 (標題固定) ---
st.set_page_config(
    page_title="總柴快報", # 固定標題
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #FFFFFF; }
    h1, h2, h3 { color: #00E5FF !important; }
    .status-bar { background: #222; padding: 8px; border-radius: 5px; text-align: center; color: #aaa; font-size: 0.8rem; margin-bottom: 15px;}
    thead tr th:first-child {display:none}
    tbody th {display:none}
    /* 籌碼標籤 */
    .chip-buy { background-color: #330000; color: #FF4444; padding: 2px 5px; border-radius: 4px; border: 1px solid #FF4444; font-size: 0.8em; }
    .chip-sell { background-color: #003300; color: #00FF00; padding: 2px 5px; border-radius: 4px; border: 1px solid #00FF00; font-size: 0.8em; }
</style>
""", unsafe_allow_html=True)

# --- 3. 設定 ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

with st.sidebar:
    st.header("⚙️ 設定")
    auto_refresh = st.toggle("啟動自動監控", value=True)
    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號", "8131")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]

def send_line(msg):
    if not LINE_TOKEN: return False, "No Token"
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"messages": [{"type": "text", "text": msg}]}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload))
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

def get_taiwan_time():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)

def get_market_status():
    now = get_taiwan_time()
    if now.weekday() >= 5: return "closed", "🌙 假日休市"
    start = now.replace(hour=9, minute=0, second=0)
    end = now.replace(hour=13, minute=30, second=0)
    if start <= now <= end: return "open", "☀️ 盤中即時"
    else: return "closed", "🌙 盤後結算"

# --- 4. 抓全台股代號 ---
@st.cache_data(ttl=3600*24)
def get_all_stock_codes():
    codes = []
    for code, info in twstock.codes.items():
        if info.market == '上市' and info.type == '股票' and len(code) == 4:
            codes.append(code)
    return sorted(codes)

# --- 5. 核心分析：MA20 + 法人籌碼 ---
def analyze_stock_deep(sid):
    # 回傳: (ma20, 籌碼狀態字串, 籌碼分數)
    # 籌碼分數: >0 偏多, <0 偏空
    try:
        # 1. 技術面：MA20
        stock = twstock.Stock(sid)
        stock.fetch_from(2024, 1)
        if len(stock.price) < 20: return None, "資料不足", 0
        ma20 = sum(stock.price[-20:]) / 20
        
        # 2. 籌碼面：法人動向 (FinMind)
        # 由於 FinMind 盤中抓不到當下，我們抓「最近 3 個交易日」的累積買賣超
        # 作為趨勢判斷
        dl = DataLoader()
        start_date = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=start_date)
        
        chip_msg = "籌碼中性"
        chip_score = 0
        
        if not df.empty:
            # 取最近 3 天數據 (外資 + 投信)
            recent = df.tail(6) # 大約是3天份
            buy_vol = recent['buy'].sum()
            sell_vol = recent['sell'].sum()
            net = buy_vol - sell_vol
            
            # 判斷強度 (簡單用張數判斷，雖不嚴謹但夠快)
            if net > 1000000: # 買超 > 1000張 (單位是股)
                chip_msg = "法人大買"
                chip_score = 2
            elif net > 0:
                chip_msg = "法人小買"
                chip_score = 1
            elif net < -1000000:
                chip_msg = "法人大賣"
                chip_score = -2
            elif net < 0:
                chip_msg = "法人小賣"
                chip_score = -1
                
        return ma20, chip_msg, chip_score
        
    except: 
        return None, "查無籌碼", 0

# --- 6. 掃描邏輯 ---
def scan_full_market(user_port):
    results = []
    buy_sigs = []
    sell_sigs = []
    
    all_targets = get_all_stock_codes()
    targets = list(set(all_targets + user_port))
    total_count = len(targets)
    
    st.toast(f"🐕 總柴啟動全市場掃描 (含法人籌碼分析)... 目標 {total_count} 檔")
    
    bar = st.progress(0)
    status_text = st.empty()
    BATCH = 50 
    
    for i in range(0, total_count, BATCH):
        batch = targets[i:i+BATCH]
        progress = min((i + BATCH) / total_count, 0.99)
        bar.progress(progress)
        status_text.text(f"掃描進度：{i}/{total_count}...")
        
        try:
            stocks = twstock.realtime.get(batch)
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
                        
                        # === 漏斗篩選 ===
                        # 1. 庫存 (必查)
                        # 2. 漲跌幅 > 2.5% (有行情才查)
                        if is_inv or abs(pct) > 2.5:
                            ma20, chip_msg, chip_score = analyze_stock_deep(sid)
                            
                            if not ma20: ma20 = prev # 防呆
                            
                            signal = "➖ 觀望"
                            reason = "-"
                            code_val = 0
                            
                            # --- 買進邏輯 (技術+籌碼) ---
                            if pct > 0:
                                # 條件：站上月線 + 漲幅夠大
                                if price >= ma20 and pct > 3.0:
                                    # 加分項：法人有買
                                    if chip_score >= 0:
                                        signal = "🔥 推薦買進"
                                        reason = f"🚀 站穩月線+長紅 ({chip_msg})"
                                        code_val = 10
                                        buy_sigs.append({'msg': f"🔥 {name} ${price} (+{pct}%) | {chip_msg}", 'is_inv': is_inv})
                                    else:
                                        # 雖然漲，但法人在賣，小心是假突破
                                        signal = "⚠️ 拉高出貨?"
                                        reason = f"股價漲但{chip_msg}"
                                        code_val = 2
                                        
                                elif price >= ma20:
                                    signal = "🔴 多頭排列"
                                    reason = "🛡️ 守穩月線"
                                    code_val = 5
                                    if is_inv: buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%) | {chip_msg}", 'is_inv': is_inv})
                            
                            # --- 賣出邏輯 ---
                            elif pct < 0:
                                # 條件：跌破月線 + 跌幅大
                                if price < ma20 and pct < -3.0:
                                    # 加分項：法人也在賣
                                    if chip_score <= 0:
                                        signal = "❄️ 推薦賣出"
                                        reason = f"📉 破線重挫 ({chip_msg})"
                                        code_val = -10
                                        sell_sigs.append({'msg': f"❄️ {name} ${price} ({pct}%) | {chip_msg}", 'is_inv': is_inv})
                                
                                elif price < ma20:
                                    signal = "🟢 轉弱破線"
                                    reason = f"❌ 跌破月線"
                                    code_val = -5
                                    if is_inv: sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%) | {chip_msg}", 'is_inv': is_inv})

                            results.append({
                                '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                                '訊號': signal, '理由': reason, '籌碼': chip_msg,
                                'MA20': round(ma20, 2), 'code': code_val, 'is_inv': is_inv
                            })
            
            time.sleep(0.2)
        except: pass
    
    bar.empty()
    status_text.empty()
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 7. 主程式 ---
if 'last_scan_data' not in st.session_state:
    st.session_state.last_scan_data = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = "尚未更新"

run_now = False
trigger_source = "auto"
status_code, status_text = get_market_status()

# 1. 初始載入
if st.session_state.last_scan_data.empty:
    run_now = True; trigger_source = "init"

# 2. 手動
if st.button(f"🔄 立即刷新 ({'盤後' if status_code=='closed' else '盤中'})", type="primary"):
    run_now = True; trigger_source = "manual"

# 3. 排程
now_tw = get_taiwan_time()
h = now_tw.hour
m = now_tw.minute

if 'done_830' not in st.session_state: st.session_state.done_830 = False
if 'done_915' not in st.session_state: st.session_state.done_915 = False
if 'done_1230' not in st.session_state: st.session_state.done_1230 = False

curr_date = now_tw.date()
if 'run_date' not in st.session_state or st.session_state.run_date != curr_date:
    st.session_state.run_date = curr_date
    st.session_state.done_830 = False
    st.session_state.done_915 = False
    st.session_state.done_1230 = False

if not run_now:
    if status_code == "open": 
        if h == 9 and 15 <= m <= 30 and not st.session_state.done_915:
            run_now = True; trigger_source = "915"
        elif h == 12 and 30 <= m <= 45 and not st.session_state.done_1230:
            run_now = True; trigger_source = "1230"
    elif status_code == "closed":
        if h == 8 and 30 <= m <= 45 and not st.session_state.done_830:
            run_now = True; trigger_source = "830"

if run_now:
    df, buys, sells = scan_full_market(portfolio)
    st.session_state.last_scan_data = df
    st.session_state.last_update_time = now_tw.strftime("%H:%M")
    
    if trigger_source == "830": st.session_state.done_830 = True
    elif trigger_source == "915": st.session_state.done_915 = True
    elif trigger_source == "1230": st.session_state.done_1230 = True

    # LINE
    if LINE_TOKEN and trigger_source != "init":
        msg_body = ""
        should_send = False
        
        my_msgs = [x['msg'] for x in buys if x['is_inv']] + [x['msg'] for x in sells if x['is_inv']]
        if my_msgs: 
            msg_body += "\n【💼 庫存警示】\n" + "\n".join(my_msgs) + "\n"
            should_send = True

        hot_buys = [x['msg'] for x in buys if not x['is_inv'] and "🔥" in x['msg']]
        try: hot_buys.sort(key=lambda x: float(x.split('+')[-1].replace('%)','')), reverse=True)
        except: pass
        
        if hot_buys: 
            msg_body += "\n【🔥 推薦買進】\n" + "\n".join(hot_buys[:5]) + "\n"
            should_send = True
            
        hot_sells = [x['msg'] for x in sells if not x['is_inv'] and "❄️" in x['msg']]
        try: hot_sells.sort(key=lambda x: float(x.split('(')[-1].split('%')[0]))
        except: pass
        
        if hot_sells: 
            msg_body += "\n【❄️ 推薦賣出】\n" + "\n".join(hot_sells[:5]) + "\n"
            should_send = True

        if should_send or trigger_source == "manual":
            title = f"🐕 總柴快報 ({status_text})"
            if not should_send: msg_body = "\n(全市場平靜，無符合條件標的)"
            send_line(title + "\n" + msg_body)
            st.toast("✅ LINE 已發送")

# --- 8. 顯示 ---
# 這裡永遠顯示固定標題，不要再變了
st.title(f"🐕 總柴快報")
st.markdown(f"<div class='status-bar'>🕒 更新時間: {st.session_state.last_update_time} | {status_text}</div>", unsafe_allow_html=True)

df_show = st.session_state.last_scan_data
if not df_show.empty:
    if portfolio:
        st.markdown("### 💼 我的庫存")
        if 'is_inv' in df_show.columns:
            my_df = df_show[df_show['is_inv'] == True]
            if not my_df.empty:
                for row in my_df.to_dict('records'):
                    color = "#FF4444" if row['漲幅'] > 0 else "#00FF00"
                    # 籌碼標籤顏色
                    chip_class = "chip-buy" if "買" in row['籌碼'] else ("chip-sell" if "賣" in row['籌碼'] else "")
                    chip_html = f"<span class='{chip_class}'>{row['籌碼']}</span>"
                    
                    st.markdown(f"**{row['名稱']} ({row['代號']})**: {row['訊號']} <span style='color:#ccc'>({row['理由']})</span> {chip_html}<br>${row['現價']} (<span style='color:{color}'>{row['漲幅']}%</span>) | MA20:{row['MA20']}", unsafe_allow_html=True)
            else: st.info("庫存無資料")

    st.divider()
    
    t1, t2, t3 = st.tabs(["📈 推薦買進", "📉 推薦賣出", "全部清單"])
    cols = ['代號', '名稱', '現價', '漲幅', '訊號', '籌碼', '理由']
    
    with t1:
        d1 = df_show[df_show['code'] > 0].sort_values('漲幅', ascending=False)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
    with t2:
        d2 = df_show[df_show['code'] < 0].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(df_show.sort_values('漲幅', ascending=False), column_order=cols, use_container_width=True, hide_index=True)
else:
    st.info("🐕 總柴熱身中，準備全市場掃描 (約 60-90 秒)...")

if auto_refresh and status_code == "open":
    time.sleep(300)
    st.rerun()

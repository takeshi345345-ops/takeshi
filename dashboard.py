import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
import json

# --- 1. SSL 修正 (維持連線) ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
old_merge_environment_settings = requests.Session.merge_environment_settings

def merge_environment_settings(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url:
        verify = False
    return old_merge_environment_settings(self, url, proxies, stream, verify, cert)

requests.Session.merge_environment_settings = merge_environment_settings

# --- 2. 頁面設定 ---
st.set_page_config(
    page_title="總柴快報 (極速版)",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #FFFFFF; }
    h1, h2, h3 { color: #00E5FF !important; }
    .stock-card { padding: 12px; margin-bottom: 8px; border-radius: 6px; border-left: 6px solid #555; background: #1a1a1a; }
    .status-bar { background: #222; padding: 8px; border-radius: 5px; text-align: center; color: #aaa; font-size: 0.8rem; margin-bottom: 15px;}
    thead tr th:first-child {display:none}
    tbody th {display:none}
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴台股快報：極速監控版")

# --- 3. 設定 ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

def get_taiwan_time():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)

# --- 4. 狀態 ---
if 'last_scan_data' not in st.session_state:
    st.session_state.last_scan_data = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = "尚未更新"

current_date = get_taiwan_time().date()
if 'run_date' not in st.session_state or st.session_state.run_date != current_date:
    st.session_state.run_date = current_date
    st.session_state.done_830 = False
    st.session_state.done_915 = False
    st.session_state.done_1230 = False

# --- 5. 精選資料庫 (只留龍頭股以加快速度) ---
SECTOR_DB = {
    "🔥 半導體": {'2330':'台積電','2454':'聯發科','2303':'聯電','3711':'日月光','3443':'創意','3661':'世芯','3035':'智原','8131':'福懋科'}, # 包含你的庫存
    "🤖 AI與電腦": {'2382':'廣達','3231':'緯創','2356':'英業達','6669':'緯穎','2376':'技嘉','2357':'華碩','3017':'奇鋐','3324':'雙鴻'},
    "⚡ 重電綠能": {'1513':'中興電','1519':'華城','1503':'士電','1605':'華新','1504':'東元'},
    "🚢 航運": {'2603':'長榮','2609':'陽明','2615':'萬海','2618':'長榮航','2610':'華航'},
    "🚗 汽車": {'2201':'裕隆','2207':'和泰車','1319':'東陽'},
    "💰 金融": {'2881':'富邦金','2882':'國泰金','2891':'中信金','2886':'兆豐金'},
    "🥤 傳產": {'1605':'華新', '1476':'儒鴻', '9910':'豐泰', '2002':'中鋼', '1101':'台泥'}
}

with st.sidebar:
    st.header("⚙️ 設定")
    auto_refresh = st.toggle("啟動自動監控 (每5分)", value=True)
    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號", "8131")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    
    st.divider()
    all_sectors = list(SECTOR_DB.keys())
    selected_sectors = st.multiselect("掃描族群", all_sectors, default=all_sectors)

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

# --- 6. 核心掃描 (批次極速版) ---
def calculate_ma20(sid):
    # 只給庫存用
    try:
        stock = twstock.Stock(sid)
        stock.fetch_from(2024, 1)
        if len(stock.price) < 20: return None
        return sum(stock.price[-20:]) / 20
    except: return None

def get_targets(user_port, sectors):
    target_codes = set(user_port)
    code_info = {p: {'name': f"庫存({p})", 'sector': '💼 我的庫存', 'is_inv': True} for p in user_port}
    for sec in sectors:
        for code, name in SECTOR_DB[sec].items():
            target_codes.add(code)
            if code not in code_info:
                code_info[code] = {'name': name, 'sector': sec, 'is_inv': False}
    return list(target_codes), code_info

def scan_stocks(target_codes, code_info):
    results, buy_sigs, sell_sigs = [], [], []
    
    # 這裡不做進度條，直接用 toast，避免畫面跳動
    st.toast(f"🐕 正在掃描 {len(target_codes)} 檔股票...")
    
    # 加大批次量，一次抓 20 檔
    BATCH = 20
    
    for i in range(0, len(target_codes), BATCH):
        batch = target_codes[i:i+BATCH]
        try:
            stocks = twstock.realtime.get(batch)
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        rt = data['realtime']
                        
                        # 價格容錯處理
                        try: price = float(rt['latest_trade_price'])
                        except: 
                            try: price = float(rt['best_bid_price'][0])
                            except: continue # 真的沒價錢就跳過
                        
                        if price == 0: continue
                        
                        try: prev = float(rt['previous_close'])
                        except: prev = price
                        
                        pct = round(((price-prev)/prev)*100, 2)
                        
                        name = code_info[sid]['name']
                        is_inv = code_info[sid]['is_inv']
                        sec = code_info[sid]['sector']
                        
                        # --- 策略核心 ---
                        ma20 = prev 
                        ma_source = "昨收" # 預設用昨收當支撐
                        
                        # ★ 只對「庫存」算 MA20，其他人只看漲跌幅 (速度優化關鍵) ★
                        if is_inv:
                            real_ma20 = calculate_ma20(sid)
                            if real_ma20:
                                ma20 = real_ma20
                                ma_source = "MA20"
                        
                        signal = "➖ 盤整"
                        reason = "波動小"
                        code_val = 0 
                        
                        # 1. 買進訊號 (漲 > 2% 或 庫存站上月線)
                        if pct > 2.0:
                            signal = "🔥 飆股噴出"
                            reason = f"🚀 強勢上漲 ({ma_source}之上)"
                            code_val = 10
                            # 漲超過 3.5% 才發 LINE
                            if pct > 3.5:
                                buy_sigs.append({'msg': f"🔥 {name} ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                        elif is_inv and price >= ma20:
                            signal = "🔴 續抱"
                            reason = f"🛡️ 守穩{ma_source}"
                            code_val = 5
                            
                        # 2. 賣出訊號 (跌 < -2% 或 庫存跌破月線)
                        elif pct < -2.0:
                            signal = "❄️ 重挫殺盤"
                            reason = f"📉 弱勢下跌"
                            code_val = -10
                            # 跌超過 3.5% 才發 LINE
                            if pct < -3.5:
                                sell_sigs.append({'msg': f"❄️ {name} ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                        elif is_inv and price < ma20:
                            signal = "🟢 轉弱"
                            reason = f"❌ 跌破{ma_source}"
                            code_val = -5
                            sell_sigs.append({'msg': f"📉 {name} ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                        
                        # 3. 其他 (單純顯示漲跌)
                        else:
                            if pct > 0: 
                                signal = "📈 上漲"
                                code_val = 1
                            elif pct < 0:
                                signal = "📉 下跌"
                                code_val = -1

                        results.append({
                            '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                            '訊號': signal, '理由': reason, 'code': code_val, 
                            '族群': sec, 'is_inv': is_inv
                        })
            # 休息一下避免被鎖，但縮短時間
            time.sleep(0.2)
        except: pass
    
    if not results: return pd.DataFrame(), [], []
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 7. 主流程 ---
targets, info = get_targets(portfolio, selected_sectors)
run_now = False
trigger_source = "auto"

if st.session_state.last_scan_data.empty:
    run_now = True; trigger_source = "init"

if st.button("🔄 立即刷新", type="primary"):
    run_now = True; trigger_source = "manual"

now_tw = get_taiwan_time()
current_time_str = now_tw.strftime("%H:%M")
curr_h = now_tw.hour
curr_m = now_tw.minute

if not run_now:
    if curr_h == 8 and 30 <= curr_m <= 45 and not st.session_state.done_830:
        run_now = True; trigger_source = "830"
    elif curr_h == 9 and 15 <= curr_m <= 30 and not st.session_state.done_915:
        run_now = True; trigger_source = "915"
    elif curr_h == 12 and 30 <= curr_m <= 45 and not st.session_state.done_1230:
        run_now = True; trigger_source = "1230"

if run_now:
    df, buys, sells = scan_stocks(targets, info)
    
    st.session_state.last_scan_data = df
    st.session_state.last_update_time = current_time_str
    
    if trigger_source == "830": st.session_state.done_830 = True
    elif trigger_source == "915": st.session_state.done_915 = True
    elif trigger_source == "1230": st.session_state.done_1230 = True

    if LINE_TOKEN and trigger_source != "init":
        msg_body = ""
        should_send = False
        
        my_msgs = [x['msg'] for x in buys if x['is_inv']] + [x['msg'] for x in sells if x['is_inv']]
        if my_msgs: 
            msg_body += "\n【💼 庫存警示】\n" + "\n".join(my_msgs) + "\n"
            should_send = True

        # 嚴格篩選：只有大漲大跌才發通知
        hot_buys = [x['msg'] for x in buys if not x['is_inv']]
        if hot_buys: 
            msg_body += "\n【🔥 飆股噴出】\n" + "\n".join(hot_buys[:5]) + "\n"
            should_send = True
            
        hot_sells = [x['msg'] for x in sells if not x['is_inv']]
        if hot_sells: 
            msg_body += "\n【❄️ 重挫殺盤】\n" + "\n".join(hot_sells[:5]) + "\n"
            should_send = True

        if should_send or trigger_source == "manual":
            title = f"🐕 總柴快報 ({trigger_source})"
            if not should_send: msg_body = "\n(市場平靜，無特殊訊號)"
            send_line(title + "\n" + msg_body)
            st.toast("✅ LINE 通知已發送")

# --- 8. 顯示 ---
st.markdown(f"<div class='status-bar'>🕒 更新時間: {st.session_state.last_update_time}</div>", unsafe_allow_html=True)

df_show = st.session_state.last_scan_data
if not df_show.empty:
    if portfolio:
        st.markdown("### 💼 我的庫存")
        my_df = df_show[df_show['is_inv'] == True]
        if not my_df.empty:
            for row in my_df.itertuples():
                color = "#FF4444" if row.漲幅 > 0 else "#00FF00"
                st.markdown(f"**{row.名稱} ({row.代號})**: {row.訊號} <span style='color:#888'>({row.理由})</span><br>${row.現價} (<span style='color:{color}'>{row.漲幅}%</span>)", unsafe_allow_html=True)
        else: st.info("庫存無資料")

    st.divider()
    
    t1, t2, t3 = st.tabs(["📈 多方排行", "📉 空方排行", "全部列表"])
    cols = ['名稱', '現價', '漲幅', '訊號', '理由']
    
    with t1:
        # 只要 >= 0 就列出來
        d1 = df_show[df_show['漲幅'] >= 0].sort_values('漲幅', ascending=False)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
    with t2:
        # 只要 < 0 就列出來
        d2 = df_show[df_show['漲幅'] < 0].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(df_show.sort_values('漲幅', ascending=False), column_order=cols, use_container_width=True, hide_index=True)
else:
    st.info("🐕 總柴極速連線中...")

if auto_refresh:
    time.sleep(300)
    st.rerun()

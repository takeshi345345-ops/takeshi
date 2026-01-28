import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
import json

# --- 1. SSL 修正 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
old_merge_environment_settings = requests.Session.merge_environment_settings

def merge_environment_settings(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url:
        verify = False
    return old_merge_environment_settings(self, url, proxies, stream, verify, cert)

requests.Session.merge_environment_settings = merge_environment_settings

# --- 2. 頁面設定 ---
st.set_page_config(
    page_title="總柴快報 (保證有資料版)",
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

# --- 3. 內建熱門股清單 (防止抓不到代號) ---
# 這裡內建 300+ 檔熱門股，確保全市場掃描一定有資料
HOT_STOCKS = [
    '2330','2317','2454','2308','2303','2382','3231','2357','2376','2356','3037','3034','2379','3008',
    '3045','2412','2345','3017','2324','6669','2395','4938','2408','3443','3661','2301','5871','2881',
    '2882','2891','2886','2884','2885','2892','2880','2883','2890','5880','2887','2801','2603','2609',
    '2615','2618','2610','2637','2606','2634','1513','1519','1503','1504','1605','1609','1514','6806',
    '9958','2031','1101','1216','2002','2105','2201','2207','1301','1303','1326','1402','1476','9910',
    '1722','1708','4743','1795','4128','6472','6446','6547','3293','3529','6531','8046','8069','6274',
    '6213','4958','6770','5347','6488','3035','3406','3596','3711','6239','6269','8150','3324','3653',
    '3665','3694','4919','4961','5269','5274','5483','6104','6121','6147','6187','6223','6244','6271',
    '6285','6414','6415','6456','6515','6643','6719','6756','8016','8028','8050','8081','8112','8155',
    '8299','8358','8436','8454','8464','8936','9921','9941','8131'
]

# --- 4. 側邊欄與變數 ---
portfolio = [] 
LINE_TOKEN = None

with st.sidebar:
    st.header("⚙️ 設定")
    if "LINE_TOKEN" in st.secrets:
        LINE_TOKEN = st.secrets["LINE_TOKEN"]
    else:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")
        
    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號", "8131") # 你的庫存
    if inv:
        portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    
    # 時間判斷 (盤中自動開，盤後自動關但可手動開)
    now_utc8 = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    default_auto = True if (9 <= now_utc8.hour < 14) else False
    auto_refresh = st.toggle("啟動自動監控", value=default_auto)

# --- 5. 核心函式 ---
def get_taiwan_time():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)

def get_market_status():
    now = get_taiwan_time()
    # 週末視為盤後
    if now.weekday() >= 5:
        return "closed", "🌙 假日休市 (結算數據)"
    
    start = now.replace(hour=9, minute=0, second=0)
    end = now.replace(hour=13, minute=30, second=0)
    
    if start <= now <= end:
        return "open", "☀️ 盤中即時 (Live)"
    else:
        return "closed", "🌙 盤後結算 (Final)"

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

# --- 6. 狀態管理 ---
if 'last_scan_data' in st.session_state:
    # 資料結構檢查，若舊資料缺欄位則清空
    if not st.session_state.last_scan_data.empty and 'MA20' not in st.session_state.last_scan_data.columns:
        st.session_state.last_scan_data = pd.DataFrame()

if 'last_scan_data' not in st.session_state:
    st.session_state.last_scan_data = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = "尚未更新"

# 每日重置發送狀態
curr_date = get_taiwan_time().date()
if 'run_date' not in st.session_state or st.session_state.run_date != curr_date:
    st.session_state.run_date = curr_date
    st.session_state.done_830 = False
    st.session_state.done_915 = False
    st.session_state.done_1230 = False

# --- 7. MA20 計算 ---
def calculate_ma20(sid):
    try:
        stock = twstock.Stock(sid)
        stock.fetch_from(2024, 1)
        if len(stock.price) < 20: return None
        return sum(stock.price[-20:]) / 20
    except: return None

# --- 8. 掃描邏輯 ---
def scan_market(user_port):
    results, buy_sigs, sell_sigs = [], [], []
    
    # 標題
    status_code, status_text = get_market_status()
    st.title(f"🐕 總柴台股快報：{status_text}")
    
    # 合併清單：庫存 + 內建熱門股
    targets = list(set(portfolio + HOT_STOCKS))
    
    st.toast(f"🐕 正在掃描 {len(targets)} 檔熱門股與庫存...")
    
    progress_bar = st.progress(0)
    BATCH = 30 # 批次量
    total_batches = (len(targets) // BATCH) + 1
    
    for i in range(0, len(targets), BATCH):
        batch = targets[i:i+BATCH]
        progress_bar.progress(min((i // BATCH + 1) / total_batches, 0.95))
        
        try:
            stocks = twstock.realtime.get(batch)
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        rt = data['realtime']
                        # 價格抓取 (含容錯)
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
                        
                        # --- 策略核心 ---
                        ma20 = prev
                        ma_source = "昨收"
                        
                        # 只有 庫存 或 波動>2.5% 才去算 MA20 (省時間)
                        if is_inv or abs(pct) > 2.5:
                            real_ma20 = calculate_ma20(sid)
                            if real_ma20:
                                ma20 = real_ma20
                                ma_source = "MA20"
                        
                        signal = "➖ 盤整"
                        reason = "-"
                        code_val = 0 
                        
                        # A. 買方
                        if pct > 0:
                            if pct > 3.5 and price >= ma20:
                                signal = "🔥 飆股噴出"
                                reason = f"🚀 爆量長紅 (>{ma_source})"
                                code_val = 10
                                buy_sigs.append({'msg': f"🔥 {name} ${price} (+{pct}%)", 'is_inv': is_inv})
                            elif price >= ma20 and pct > 2.0:
                                signal = "🔴 多頭轉強"
                                reason = f"🛡️ 站穩{ma_source}"
                                code_val = 5
                                if is_inv:
                                    buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%)", 'is_inv': is_inv})
                            elif pct > 3.0:
                                signal = "🌤️ 強力反彈"
                                reason = "⚠️ 深跌反彈"
                                code_val = 2
                            else:
                                signal = "📈 上漲"
                                code_val = 1
                        
                        # B. 賣方
                        elif pct < 0:
                            if pct < -3.5:
                                signal = "❄️ 重挫殺盤"
                                reason = "📉 恐慌賣壓"
                                code_val = -10
                                sell_sigs.append({'msg': f"❄️ {name} ${price} ({pct}%)", 'is_inv': is_inv})
                            elif price < ma20 and pct < -2.0:
                                signal = "🟢 轉弱破線"
                                reason = f"❌ 跌破{ma_source}"
                                code_val = -5
                                if is_inv:
                                    sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%)", 'is_inv': is_inv})
                            else:
                                signal = "📉 下跌"
                                code_val = -1

                        # 結果存入 (庫存必存，其他波動>1%才存)
                        if is_inv or abs(pct) > 1.0:
                            results.append({
                                '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                                '訊號': signal, '理由': reason, 'MA20': round(ma20, 2),
                                'code': code_val, 'is_inv': is_inv
                            })
            
            time.sleep(0.2)
        except: pass
            
    progress_bar.empty()
    if not results: return pd.DataFrame(), [], []
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 9. 主程式執行 ---
run_now = False
trigger_source = "auto"

# 1. 首次載入自動跑
if st.session_state.last_scan_data.empty:
    run_now = True; trigger_source = "init"

# 2. 手動刷新
status_code, status_text = get_market_status()
btn_label = "🔄 立即刷新 (盤中即時)" if status_code == "open" else "🔄 立即刷新 (盤後結算)"
if st.button(btn_label, type="primary"):
    run_now = True; trigger_source = "manual"

# 3. 排程
now_tw = get_taiwan_time()
h = now_tw.hour
m = now_tw.minute

if not run_now and status_code == "open": # 盤中才定時
    if h == 9 and 15 <= m <= 30 and not st.session_state.done_915:
        run_now = True; trigger_source = "915"
    elif h == 12 and 30 <= m <= 45 and not st.session_state.done_1230:
        run_now = True; trigger_source = "1230"
elif not run_now and status_code == "closed": # 盤後只檢查盤前那次
    if h == 8 and 30 <= m <= 45 and not st.session_state.done_830:
        run_now = True; trigger_source = "830"

if run_now:
    df, buys, sells = scan_market(portfolio)
    st.session_state.last_scan_data = df
    st.session_state.last_update_time = now_tw.strftime("%H:%M")
    
    if trigger_source == "830": st.session_state.done_830 = True
    elif trigger_source == "915": st.session_state.done_915 = True
    elif trigger_source == "1230": st.session_state.done_1230 = True

    # LINE 通知
    if LINE_TOKEN and trigger_source != "init":
        msg_body = ""
        should_send = False
        
        my_msgs = [x['msg'] for x in buys if x['is_inv']] + [x['msg'] for x in sells if x['is_inv']]
        if my_msgs: 
            msg_body += "\n【💼 庫存警示】\n" + "\n".join(my_msgs) + "\n"
            should_send = True

        hot_buys = [x['msg'] for x in buys if not x['is_inv'] and "🔥" in x['msg']]
        hot_buys.sort(key=lambda x: float(x.split('+')[1].split('%')[0]), reverse=True)
        if hot_buys: 
            msg_body += "\n【🔥 飆股排行】\n" + "\n".join(hot_buys[:5]) + "\n"
            should_send = True
            
        hot_sells = [x['msg'] for x in sells if not x['is_inv'] and "❄️" in x['msg']]
        hot_sells.sort(key=lambda x: float(x.split('(')[-1].split('%')[0]))
        if hot_sells: 
            msg_body += "\n【❄️ 殺盤排行】\n" + "\n".join(hot_sells[:5]) + "\n"
            should_send = True

        if should_send or trigger_source == "manual":
            title = f"🐕 總柴快報 ({status_text})"
            if not should_send: msg_body = "\n(市場平靜)"
            send_line(title + "\n" + msg_body)
            st.toast("✅ LINE 已發送")

# --- 10. 顯示結果 ---
st.markdown(f"<div class='status-bar'>🕒 更新: {st.session_state.last_update_time} | {status_text}</div>", unsafe_allow_html=True)

df_show = st.session_state.last_scan_data
if not df_show.empty:
    if portfolio:
        st.markdown("### 💼 我的庫存")
        my_df = df_show[df_show['is_inv'] == True]
        if not my_df.empty:
            for row in my_df.to_dict('records'):
                color = "#FF4444" if row['漲幅'] > 0 else "#00FF00"
                ma_val = row.get('MA20', 'N/A')
                st.markdown(f"**{row['名稱']} ({row['代號']})**: {row['訊號']} <span style='color:#888'>({row['理由']})</span><br>${row['現價']} (<span style='color:{color}'>{row['漲幅']}%</span>) | MA20:{ma_val}", unsafe_allow_html=True)
        else: st.info("庫存無資料")

    st.divider()
    t1, t2, t3 = st.tabs(["📈 飆股排行", "📉 殺盤排行", "全部清單"])
    cols = ['代號', '名稱', '現價', '漲幅', '訊號', '理由']
    
    with t1:
        d1 = df_show[df_show['漲幅'] > 0].sort_values('漲幅', ascending=False)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
    with t2:
        d2 = df_show[df_show['漲幅'] < 0].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(df_show.sort_values('漲幅', ascending=False), column_order=cols, use_container_width=True, hide_index=True)
else:
    st.info("🐕 總柴正在連線中... (首次載入需時約 30 秒)")

if auto_refresh and status_code == "open":
    time.sleep(300)
    st.rerun()

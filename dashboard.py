import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
import json

# --- 1. SSL 憑證修正 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
old_merge_environment_settings = requests.Session.merge_environment_settings

def merge_environment_settings(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url:
        verify = False
    return old_merge_environment_settings(self, url, proxies, stream, verify, cert)

requests.Session.merge_environment_settings = merge_environment_settings

# --- 2. 頁面設定 ---
st.set_page_config(
    page_title="總柴快報 (穩定修復版)",
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
    /* 強調飆股 */
    .highlight { color: #FF00FF; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴台股快報：全市場狙擊模式")

# --- 3. 設定 ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

def get_taiwan_time():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)

# --- 4. 狀態管理 (修復 Bug 關鍵) ---
# 強制清除舊格式資料，避免 AttributeError
if 'last_scan_data' in st.session_state:
    # 檢查是否包含新欄位 'MA20'，沒有就清空
    if not st.session_state.last_scan_data.empty and 'MA20' not in st.session_state.last_scan_data.columns:
        st.session_state.last_scan_data = pd.DataFrame()

if 'last_scan_data' not in st.session_state:
    st.session_state.last_scan_data = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = "尚未更新"

# 狀態標記
current_date = get_taiwan_time().date()
if 'run_date' not in st.session_state or st.session_state.run_date != current_date:
    st.session_state.run_date = current_date
    st.session_state.done_830 = False
    st.session_state.done_915 = False
    st.session_state.done_1230 = False

with st.sidebar:
    st.header("⚙️ 設定")
    auto_refresh = st.toggle("啟動自動監控 (每5分)", value=True)
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

# --- 5. 獲取全市場清單 ---
@st.cache_data(ttl=3600*12)
def get_all_stock_codes():
    codes = []
    for code, info in twstock.codes.items():
        if info.market == '上市' and info.type == '股票' and len(code) == 4:
            codes.append(code)
    return sorted(codes)

# --- 6. 核心掃描 ---
def calculate_ma20(sid):
    try:
        stock = twstock.Stock(sid)
        stock.fetch_from(2024, 1)
        if len(stock.price) < 20: return None
        return sum(stock.price[-20:]) / 20
    except: return None

def scan_market(user_port):
    results, buy_sigs, sell_sigs = [], [], []
    
    all_targets = get_all_stock_codes()
    targets = list(set(all_targets + user_port))
    
    st.toast(f"🐕 全市場掃描啟動！目標: {len(targets)} 檔 (請稍候約 1-2 分鐘)...")
    
    progress_bar = st.progress(0)
    BATCH = 50 
    total_batches = (len(targets) // BATCH) + 1
    
    for i in range(0, len(targets), BATCH):
        batch_codes = targets[i:i+BATCH]
        current_batch_idx = i // BATCH
        progress_bar.progress(min((current_batch_idx + 1) / total_batches, 0.95))
        
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
                        
                        # 篩選條件：庫存 或 波動 > 3%
                        need_deep_scan = is_inv or pct > 3.0 or pct < -3.0
                        
                        ma20 = prev 
                        ma_source = "昨收"
                        
                        if need_deep_scan:
                            real_ma20 = calculate_ma20(sid)
                            if real_ma20:
                                ma20 = real_ma20
                                ma_source = "MA20"
                        
                        signal = "➖ 盤整"
                        reason = "-"
                        code_val = 0 
                        
                        # A. 買進訊號
                        if pct > 0:
                            if pct > 3.5 and price >= ma20:
                                signal = "🔥 飆股噴出"
                                reason = f"🚀 爆量長紅 (>{ma_source})"
                                code_val = 10
                                buy_sigs.append({'msg': f"🔥 {name}({sid}) ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                            elif price >= ma20 and pct > 2.0:
                                signal = "🔴 多頭轉強"
                                reason = f"🛡️ 站穩{ma_source}"
                                code_val = 5
                                if is_inv:
                                    buy_sigs.append({'msg': f"🔴 {name}({sid}) ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                            elif pct > 3.0 and price < ma20:
                                signal = "🌤️ 強力反彈"
                                reason = "⚠️ 月線下急拉"
                                code_val = 2
                            else:
                                signal = "📈 上漲"
                                code_val = 1

                        # B. 賣出訊號
                        elif pct < 0:
                            if pct < -3.5:
                                signal = "❄️ 重挫殺盤"
                                reason = "📉 恐慌賣壓"
                                code_val = -10
                                sell_sigs.append({'msg': f"❄️ {name}({sid}) ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                            elif price < ma20 and pct < -2.0:
                                signal = "🟢 轉弱破線"
                                reason = f"❌ 跌破{ma_source}"
                                code_val = -5
                                if is_inv:
                                    sell_sigs.append({'msg': f"🟢 {name}({sid}) ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                            else:
                                signal = "📉 下跌"
                                code_val = -1

                        if is_inv or abs(pct) > 1.5:
                            results.append({
                                '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                                '訊號': signal, '理由': reason, 'MA20': round(ma20, 2),
                                'code': code_val, 'is_inv': is_inv
                            })
            
            time.sleep(0.3)
            
        except Exception as e:
            pass
            
    progress_bar.empty()
    if not results: return pd.DataFrame(), [], []
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 7. 主流程 ---
run_now = False
trigger_source = "auto"

# 檢查是否為空
if st.session_state.last_scan_data.empty:
    run_now = True; trigger_source = "init"

if st.button("🔄 立即刷新全市場", type="primary"):
    run_now = True; trigger_source = "manual"

now_tw = get_taiwan_time()
current_time_str = now_tw.strftime("%H:%M")
curr_h = now_tw.hour
curr_m = now_tw.minute

# 排程
if not run_now:
    if curr_h == 8 and 30 <= curr_m <= 45 and not st.session_state.done_830:
        run_now = True; trigger_source = "830"
    elif curr_h == 9 and 15 <= curr_m <= 30 and not st.session_state.done_915:
        run_now = True; trigger_source = "915"
    elif curr_h == 12 and 30 <= curr_m <= 45 and not st.session_state.done_1230:
        run_now = True; trigger_source = "1230"

if run_now:
    df, buys, sells = scan_market(portfolio)
    
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

        hot_buys = [x['msg'] for x in buys if not x['is_inv'] and "🔥" in x['msg']]
        hot_buys.sort(key=lambda x: float(x.split('+')[1].split('%')[0]), reverse=True)
        if hot_buys: 
            msg_body += "\n【🔥 全市場飆股 TOP 5】\n" + "\n".join(hot_buys[:5]) + "\n"
            should_send = True
            
        hot_sells = [x['msg'] for x in sells if not x['is_inv'] and "❄️" in x['msg']]
        hot_sells.sort(key=lambda x: float(x.split('(')[-1].split('%')[0]))
        if hot_sells: 
            msg_body += "\n【❄️ 全市場重挫 TOP 5】\n" + "\n".join(hot_sells[:5]) + "\n"
            should_send = True

        if should_send or trigger_source == "manual":
            title = f"🐕 總柴快報 ({trigger_source})"
            if not should_send: msg_body = "\n(全市場平靜，無大波動)"
            send_line(title + "\n" + msg_body)
            st.toast("✅ LINE 通知已發送")

# --- 8. 顯示 (修復錯誤點) ---
st.markdown(f"<div class='status-bar'>🕒 更新時間: {st.session_state.last_update_time} | 自動監控中</div>", unsafe_allow_html=True)

df_show = st.session_state.last_scan_data
if not df_show.empty:
    if portfolio:
        st.markdown("### 💼 我的庫存")
        my_df = df_show[df_show['is_inv'] == True]
        if not my_df.empty:
            # 這裡改用 to_dict 避免 itertuples 屬性錯誤
            for row in my_df.to_dict('records'):
                color = "#FF4444" if row['漲幅'] > 0 else "#00FF00"
                # 安全地讀取 MA20
                ma20_val = row.get('MA20', 'N/A')
                st.markdown(f"**{row['名稱']} ({row['代號']})**: {row['訊號']} <span style='color:#888'>({row['理由']})</span><br>${row['現價']} (<span style='color:{color}'>{row['漲幅']}%</span>) | MA20:{ma20_val}", unsafe_allow_html=True)
        else: st.info("庫存無資料 (可能今日無交易或代號錯誤)")

    st.divider()
    
    t1, t2, t3 = st.tabs(["📈 全市場飆股", "📉 全市場重挫", "波動列表"])
    cols = ['代號', '名稱', '現價', '漲幅', '訊號', '理由']
    
    with t1:
        d1 = df_show[df_show['漲幅'] > 3].sort_values('漲幅', ascending=False)
        if d1.empty: st.info("無漲幅 > 3% 之股票")
        else: st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
    with t2:
        d2 = df_show[df_show['漲幅'] < -3].sort_values('漲幅', ascending=True)
        if d2.empty: st.info("無跌幅 > 3% 之股票")
        else: st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(df_show.sort_values('漲幅', ascending=False), column_order=cols, use_container_width=True, hide_index=True)
else:
    st.info("🐕 正在進行全市場掃描 (約需 1-2 分鐘)...")

if auto_refresh:
    time.sleep(300)
    st.rerun()

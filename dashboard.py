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
    page_title="總柴快報 (日夜雙模版)",
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
    /* 模式標籤 */
    .mode-tag { background: #333; color: #FFD700; padding: 4px 10px; border-radius: 15px; font-weight: bold; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# --- 3. 設定 ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

def get_taiwan_time():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)

# 判斷是盤中還是收盤
def get_market_status():
    now = get_taiwan_time()
    # 簡單判斷：09:00 ~ 13:30 為盤中，其餘為收盤
    # (週六日算收盤)
    if now.weekday() >= 5:
        return "closed", "🌙 假日休市 (查看上週五收盤)"
    
    start_time = now.replace(hour=9, minute=0, second=0)
    end_time = now.replace(hour=13, minute=30, second=0)
    
    if start_time <= now <= end_time:
        return "open", "☀️ 盤中即時 (Live)"
    else:
        return "closed", "🌙 盤後結算 (Final)"

# --- 4. 狀態管理 ---
if 'last_scan_data' not in st.session_state:
    st.session_state.last_scan_data = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = "尚未更新"

# --- 5. 獲取全市場清單 ---
@st.cache_data(ttl=3600*12)
def get_all_stock_codes():
    codes = []
    for code, info in twstock.codes.items():
        if info.market == '上市' and info.type == '股票' and len(code) == 4:
            codes.append(code)
    return sorted(codes)

# --- 6. 核心掃描 (日夜雙邏輯) ---
def calculate_ma20(sid):
    try:
        stock = twstock.Stock(sid)
        # 盤後模式：抓最近資料即可
        stock.fetch_from(2024, 1)
        if len(stock.price) < 20: return None
        return sum(stock.price[-20:]) / 20
    except: return None

def scan_market(user_port):
    results, buy_sigs, sell_sigs = [], [], []
    
    status_code, status_text = get_market_status()
    st.title(f"🐕 總柴台股快報：{status_text}")
    
    all_targets = get_all_stock_codes()
    targets = list(set(all_targets + user_port))
    
    st.toast(f"🐕 啟動全市場掃描 ({len(targets)} 檔)...")
    
    progress_bar = st.progress(0)
    BATCH = 50 
    total_batches = (len(targets) // BATCH) + 1
    
    for i in range(0, len(targets), BATCH):
        batch_codes = targets[i:i+BATCH]
        current_batch_idx = i // BATCH
        progress_bar.progress(min((current_batch_idx + 1) / total_batches, 0.95))
        
        try:
            # 即時API在盤後會顯示「當日收盤資訊」，所以還是可以用
            stocks = twstock.realtime.get(batch_codes)
            
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        rt = data['realtime']
                        try: price = float(rt['latest_trade_price'])
                        except: 
                            try: price = float(rt['best_bid_price'][0])
                            except: continue # 真的沒價錢就跳過
                        
                        if price == 0: continue
                        
                        try: prev = float(rt['previous_close'])
                        except: prev = price
                        
                        pct = round(((price-prev)/prev)*100, 2)
                        name = data['info']['name']
                        is_inv = sid in user_port
                        
                        # === 篩選邏輯 (日夜通用) ===
                        # 盤後我們看的是「今天的結果論」
                        
                        # 1. 初步篩選：只有漲跌幅顯著 or 庫存 才算 MA20
                        # 盤後標準：漲跌超過 2.5% 就值得看
                        need_deep_scan = is_inv or abs(pct) > 2.5
                        
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
                        
                        # --- 策略 A: 買進 (紅) ---
                        if pct > 0:
                            # 飆股：漲 > 3.5% + 站上月線
                            if pct > 3.5 and price >= ma20:
                                signal = "🔥 飆股噴出"
                                reason = f"🚀 爆量長紅 (>{ma_source})"
                                code_val = 10
                                buy_sigs.append({'msg': f"🔥 {name}({sid}) ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                            
                            # 多頭：漲 > 2% + 站上月線
                            elif price >= ma20 and pct > 2.0:
                                signal = "🔴 多頭轉強"
                                reason = f"🛡️ 站穩{ma_source}"
                                code_val = 5
                                if is_inv:
                                    buy_sigs.append({'msg': f"🔴 {name}({sid}) ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                            
                            # 反彈
                            elif pct > 3.0 and price < ma20:
                                signal = "🌤️ 強力反彈"
                                reason = "⚠️ 月線下急拉"
                                code_val = 2
                            else:
                                signal = "📈 上漲"
                                code_val = 1

                        # --- 策略 B: 賣出 (綠) ---
                        elif pct < 0:
                            # 殺盤
                            if pct < -3.5:
                                signal = "❄️ 重挫殺盤"
                                reason = "📉 恐慌賣壓"
                                code_val = -10
                                sell_sigs.append({'msg': f"❄️ {name}({sid}) ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                            
                            # 轉弱
                            elif price < ma20 and pct < -2.0:
                                signal = "🟢 轉弱破線"
                                reason = f"❌ 跌破{ma_source}"
                                code_val = -5
                                if is_inv:
                                    sell_sigs.append({'msg': f"🟢 {name}({sid}) ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                            else:
                                signal = "📉 下跌"
                                code_val = -1

                        # 結果存入 (只存波動夠大或是庫存)
                        if is_inv or abs(pct) > 1.0:
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
status_code, status_text = get_market_status()

# 狀態初始化：清除舊格式
if 'last_scan_data' in st.session_state and not st.session_state.last_scan_data.empty:
    if 'MA20' not in st.session_state.last_scan_data.columns:
        st.session_state.last_scan_data = pd.DataFrame()

# 開機自動跑 (如果是盤中每5分跑，盤後只跑一次)
if st.session_state.last_scan_data.empty:
    run_now = True; trigger_source = "init"

if st.button(f"🔄 立即刷新 ({'盤後' if status_code=='closed' else '盤中'})", type="primary"):
    run_now = True; trigger_source = "manual"

# 排程邏輯
now_tw = get_taiwan_time()
curr_h = now_tw.hour
curr_m = now_tw.minute

# 狀態管理 (防止重複發送)
if 'done_830' not in st.session_state: st.session_state.done_830 = False
if 'done_915' not in st.session_state: st.session_state.done_915 = False
if 'done_1230' not in st.session_state: st.session_state.done_1230 = False

if not run_now and status_code == "open":
    # 盤中才需要定時檢查
    if curr_h == 9 and 15 <= curr_m <= 30 and not st.session_state.done_915:
        run_now = True; trigger_source = "915"
    elif curr_h == 12 and 30 <= curr_m <= 45 and not st.session_state.done_1230:
        run_now = True; trigger_source = "1230"
elif not run_now and status_code == "closed":
    # 盤後 08:30 (盤前) 檢查一次
    if curr_h == 8 and 30 <= curr_m <= 45 and not st.session_state.done_830:
        run_now = True; trigger_source = "830"

if run_now:
    df, buys, sells = scan_market(portfolio)
    
    current_time_str = now_tw.strftime("%H:%M")
    st.session_state.last_scan_data = df
    st.session_state.last_update_time = current_time_str
    
    if trigger_source == "830": st.session_state.done_830 = True
    elif trigger_source == "915": st.session_state.done_915 = True
    elif trigger_source == "1230": st.session_state.done_1230 = True

    # LINE 發送
    if LINE_TOKEN and trigger_source != "init":
        msg_body = ""
        should_send = False
        
        # 1. 庫存
        my_msgs = [x['msg'] for x in buys if x['is_inv']] + [x['msg'] for x in sells if x['is_inv']]
        if my_msgs: 
            msg_body += "\n【💼 庫存警示】\n" + "\n".join(my_msgs) + "\n"
            should_send = True

        # 2. 飆股 (盤後模式下，這些就是今天的勝利組)
        hot_buys = [x['msg'] for x in buys if not x['is_inv'] and "🔥" in x['msg']]
        hot_buys.sort(key=lambda x: float(x.split('+')[1].split('%')[0]), reverse=True)
        
        if hot_buys: 
            msg_body += "\n【🔥 今日飆股 TOP 5】\n" + "\n".join(hot_buys[:5]) + "\n"
            should_send = True
            
        # 3. 殺盤
        hot_sells = [x['msg'] for x in sells if not x['is_inv'] and "❄️" in x['msg']]
        hot_sells.sort(key=lambda x: float(x.split('(')[-1].split('%')[0]))
        
        if hot_sells: 
            msg_body += "\n【❄️ 今日重挫 TOP 5】\n" + "\n".join(hot_sells[:5]) + "\n"
            should_send = True

        if should_send or trigger_source == "manual":
            title = f"🐕 總柴快報 ({status_text})"
            if not should_send: msg_body = "\n(今日市場平靜，無符合條件標的)"
            send_line(title + "\n" + msg_body)
            st.toast("✅ LINE 通知已發送")

# --- 8. 顯示 ---
st.markdown(f"<div class='status-bar'>🕒 更新時間: {st.session_state.last_update_time} | {status_text}</div>", unsafe_allow_html=True)

df_show = st.session_state.last_scan_data
if not df_show.empty:
    # 庫存區
    if portfolio:
        st.markdown("### 💼 我的庫存")
        my_df = df_show[df_show['is_inv'] == True]
        if not my_df.empty:
            for row in my_df.to_dict('records'):
                color = "#FF4444" if row['漲幅'] > 0 else "#00FF00"
                ma20_val = row.get('MA20', 'N/A')
                st.markdown(f"**{row['名稱']} ({row['代號']})**: {row['訊號']} <span style='color:#888'>({row['理由']})</span><br>${row['現價']} (<span style='color:{color}'>{row['漲幅']}%</span>) | MA20:{ma20_val}", unsafe_allow_html=True)
        else: st.info("庫存無資料")

    st.divider()
    
    t1, t2, t3 = st.tabs(["📈 飆股排行", "📉 重挫排行", "全部列表"])
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
    st.info("🐕 全市場掃描中... (首次載入約需 1-2 分鐘)")

# 盤中每5分重整，盤後休息(直到手動按)
if status_code == "open":
    with st.sidebar:
        auto_refresh = st.toggle("自動刷新 (每5分)", value=True)
    if auto_refresh:
        time.sleep(300)
        st.rerun()

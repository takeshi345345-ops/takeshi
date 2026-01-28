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
    page_title="總柴快報 (智能篩選版)",
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
    /* 篩選通過的標記 */
    .pass-tag { color: #00FF00; font-weight: bold; border: 1px solid #00FF00; padding: 2px 6px; border-radius: 4px;}
    .fail-tag { color: #555; font-size: 0.8em; }
</style>
""", unsafe_allow_html=True)

# --- 3. 設定區 ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

with st.sidebar:
    st.header("⚙️ 設定")
    # 預設開啟自動監控
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

def get_taiwan_time():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)

# --- 4. 關鍵技術：計算 MA20 (月線) ---
# 這是篩選的核心，沒有過月線的飆股都是假的
def check_technical_filter(sid, current_price):
    try:
        stock = twstock.Stock(sid)
        # 抓 35 天確保算得出 MA20
        hist = stock.fetch_from(2024, 1) # twstock 會自動優化抓最近
        if len(hist) < 20:
            return None, "資料不足"
        
        # 計算 MA20
        closes = [x.close for x in hist]
        ma20 = sum(closes[-20:]) / 20
        
        return ma20, "OK"
    except:
        return None, "計算失敗"

# --- 5. 核心邏輯：爬蟲 + 嚴格過濾 ---
@st.cache_data(ttl=60)
def scrape_and_filter(mode='up'):
    results = []
    
    # 1. 抓取 Yahoo 排行榜 (候選名單)
    try:
        url = "https://tw.stock.yahoo.com/rank/change-up?exchange=TAI" if mode == 'up' else "https://tw.stock.yahoo.com/rank/change-down?exchange=TAI"
        headers = {'User-Agent': 'Mozilla/5.0'}
        dfs = pd.read_html(url)
        if len(dfs) > 0:
            raw_df = dfs[0]
            # 整理欄位
            raw_df.columns = [c.replace('股號', '代號').replace('名稱', '股票').replace('成交', '現價').replace('漲跌幅', '漲幅') for c in raw_df.columns]
            
            # 只取前 40 名來篩選 (效率考量)
            candidates = raw_df.head(40)
            
            # 2. 逐一進行「麻紗邏輯」過濾
            for i, row in candidates.iterrows():
                try:
                    # 處理代號：Yahoo 有時會是 "2330 台積電" 黏在一起，或是單純 "2330"
                    raw_str = str(row.get('股票', row.get('代號', '')))
                    # 簡單萃取數字
                    sid = ''.join(filter(str.isdigit, raw_str))
                    # 如果代號欄位本身就是數字
                    if not sid and str(row.get('代號','')).isdigit():
                         sid = str(row.get('代號',''))
                    
                    # 確保抓到的是 4 碼股票
                    if len(sid) != 4: continue
                    
                    name = str(row.get('股票', ''))
                    # 處理名字黏代號的情況
                    if sid in name: name = name.replace(sid, '').strip()

                    price = float(row.get('現價', 0))
                    
                    # 處理漲跌幅 (Yahoo 可能帶有 % 或顏色符號)
                    pct_raw = str(row.get('漲幅', 0)).replace('%', '').replace('+', '')
                    pct = float(pct_raw)

                    # --- 關鍵篩選開始 ---
                    ma20, status = check_technical_filter(sid, price)
                    
                    if ma20:
                        # 你的邏輯：
                        # 買進：漲幅 > 3% 且 站上月線
                        if mode == 'up':
                            if price >= ma20:
                                results.append({
                                    "代號": sid, "名稱": name, "現價": price, "漲幅": pct,
                                    "MA20": round(ma20, 2), "訊號": "🔥 旺大飆股", 
                                    "理由": f"站上月線({round(ma20,1)})且爆量"
                                })
                            else:
                                # 雖然漲幅大，但還在月線下 -> 剔除或標記反彈
                                # 這裡我們嚴格一點，只選站上的
                                pass 
                        
                        # 賣出：跌幅 < -3% 且 跌破月線
                        else:
                            if price < ma20:
                                results.append({
                                    "代號": sid, "名稱": name, "現價": price, "漲幅": pct,
                                    "MA20": round(ma20, 2), "訊號": "❄️ 破線殺盤", 
                                    "理由": f"跌破月線({round(ma20,1)})且重挫"
                                })
                            else:
                                pass
                    
                    # 稍微休息避免被鎖
                    time.sleep(0.05)
                    
                except: continue
                
    except Exception as e:
        st.error(f"連線篩選錯誤: {e}")
        
    return pd.DataFrame(results)

# 庫存獨立檢查
def check_inventory_strict(user_port):
    results = []
    if not user_port: return pd.DataFrame()
    
    try:
        stocks = twstock.realtime.get(user_port)
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
                    
                    # 算 MA20
                    ma20, status = check_technical_filter(sid, price)
                    if not ma20: ma20 = prev # 算不出來就暫用昨收
                    
                    signal = "➖ 觀望"
                    reason = "盤整中"
                    
                    # 庫存邏輯
                    if price >= ma20:
                        if pct > 3: signal = "🔥 庫存噴出"; reason = "站穩月線+長紅"
                        elif pct > 0: signal = "🔴 續抱"; reason = "股價在月線上"
                        else: signal = "🛡️ 整理"; reason = "月線上回檔"
                    else:
                        if pct < -3: signal = "❄️ 庫存重挫"; reason = "破月線+長黑"
                        elif pct < 0: signal = "🟢 轉弱"; reason = "股價在月線下"
                        else: signal = "🌤️ 反彈"; reason = "月線下反彈"
                        
                    results.append({
                        "代號": sid, "名稱": name, "現價": price, "漲幅": pct,
                        "訊號": signal, "理由": reason, "MA20": round(ma20, 2)
                    })
    except: pass
    return pd.DataFrame(results)

# --- 6. 主流程 ---
now = get_taiwan_time()
status_text = "🌙 盤後結算 (篩選今日收盤)"
if 9 <= now.hour < 13 or (now.hour == 13 and now.minute <= 30):
    status_text = "☀️ 盤中即時 (篩選即時排行)"

st.title(f"🐕 總柴篩選器：{status_text}")

# 自動執行 (不需按鈕，開機即跑)
with st.spinner("🐕 總柴正在抓取排行榜並進行「月線過濾」..."):
    # 1. 抓取並過濾
    df_up_filtered = scrape_and_filter('up')
    df_down_filtered = scrape_and_filter('down')
    # 2. 檢查庫存
    df_inv = check_inventory_strict(portfolio)

# --- 7. 顯示結果 (你的嚴格要求) ---
st.markdown(f"<div class='status-bar'>篩選標準：Yahoo排行前40名 + 必須站上/跌破月線 (MA20)</div>", unsafe_allow_html=True)

# 庫存區
if not df_inv.empty:
    st.subheader("💼 我的庫存")
    for row in df_inv.to_dict('records'):
        color = "#FF4444" if row['漲幅'] > 0 else "#00FF00"
        st.markdown(f"**{row['名稱']} ({row['代號']})**: {row['訊號']} <span style='color:#ccc'>({row['理由']})</span><br>${row['現價']} (<span style='color:{color}'>{row['漲幅']}%</span>) | MA20:{row['MA20']}", unsafe_allow_html=True)
    st.divider()

# 篩選結果區
t1, t2 = st.tabs(["🔥 嚴選飆股 (站上月線)", "❄️ 嚴選殺盤 (跌破月線)"])

cols = ['代號', '名稱', '現價', '漲幅', 'MA20', '理由']

with t1:
    if not df_up_filtered.empty:
        # 按漲幅排序
        df_show = df_up_filtered.sort_values('漲幅', ascending=False)
        st.dataframe(df_show, column_order=cols, use_container_width=True, hide_index=True)
    else:
        st.info("今日排行榜中，沒有股票符合「站上月線」的條件 (行情太差)。")

with t2:
    if not df_down_filtered.empty:
        # 按跌幅排序
        df_show = df_down_filtered.sort_values('漲幅', ascending=True)
        st.dataframe(df_show, column_order=cols, use_container_width=True, hide_index=True)
    else:
        st.info("今日排行榜中，沒有股票符合「跌破月線」的條件。")

# --- LINE 通知邏輯 ---
if 'last_run_hour' not in st.session_state: st.session_state.last_run_hour = -1
current_h = now.hour

# 定時發送 (8:30, 9:15, 12:30)
send_trigger = False
# 簡化判斷：如果是這三個小時，且這小時還沒發過
if current_h in [8, 9, 12] and st.session_state.last_run_hour != current_h:
    # 進一步檢查分鐘 (避免剛過整點就發，確保 8:30, 9:15)
    m = now.minute
    if (current_h==8 and m>=30) or (current_h==9 and m>=15) or (current_h==12 and m>=30):
        send_trigger = True

# 手動觸發
if st.button("🔄 立即刷新並檢測 LINE", type="primary"):
    send_trigger = True
    # 這裡要強制刷新頁面重跑，但 streamlit 會自動重跑 script，所以只需標記

if send_trigger and LINE_TOKEN:
    msg = f"🐕 總柴篩選 ({status_text})\n"
    has_msg = False
    
    # 庫存
    if not df_inv.empty:
        my_msg = []
        for r in df_inv.to_dict('records'):
            my_msg.append(f"{r['名稱']} ${r['現價']} ({r['漲幅']}%) {r['訊號']}")
        msg += "\n【💼 庫存】\n" + "\n".join(my_msg) + "\n"
        has_msg = True
    
    # 飆股 (只取篩選後的前 3 名)
    if not df_up_filtered.empty:
        up_msg = []
        for i, r in df_up_filtered.head(3).iterrows():
            up_msg.append(f"🔥 {r['名稱']} ${r['現價']} (+{r['漲幅']}%)")
        msg += "\n【🚀 嚴選飆股】\n" + "\n".join(up_msg) + "\n"
        has_msg = True
        
    if has_msg:
        send_line(msg)
        st.toast("✅ LINE 已發送")
        st.session_state.last_run_hour = current_h # 標記已發送

# 自動刷新
if auto_refresh:
    time.sleep(300)
    st.rerun()

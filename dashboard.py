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
    page_title="總柴快報 (強制補位版)",
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

st.title("🐕 總柴台股快報：絕對有資料版")

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

# --- 5. 資料庫 ---
SECTOR_DB = {
    "🔥 半導體": {'2330':'台積電','2454':'聯發科','2303':'聯電','3711':'日月光','3034':'聯詠','2379':'瑞昱','3443':'創意','3661':'世芯-KY','3035':'智原','3529':'力旺','6531':'愛普','3189':'景碩','8046':'南電','3037':'欣興','8299':'群聯','3260':'威剛','2408':'南亞科','4966':'譜瑞','6104':'創惟','6415':'矽力','6756':'威鋒','2344':'華邦電','2337':'旺宏','6271':'同欣電','5269':'祥碩','8016':'矽創','8131':'福懋科','8131':'福懋科'},
    "🤖 AI與電腦": {'2382':'廣達','3231':'緯創','2356':'英業達','6669':'緯穎','2376':'技嘉','2357':'華碩','2324':'仁寶','2301':'光寶科','3017':'奇鋐','3324':'雙鴻','2421':'建準','3653':'健策','3483':'力致','8996':'高力','2368':'金像電','6274':'台燿','6213':'聯茂','2395':'研華','6414':'樺漢','3483':'力致'},
    "📡 網通光電": {'2345':'智邦','5388':'中磊','3596':'智易','6285':'啟碁','4906':'正文','3704':'合勤控','3062':'建漢','2409':'友達','3481':'群創','6116':'彩晶','3008':'大立光','3406':'玉晶光','4961':'天鈺'},
    "⚡ 重電綠能": {'1513':'中興電','1519':'華城','1503':'士電','1514':'亞力','1609':'大亞','1605':'華新','1618':'合機','1603':'華電','6806':'森崴能源','3708':'上緯投控','9958':'世紀鋼','2031':'新光鋼','1504':'東元','1605':'華新'},
    "🏗️ 營建資產": {'2501':'國建','2542':'興富發','2548':'華固','5522':'遠雄','2520':'冠德','2515':'中工','2538':'基泰','2505':'國揚','2547':'日勝生','5534':'長虹','2545':'皇翔','2537':'聯上發','9940':'信義'},
    "🏥 生技醫療": {'1795':'美時','4743':'合一','6472':'保瑞','1760':'寶齡','6446':'藥華藥','4128':'中天','4162':'智擎','4114':'健喬','3205':'佰研','4105':'東洋','4123':'晟德','4133':'亞諾法','6547':'高端'},
    "🚢 航運軍工": {'2603':'長榮','2609':'陽明','2615':'萬海','2618':'長榮航','2610':'華航','2637':'慧洋','2606':'裕民','5608':'四維航','2634':'漢翔','8033':'雷虎','8222':'寶一','5284':'jpp-KY','2630':'亞航'},
    "🚗 汽車": {'2201':'裕隆','2204':'中華','2207':'和泰車','1319':'東陽','1521':'大億','1536':'和大','3665':'貿聯','4551':'智伸科'},
    "💰 金融": {'2881':'富邦金','2882':'國泰金','2891':'中信金','2886':'兆豐金','2884':'玉山金','2885':'元大金','2892':'第一金','2880':'華南金','2883':'開發金','2890':'永豐金','5880':'合庫金','2887':'台新金'},
    "🥤 傳產": {'1216':'統一','2707':'晶華','2723':'美食-KY','2727':'王品','1476':'儒鴻','1402':'遠東新','9910':'豐泰','9904':'寶成','1301':'台塑','1303':'南亞','1326':'台化','1907':'永豐餘','1904':'正隆','1802':'台玻','2105':'正新'},
    "📈 ETF": {'0050':'0050','0056':'0056','00878':'00878','00929':'00929','00940':'00940','00919':'00919','00632R':'反1','00679B':'美債'}
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

# --- 6. 核心：強制取值邏輯 ---
def get_stock_data_safe(sid):
    # 策略 1: 嘗試即時
    try:
        data = twstock.realtime.get(sid)
        if data['success']:
            rt = data['realtime']
            price_str = rt['latest_trade_price']
            
            # 關鍵修正：如果即時價是 '-' 或空，視為無效，跳去策略2
            if price_str == '-' or not price_str:
                raise ValueError("No realtime price")
                
            price = float(price_str)
            try: prev = float(rt['previous_close'])
            except: prev = price
            
            return price, prev, "即時"
    except:
        pass

    # 策略 2: 抓收盤 (備援) - 這是為了確保一定有資料！
    try:
        stock = twstock.Stock(sid)
        # 抓最近 5 天，確保有資料
        hist = stock.fetch_from(2024, 1) # twstock 會自動優化
        if len(hist) >= 2:
            # 倒數第一筆是最近的收盤 (可能是今天或昨天)
            price = hist[-1].close
            prev = hist[-2].close
            return price, prev, "收盤"
    except:
        return 0, 0, "無資料"
    
    return 0, 0, "無資料"

# 計算 MA20 (用歷史資料)
def calculate_ma20(sid):
    try:
        stock = twstock.Stock(sid)
        hist = stock.fetch_from(2024, 1)
        if len(hist) < 20: return None
        return sum([x.close for x in hist[-20:]]) / 20
    except: return None

# --- 7. 掃描邏輯 ---
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
    
    st.toast("🐕 強力掃描中 (含收盤備援)...")
    BATCH = 10 # 降低批次量，避免卡住
    
    # 這裡不能用 batch get，因為要針對每一檔做 fallback 處理
    # 雖然慢一點，但保證準確
    
    progress = 0
    total = len(target_codes)
    
    # 為了速度，還是先試 batch，失敗的再單獨抓
    # 但 twstock batch 若失敗很難 fallback，我們改用迴圈快速處理
    
    for i, sid in enumerate(target_codes):
        try:
            price, prev, source = get_stock_data_safe(sid)
            
            if price == 0: continue # 真的抓不到就算了
            
            pct = round(((price-prev)/prev)*100, 2)
            
            name = code_info[sid]['name']
            is_inv = code_info[sid]['is_inv']
            sec = code_info[sid]['sector']
            
            # 策略核心
            ma20 = prev
            has_ma = False
            
            # 只要是庫存，或者漲跌幅有動靜，就算 MA20
            # 這次放寬：只要有漲跌都算，確保資料完整
            real_ma20 = calculate_ma20(sid)
            if real_ma20:
                ma20 = real_ma20
                has_ma = True
            
            signal = "➖ 盤整"
            reason = "波動不大"
            code_val = 0 
            
            # === 旺大 x 麻紗 邏輯 ===
            
            # 1. 買方訊號
            if pct > 0:
                # 飆股：漲 > 3.5% 且 站上月線
                if pct > 3.5 and price >= ma20:
                    signal = "🔥 飆股噴出"
                    reason = f"🚀 爆量長紅 (>{ma20:.1f})"
                    code_val = 10
                    buy_sigs.append({'msg': f"🔥 {name} ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                
                # 多頭：漲 > 0 且 站上月線
                elif price >= ma20:
                    signal = "🔴 多頭排列"
                    reason = "🛡️ 站穩月線"
                    code_val = 5
                    if is_inv or pct > 2: # 庫存或漲2%才通知
                        buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                
                # 反彈：月線下但漲
                else:
                    signal = "🌤️ 跌深反彈"
                    reason = "⚠️ 月線下反彈"
                    code_val = 2
            
            # 2. 賣方訊號
            elif pct < 0:
                # 殺盤：跌 > 3.5%
                if pct < -3.5:
                    signal = "❄️ 重挫殺盤"
                    reason = "📉 恐慌賣壓"
                    code_val = -10
                    sell_sigs.append({'msg': f"❄️ {name} ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                
                # 轉弱：跌破月線
                elif price < ma20:
                    signal = "🟢 轉弱破線"
                    reason = f"❌ 跌破月線 ({ma20:.1f})"
                    code_val = -5
                    if is_inv or pct < -2:
                        sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                
                # 回檔：月線上但跌
                else:
                    signal = "📉 漲多回檔"
                    reason = "🛡️ 月線上整理"
                    code_val = -2

            # 標記來源 (如果是收盤價，加個備註)
            if source == "收盤":
                name = f"{name}(收)"

            results.append({
                '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                '訊號': signal, '理由': reason, 'MA20': round(ma20, 2),
                'code': code_val, '族群': sec, 'is_inv': is_inv
            })
            
        except: pass
        
    if not results: return pd.DataFrame(), [], []
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 8. 主流程 ---
targets, info = get_targets(portfolio, selected_sectors)
run_now = False
trigger_source = "auto"

if st.session_state.last_scan_data.empty:
    run_now = True; trigger_source = "init"

if st.button("🔄 立即刷新 (強制補位)", type="primary"):
    run_now = True; trigger_source = "manual"

# 排程
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

        hot_buys = [x['msg'] for x in buys if not x['is_inv'] and "🔥" in x['msg']]
        if hot_buys: 
            msg_body += "\n【🔥 飆股噴出】\n" + "\n".join(hot_buys[:5]) + "\n"
            should_send = True
            
        hot_sells = [x['msg'] for x in sells if not x['is_inv'] and "❄️" in x['msg']]
        if hot_sells: 
            msg_body += "\n【❄️ 重挫殺盤】\n" + "\n".join(hot_sells[:5]) + "\n"
            should_send = True

        if should_send or trigger_source == "manual":
            title = f"🐕 總柴快報 ({trigger_source})"
            if not should_send: msg_body = "\n(市場平靜，無特殊訊號)"
            send_line(title + "\n" + msg_body)
            st.toast("✅ LINE 通知已發送")

# --- 9. 顯示 ---
st.markdown(f"<div class='status-bar'>🕒 更新時間: {st.session_state.last_update_time}</div>", unsafe_allow_html=True)

df_show = st.session_state.last_scan_data
if not df_show.empty:
    if portfolio:
        st.markdown("### 💼 我的庫存")
        my_df = df_show[df_show['is_inv'] == True]
        if not my_df.empty:
            for row in my_df.itertuples():
                color = "#FF4444" if row.漲幅 > 0 else "#00FF00"
                st.markdown(f"**{row.名稱} ({row.代號})**: {row.訊號} <span style='color:#888'>({row.理由})</span><br>${row.現價} (<span style='color:{color}'>{row.漲幅}%</span>) | MA20:{row.MA20}", unsafe_allow_html=True)
        else: st.info("庫存無資料")

    st.divider()
    
    t1, t2, t3 = st.tabs(["📈 多方排行", "📉 空方排行", "全部列表"])
    cols = ['名稱', '現價', '漲幅', '訊號', '理由']
    
    with t1:
        d1 = df_show[df_show['漲幅'] >= 0].sort_values('漲幅', ascending=False)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
    with t2:
        d2 = df_show[df_show['漲幅'] < 0].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(df_show.sort_values('漲幅', ascending=False), column_order=cols, use_container_width=True, hide_index=True)
else:
    st.info("🐕 總柴暖身中... (請稍候)")

if auto_refresh:
    time.sleep(300)
    st.rerun()

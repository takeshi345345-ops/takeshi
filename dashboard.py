import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
import json
from FinMind.data import DataLoader

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
    page_title="總柴快報 (籌碼嚴選版)",
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

st.title("🐕 總柴台股快報：技術+籌碼嚴選")

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

# --- 5. 深度分析函式 (技術+籌碼) ---
def analyze_deep(sid):
    # 這個函式只對「潛在飆股」執行，避免全市場掃描太慢
    try:
        # 1. 抓歷史股價 (算 MA20)
        stock = twstock.Stock(sid)
        stock.fetch_from(2024, 1)
        if len(stock.price) < 20: return None, "資料不足"
        ma20 = sum(stock.price[-20:]) / 20
        
        # 2. 抓法人籌碼 (FinMind 抓近3日)
        dl = DataLoader()
        # 抓最近 10 天確保有資料
        start_d = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
        df_chips = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=start_d)
        
        chips_status = "中性"
        if not df_chips.empty:
            # 取最近 3 天的資料
            recent = df_chips.tail(6) # 3天 * 2種法人(外資/投信) approx
            # 簡單加總 外資 + 投信 的買賣超
            total_buy = recent['buy'].sum()
            total_sell = recent['sell'].sum()
            net = total_buy - total_sell
            
            if net > 0: chips_status = "法人買超"
            elif net < 0: chips_status = "法人賣超"
            
        return ma20, chips_status
    except:
        return None, "查無籌碼"

# --- 6. 核心掃描 ---
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
    
    st.toast("🐕 第一階段：全市場即時掃描...")
    BATCH = 20
    
    for i in range(0, len(target_codes), BATCH):
        batch = target_codes[i:i+BATCH]
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
                        
                        name = code_info[sid]['name']
                        is_inv = code_info[sid]['is_inv']
                        sec = code_info[sid]['sector']
                        
                        # === 第二階段：深度分析 (只針對有波動或庫存) ===
                        ma20 = prev # 預設昨收
                        ma20_source = "昨收"
                        chips = "未查詢"
                        
                        # 只有：庫存、漲>2%、跌<-2% 才去查 MA20 和 籌碼
                        # 這樣可以避開那些盤整的股票，把資源集中在飆股
                        is_active = is_inv or pct > 2.0 or pct < -2.0
                        
                        if is_active:
                            real_ma20, real_chips = analyze_deep(sid)
                            if real_ma20:
                                ma20 = real_ma20
                                ma20_source = "MA20"
                                chips = real_chips
                        
                        signal = "➖ 盤整"
                        reason = "量縮觀望"
                        code_val = 0 
                        
                        # === 你的嚴格篩選邏輯 ===
                        
                        # A. 推薦買進 (站上月線 + 爆量長紅 + 法人買/中性)
                        if price >= ma20 and pct > 3.0:
                            signal = "🔥 推薦買進"
                            reason = f"🚀 站上月線+爆量長紅 ({chips})"
                            code_val = 10
                            # 只有籌碼是正向或中性才推，法人大賣就不推
                            if "賣" not in chips:
                                buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%) | {reason}", 'is_inv': is_inv})
                        
                        # B. 庫存多頭 (站上月線)
                        elif is_inv and price >= ma20:
                             signal = "🔴 持股續抱"
                             reason = f"🛡️ 守穩月線 ({chips})"
                             code_val = 5

                        # C. 推薦賣出 (跌破月線 + 長黑 + 法人賣/中性)
                        elif price < ma20 and pct < -3.0:
                            signal = "❄️ 推薦賣出"
                            reason = f"📉 跌破月線+重挫 ({chips})"
                            code_val = -10
                            if "買" not in chips:
                                sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%) | {reason}", 'is_inv': is_inv})

                        # D. 庫存轉弱
                        elif is_inv and price < ma20:
                            signal = "🟢 庫存轉弱"
                            reason = f"❌ 跌破月線 ({chips})"
                            code_val = -5
                            sell_sigs.append({'msg': f"📉 {name} ${price} ({pct}%) | {reason}", 'is_inv': is_inv})
                        
                        # E. 其他 (單純顯示漲跌，不給訊號)
                        else:
                            if pct > 0: 
                                signal = "📈 上漲"
                                code_val = 1
                            elif pct < 0:
                                signal = "📉 下跌"
                                code_val = -1
                            if is_active:
                                reason = f"{ma20_source}盤整 ({chips})"

                        results.append({
                            '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                            '訊號': signal, '理由': reason, '籌碼': chips,
                            'code': code_val, '族群': sec, 'is_inv': is_inv
                        })
            time.sleep(0.5)
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

    # LINE 發送 (嚴格版)
    if LINE_TOKEN and trigger_source != "init":
        msg_body = ""
        should_send = False
        
        my_msgs = [x['msg'] for x in buys if x['is_inv']] + [x['msg'] for x in sells if x['is_inv']]
        if my_msgs: 
            msg_body += "\n【💼 庫存 (福懋科)】\n" + "\n".join(my_msgs) + "\n"
            should_send = True

        hot_buys = [x['msg'] for x in buys if not x['is_inv']]
        if hot_buys: 
            msg_body += "\n【🔥 推薦買進】\n" + "\n".join(hot_buys[:5]) + "\n"
            should_send = True
            
        hot_sells = [x['msg'] for x in sells if not x['is_inv']]
        if hot_sells: 
            msg_body += "\n【❄️ 推薦賣出】\n" + "\n".join(hot_sells[:5]) + "\n"
            should_send = True

        if should_send or trigger_source == "manual":
            title = f"🐕 總柴快報 ({trigger_source})"
            if not should_send: msg_body = "\n(無符合條件之標的)"
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
                st.markdown(f"**{row.名稱} ({row.代號})**: {row.訊號} <span style='color:#888'>({row.理由})</span><br>${row.現價} (<span style='color:{color}'>{row.漲幅}%</span>) | 籌碼:{row.籌碼}", unsafe_allow_html=True)
        else: st.info("庫存無資料")

    st.divider()
    
    t1, t2, t3 = st.tabs(["📈 多方排行", "📉 空方排行", "全部列表"])
    cols = ['名稱', '現價', '漲幅', '訊號', '籌碼', '理由']
    
    with t1:
        d1 = df_show[df_show['漲幅'] >= 0].sort_values('漲幅', ascending=False)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
    with t2:
        d2 = df_show[df_show['漲幅'] < 0].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(df_show.sort_values('漲幅', ascending=False), column_order=cols, use_container_width=True, hide_index=True)
else:
    st.info("🐕 總柴暖身中...")

if auto_refresh:
    time.sleep(300)
    st.rerun()

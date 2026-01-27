import streamlit as st
import pandas as pd
import twstock
import time
import datetime
from FinMind.data import DataLoader

# --- 0. 頁面設定 ---
st.set_page_config(
    page_title="總柴台股快報 (三班制)",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #FFFFFF; }
    h1, h2, h3 { color: #00E5FF !important; }
    .stock-card { padding: 12px; margin-bottom: 8px; border-radius: 6px; border-left: 6px solid #555; background: #1a1a1a; }
    .card-buy { border-left-color: #FF00FF; }
    .card-sell { border-left-color: #00FF00; }
    .card-wait { border-left-color: #FFD700; }
    .ticker { font-size: 1.1rem; font-weight: bold; color: #fff; }
    .info { font-size: 0.9rem; color: #ccc; }
    .sector-tag { font-size: 0.8rem; color: #00E5FF; background: #222; padding: 2px 6px; border-radius: 4px; margin-right: 5px; }
    .notify-status { background: #333; padding: 10px; border-radius: 5px; text-align: center; color: #FFA500; font-weight: bold; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴台股快報：三班制監控")

# --- 1. 自動讀取 Token (免輸入) ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    # 如果沒設定 Secrets，才顯示輸入框
    with st.sidebar:
        st.warning("💡 提示：去 Streamlit 後台設定 Secrets 就可以免輸入密碼喔！")
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

# --- 2. 初始化狀態 (紀錄今天有沒有發過) ---
if 'last_run_date' not in st.session_state:
    st.session_state.last_run_date = datetime.date.today()
    st.session_state.done_830 = False
    st.session_state.done_915 = False
    st.session_state.done_1230 = False

# 跨日重置
if st.session_state.last_run_date != datetime.date.today():
    st.session_state.last_run_date = datetime.date.today()
    st.session_state.done_830 = False
    st.session_state.done_915 = False
    st.session_state.done_1230 = False

# --- 3. 產業與庫存設定 ---
SECTOR_DB = {
    "🔥 半導體": {'2330':'台積電','2454':'聯發科','2303':'聯電','3711':'日月光','3034':'聯詠','2379':'瑞昱','3443':'創意','3661':'世芯-KY','3035':'智原','3529':'力旺','6531':'愛普','3189':'景碩','8046':'南電','3037':'欣興','8299':'群聯','3260':'威剛','2408':'南亞科','4966':'譜瑞','6104':'創惟','6415':'矽力','6756':'威鋒','2344':'華邦電','2337':'旺宏','6271':'同欣電','5269':'祥碩','8016':'矽創','8131':'福懋科'},
    "🤖 AI與電腦": {'2382':'廣達','3231':'緯創','2356':'英業達','6669':'緯穎','2376':'技嘉','2357':'華碩','2324':'仁寶','2301':'光寶科','3017':'奇鋐','3324':'雙鴻','2421':'建準','3653':'健策','3483':'力致','8996':'高力','2368':'金像電','6274':'台燿','6213':'聯茂','2395':'研華','6414':'樺漢','3483':'力致'},
    "📡 網通光電": {'2345':'智邦','5388':'中磊','3596':'智易','6285':'啟碁','4906':'正文','3704':'合勤控','3062':'建漢','2409':'友達','3481':'群創','6116':'彩晶','3008':'大立光','3406':'玉晶光','4961':'天鈺'},
    "⚡ 重電綠能": {'1513':'中興電','1519':'華城','1503':'士電','1514':'亞力','1609':'大亞','1605':'華新','1618':'合機','1603':'華電','6806':'森崴能源','3708':'上緯投控','9958':'世紀鋼','2031':'新光鋼','1504':'東元'},
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
    auto_refresh = st.toggle("啟動自動監控", value=True, help="開啟後，網頁會自動刷新檢查時間")
    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號", "2330, 2603")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    
    st.divider()
    all_sectors = list(SECTOR_DB.keys())
    selected_sectors = st.multiselect("掃描族群", all_sectors, default=all_sectors)

# --- 4. LINE 發送 ---
def send_line(msg):
    if not LINE_TOKEN: return False, "No Token"
    import requests, json
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"messages": [{"type": "text", "text": msg}]}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload))
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

# --- 5. 掃描函式 (A. 昨日數據 B. 即時數據) ---

def get_targets(user_port, sectors):
    target_codes = set(user_port)
    code_info = {p: {'name': f"庫存({p})", 'sector': '💼 我的庫存', 'is_inv': True} for p in user_port}
    for sec in sectors:
        for code, name in SECTOR_DB[sec].items():
            target_codes.add(code)
            if code not in code_info:
                code_info[code] = {'name': name, 'sector': sec, 'is_inv': False}
    return list(target_codes), code_info

def scan_yesterday(target_codes, code_info):
    # 用 FinMind 抓昨天收盤 (08:30 用)
    dl = DataLoader()
    start_date = (datetime.datetime.now() - datetime.timedelta(days=45)).strftime('%Y-%m-%d')
    
    results, buy_sigs, sell_sigs = [], [], []
    
    # 這裡只抓大盤與幾個代表性的，為了效率我們用簡單策略：抓每檔個股最近30日
    # 因為 FinMind 免費版限制，我們這裡模擬「盤前掃描」
    # 為了不卡頓，這裡用 twstock 抓歷史 (因為是盤前，不會被即時擋)
    
    bar = st.progress(0, text="🐕 盤前掃描中 (昨日收盤數據)...")
    for i, sid in enumerate(target_codes):
        if i % 5 == 0: bar.progress(min(i/len(target_codes), 0.9))
        try:
            stock = twstock.Stock(sid)
            data = stock.fetch_from(2023, 1) # 其實只抓最近就好，twstock 會自動優化
            if len(stock.price) < 20: continue
            
            price = stock.price[-1]
            prev = stock.price[-2]
            ma20 = sum(stock.price[-20:]) / 20
            
            pct = round(((price - prev)/prev)*100, 2)
            vol_ratio = 1.0 # 簡化
            
            # 策略
            name = code_info[sid]['name']
            is_inv = code_info[sid]['is_inv']
            sec = code_info[sid]['sector']
            
            msg = None
            if price > ma20:
                if pct > 2.5: 
                    msg = f"🔴 {name} ${price} (+{pct}%) 🔥昨日轉強"
                    buy_sigs.append({'msg': msg, 'is_inv': is_inv, 'sector': sec})
            else:
                if pct < -2:
                    msg = f"🟢 {name} ${price} ({pct}%) 📉昨日破線"
                    sell_sigs.append({'msg': msg, 'is_inv': is_inv, 'sector': sec})
            
            results.append({'代號': sid, '名稱': name, '現價': price, '漲幅': pct, '訊號': '昨日數據'})
        except: pass
        
    bar.empty()
    return pd.DataFrame(results), buy_sigs, sell_sigs

def scan_realtime(target_codes, code_info):
    # 用 twstock 抓即時 (09:15, 12:30 用)
    results, buy_sigs, sell_sigs = [], [], []
    bar = st.progress(0, text="🐕 盤中即時掃描中...")
    
    BATCH = 20
    for i in range(0, len(target_codes), BATCH):
        batch = target_codes[i:i+BATCH]
        try:
            stocks = twstock.realtime.get(batch)
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        rt = data['realtime']
                        price = float(rt['latest_trade_price']) if rt['latest_trade_price'] != '-' else 0
                        if price == 0: continue
                        prev = float(rt['previous_close'])
                        pct = round(((price-prev)/prev)*100, 2)
                        
                        name = code_info[sid]['name']
                        is_inv = code_info[sid]['is_inv']
                        sec = code_info[sid]['sector']
                        
                        # 簡單策略：漲跌幅 > 2%
                        if pct > 2.5:
                            buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%) 🔥即時攻擊", 'is_inv': is_inv, 'sector': sec})
                        elif pct < -2:
                            sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%) 📉即時急殺", 'is_inv': is_inv, 'sector': sec})
                            
                        results.append({'代號': sid, '名稱': name, '現價': price, '漲幅': pct, '訊號': '即時'})
            bar.progress(min((i+BATCH)/len(target_codes), 0.9))
            time.sleep(1)
        except: pass
    bar.empty()
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 6. 核心邏輯控制 ---

# 大大的手動按鈕
if st.button("🔍 立即手動更新 (抓即時)", type="primary"):
    targets, info = get_targets(portfolio, selected_sectors)
    df, buys, sells = scan_realtime(targets, info)
    st.dataframe(df)
    if buys or sells:
        st.info("掃描到訊號！")

# 自動排程邏輯
now = datetime.datetime.now()
current_time_str = now.strftime("%H:%M")

targets, info = get_targets(portfolio, selected_sectors)
msg_prefix = ""
run_task = False
df_res = pd.DataFrame()
b_list, s_list = [], []

# 檢查時間點
# A. 08:30 盤前 (抓昨日)
if now.hour == 8 and now.minute >= 30 and not st.session_state.done_830:
    st.toast("⏰ 執行 08:30 盤前掃描...")
    df_res, b_list, s_list = scan_yesterday(targets, info)
    st.session_state.done_830 = True
    msg_prefix = "🐕 總柴早報 (盤前篩選)"
    run_task = True

# B. 09:15 早盤 (抓即時)
elif now.hour == 9 and now.minute >= 15 and not st.session_state.done_915:
    st.toast("⏰ 執行 09:15 早盤衝刺...")
    df_res, b_list, s_list = scan_realtime(targets, info)
    st.session_state.done_915 = True
    msg_prefix = "🐕 總柴早盤 (09:15)"
    run_task = True

# C. 12:30 午盤 (抓即時)
elif now.hour == 12 and now.minute >= 30 and not st.session_state.done_1230:
    st.toast("⏰ 執行 12:30 午盤結算...")
    df_res, b_list, s_list = scan_realtime(targets, info)
    st.session_state.done_1230 = True
    msg_prefix = "🐕 總柴午盤 (12:30)"
    run_task = True

# 發送通知
if run_task and (b_list or s_list):
    final_msg = f"{msg_prefix} | {datetime.date.today()}\n"
    
    # 整理訊息
    my_inv = [x['msg'] for x in b_list if x['is_inv']] + [x['msg'] for x in s_list if x['is_inv']]
    others = [x['msg'] for x in b_list if not x['is_inv']] + [x['msg'] for x in s_list if not x['is_inv']]
    
    if my_inv:
        final_msg += "\n【💼 庫存警示】\n" + "\n".join(my_inv) + "\n"
    if others:
        final_msg += "\n【👀 市場訊號】\n" + "\n".join(others[:15]) # 最多顯示15檔避免洗版
        if len(others) > 15: final_msg += f"\n...還有 {len(others)-15} 檔"
        
    success, res = send_line(final_msg)
    if success: st.success(f"✅ {msg_prefix} 已發送")
    else: st.error(f"發送失敗: {res}")

# 狀態顯示
st.divider()
st.markdown(f"**🕒 現在時間**: {current_time_str}")
col1, col2, col3 = st.columns(3)
col1.metric("08:30 盤前", "已執行" if st.session_state.done_830 else "待命")
col2.metric("09:15 早盤", "已執行" if st.session_state.done_915 else "待命")
col3.metric("12:30 午盤", "已執行" if st.session_state.done_1230 else "待命")

if auto_refresh:
    time.sleep(30) # 每30秒檢查一次時間
    st.rerun()

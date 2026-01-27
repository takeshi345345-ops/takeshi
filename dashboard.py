import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
import json
from FinMind.data import DataLoader

# --- 1. 暴力破解 SSL ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
old_merge_environment_settings = requests.Session.merge_environment_settings

def merge_environment_settings(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url:
        verify = False
    return old_merge_environment_settings(self, url, proxies, stream, verify, cert)

requests.Session.merge_environment_settings = merge_environment_settings

# --- 2. 頁面設定 ---
st.set_page_config(
    page_title="總柴台股快報 (靈敏版)",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #FFFFFF; }
    h1, h2, h3 { color: #00E5FF !important; }
    .stock-card { padding: 12px; margin-bottom: 8px; border-radius: 6px; border-left: 6px solid #555; background: #1a1a1a; }
    .card-buy { border-left-color: #FF00FF; } /* 強勢 */
    .card-sell { border-left-color: #00FF00; } /* 弱勢 */
    .card-wait { border-left-color: #FFD700; } /* 盤整 */
    .ticker { font-size: 1.1rem; font-weight: bold; color: #fff; }
    .info { font-size: 0.9rem; color: #ccc; }
    .sector-tag { font-size: 0.8rem; color: #00E5FF; background: #222; padding: 2px 6px; border-radius: 4px; margin-right: 5px; }
    .notify-status { background: #333; padding: 10px; border-radius: 5px; text-align: center; color: #FFA500; font-weight: bold; margin-bottom: 20px; }
    .patrol-mode { border: 1px solid #00E5FF; padding: 5px; border-radius: 5px; text-align: center; margin-bottom: 10px; color: #00E5FF; font-size: 0.8rem;}
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴台股快報：全揭露靈敏版")

# --- 3. Token ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

# --- 4. 狀態初始化 ---
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

# --- 5. 資料庫 ---
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
    auto_refresh = st.toggle("啟動自動監控", value=True)
    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號", "2330, 2603")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    
    st.divider()
    all_sectors = list(SECTOR_DB.keys())
    selected_sectors = st.multiselect("掃描族群", all_sectors, default=all_sectors)

# --- 6. LINE 發送 ---
def send_line(msg):
    if not LINE_TOKEN: return False, "No Token"
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"messages": [{"type": "text", "text": msg}]}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload))
        if r.status_code == 200:
            return True, "OK"
        else:
            return False, r.text
    except Exception as e:
        return False, str(e)

# --- 7. 核心掃描 (調降標準版) ---
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
    
    # 預設抓即時 (twstock)
    bar = st.progress(0, text="🐕 即時連線中...")
    BATCH = 15
    for i in range(0, len(target_codes), BATCH):
        batch = target_codes[i:i+BATCH]
        try:
            stocks = twstock.realtime.get(batch)
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        rt = data['realtime']
                        try:
                            price = float(rt['latest_trade_price'])
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
                        
                        # === 關鍵修改：分級制度 ===
                        signal = "➖ 盤整"
                        code_val = 0 # 0=平盤
                        
                        # --- 多方 (漲) ---
                        if pct > 3.0:
                            signal = "🔥 飆漲攻擊"
                            code_val = 10
                            buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%) 🔥飆漲", 'is_inv': is_inv, 'sector': sec})
                        elif pct > 0:
                            signal = "🔴 多頭排列"
                            code_val = 5
                            # 只有漲超過 1% 或是庫存才發通知，不然 LINE 會太吵
                            if pct > 1.0 or is_inv:
                                buy_sigs.append({'msg': f"📈 {name} ${price} (+{pct}%)", 'is_inv': is_inv, 'sector': sec})

                        # --- 空方 (跌) ---
                        elif pct < -3.0:
                            signal = "❄️ 破線重挫"
                            code_val = -10
                            sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%) ❄️重挫", 'is_inv': is_inv, 'sector': sec})
                        elif pct < 0:
                            signal = "🟢 漲多回檔"
                            code_val = -5
                            # 只有跌超過 1% 或是庫存才發通知
                            if pct < -1.0 or is_inv:
                                sell_sigs.append({'msg': f"📉 {name} ${price} ({pct}%)", 'is_inv': is_inv, 'sector': sec})
                        
                        # 0% 也是觀察
                        if pct == 0:
                            code_val = 0
                            
                        results.append({
                            '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                            '訊號': signal, 'code': code_val, '族群': sec, 'is_inv': is_inv
                        })
            
            bar.progress(min((i+BATCH)/len(target_codes), 0.9))
            time.sleep(0.5)
        except: pass
    bar.empty()

    if not results: return pd.DataFrame(), [], []
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 8. 主程式邏輯 ---
targets, info = get_targets(portfolio, selected_sectors)
df = pd.DataFrame()
buys, sells = [], []
run_source = None

# A. 手動按鈕
if st.button("🔍 立即手動更新 (抓即時)", type="primary"):
    run_source = 'manual'

# B. 自動排程檢查
now = datetime.datetime.now()
current_time_str = now.strftime("%H:%M")

if not run_source:
    if now.hour == 8 and now.minute >= 30 and not st.session_state.done_830:
        run_source = '830'
    elif now.hour == 9 and now.minute >= 15 and not st.session_state.done_915:
        run_source = '915'
    elif now.hour == 12 and now.minute >= 30 and not st.session_state.done_1230:
        run_source = '1230'

if run_source:
    if run_source == '830': 
        st.toast("⏰ 08:30 盤前掃描...")
        st.session_state.done_830 = True
        msg_title = "🐕 總柴早報"
    elif run_source == 'manual':
        st.toast("🚀 手動更新...")
        msg_title = "🐕 總柴即時快報 (手動)"
    else:
        st.toast(f"⏰ {run_source} 定時掃描...")
        if run_source == '915': st.session_state.done_915 = True
        if run_source == '1230': st.session_state.done_1230 = True
        msg_title = f"🐕 總柴定時快報 ({current_time_str})"
    
    # 執行
    df, buys, sells = scan_stocks(targets, info)
    
    if not df.empty:
        st.success(f"更新完成！({len(df)} 筆)")
        
        # 顯示庫存
        if portfolio:
            st.markdown("### 💼 我的庫存")
            my_df = df[df['is_inv'] == True]
            if not my_df.empty:
                for row in my_df.itertuples():
                    color = "#FF4444" if row.漲幅 > 0 else "#00FF00"
                    st.markdown(f"**{row.名稱} ({row.代號})**: {row.訊號} | ${row.現價} (<span style='color:{color}'>{row.漲幅}%</span>)", unsafe_allow_html=True)
            else: st.info("庫存暫無資料")

        st.divider()
        st.subheader("全市場掃描結果")
        
        # === 關鍵：不再只有空白，而是分成「漲」跟「跌」兩個大本營 ===
        t1, t2, t3 = st.tabs(["📈 多方/買進 (漲)", "📉 空方/賣出 (跌)", "全部"])
        
        cols = ['名稱', '族群', '現價', '漲幅', '訊號']
        
        with t1:
            # 只要漲幅 > 0 就進來，按漲幅排序
            d1 = df[df['涨幅'] > 0].sort_values('漲幅', ascending=False)
            if d1.empty: st.info("目前無上漲股票")
            else: st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
            
        with t2:
            # 只要漲幅 < 0 就進來，按跌幅排序 (漲幅越小越前面)
            d2 = df[df['漲幅'] < 0].sort_values('漲幅', ascending=True)
            if d2.empty: st.info("目前無下跌股票")
            else: st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
            
        with t3:
            st.dataframe(df.sort_values('漲幅', ascending=False), column_order=cols, use_container_width=True, hide_index=True)

        # === 發送 LINE (保證發送) ===
        if LINE_TOKEN:
            final_msg = f"{msg_title} | {datetime.date.today()}\n"
            
            # 1. 庫存
            my_msgs = [x['msg'] for x in buys if x['is_inv']] + [x['msg'] for x in sells if x['is_inv']]
            if my_msgs:
                final_msg += "\n【💼 庫存快報】\n" + "\n".join(my_msgs) + "\n"
            else:
                final_msg += "\n【💼 庫存】今日平穩\n"

            # 2. 市場精選 (只挑波動大的發通知，避免太吵)
            hot_buys = [x['msg'] for x in buys if not x['is_inv'] and "🔥" in x['msg']] # 只發飆漲的
            hot_sells = [x['msg'] for x in sells if not x['is_inv'] and "❄️" in x['msg']] # 只發重挫的
            
            # 如果都沒有飆漲重挫，就各抓前 3 名給你看
            if not hot_buys:
                hot_buys = [x['msg'] for x in buys if not x['is_inv']][:3]
            if not hot_sells:
                hot_sells = [x['msg'] for x in sells if not x['is_inv']][:3]

            if hot_buys: final_msg += "\n【🔥 市場焦點】\n" + "\n".join(hot_buys[:5]) + "\n"
            if hot_sells: final_msg += "\n【❄️ 弱勢焦點】\n" + "\n".join(hot_sells[:5]) + "\n"
            
            send_line(final_msg)
            st.toast("✅ LINE 通知已發送！")
            
    else:
        st.error("無法取得資料，請稍後再試。")

st.markdown(f"<div class='patrol-mode'>🕒 現在時間: {current_time_str} | 自動監控中</div>", unsafe_allow_html=True)
if auto_refresh:
    time.sleep(30)
    st.rerun()

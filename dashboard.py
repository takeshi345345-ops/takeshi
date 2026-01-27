import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
import json
from FinMind.data import DataLoader

# --- 🔥 1. 暴力破解 SSL (確保雲端能抓到即時資料) ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
old_merge_environment_settings = requests.Session.merge_environment_settings

def merge_environment_settings(self, url, proxies, stream, verify, cert):
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url:
        verify = False
    return old_merge_environment_settings(self, url, proxies, stream, verify, cert)

requests.Session.merge_environment_settings = merge_environment_settings

# --- 2. 頁面設定 ---
st.set_page_config(
    page_title="總柴台股快報 (完美修復版)",
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
    /* 讓自動刷新的計時器比較明顯 */
    .patrol-mode { border: 1px solid #00E5FF; padding: 5px; border-radius: 5px; text-align: center; margin-bottom: 10px; color: #00E5FF; font-size: 0.8rem;}
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴台股快報：介面與通知修復版")

# --- 3. 自動讀取 Token (優先讀 Secrets) ---
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
    # 預設開啟自動監控，讓計時器能跑
    auto_refresh = st.toggle("啟動自動監控 (三班制)", value=True, help="開啟後，網頁會自動刷新，時間到自動發LINE")
    
    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號", "2330, 2603")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    
    st.divider()
    all_sectors = list(SECTOR_DB.keys())
    selected_sectors = st.multiselect("掃描族群", all_sectors, default=all_sectors)

# --- 6. LINE 發送函式 (debug版) ---
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

# --- 7. 核心掃描 (統合版) ---
def get_targets(user_port, sectors):
    target_codes = set(user_port)
    code_info = {p: {'name': f"庫存({p})", 'sector': '💼 我的庫存', 'is_inv': True} for p in user_port}
    for sec in sectors:
        for code, name in SECTOR_DB[sec].items():
            target_codes.add(code)
            if code not in code_info:
                code_info[code] = {'name': name, 'sector': sec, 'is_inv': False}
    return list(target_codes), code_info

def scan_stocks(target_codes, code_info, mode="realtime"):
    # mode: 'realtime' (即時, twstock) 或 'yesterday' (昨收, finmind)
    results, buy_sigs, sell_sigs = [], [], []
    
    # === A. 即時模式 (Twstock) ===
    if mode == "realtime":
        bar = st.progress(0, text="🐕 即時連線中 (SSL已忽略)...")
        BATCH = 15
        for i in range(0, len(target_codes), BATCH):
            batch = target_codes[i:i+BATCH]
            try:
                stocks = twstock.realtime.get(batch)
                if stocks:
                    for sid, data in stocks.items():
                        if data['success']:
                            rt = data['realtime']
                            # 價格處理
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
                            
                            # === 訊號判定 (恢復篩股架構) ===
                            signal = "🛡️ 觀望"
                            code_val = 0 # 10=買, -10=賣, 5=觀察
                            
                            # 買進條件: 漲幅 > 2%
                            if pct > 2.0:
                                signal = "🔥 強勢攻擊"
                                code_val = 10
                                buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%)", 'is_inv': is_inv, 'sector': sec})
                            
                            # 賣出條件: 跌幅 > 2%
                            elif pct < -2.0:
                                signal = "📉 弱勢破線"
                                code_val = -10
                                sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%)", 'is_inv': is_inv, 'sector': sec})
                            
                            # 觀察條件: 漲幅 0~2% 且是庫存
                            elif is_inv and pct >= 0:
                                signal = "👀 續抱觀察"
                                code_val = 5
                            
                            results.append({
                                '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                                '訊號': signal, 'code': code_val, '族群': sec, 'is_inv': is_inv
                            })
                
                bar.progress(min((i+BATCH)/len(target_codes), 0.9))
                time.sleep(1)
            except: pass
        bar.empty()

    # === B. 昨日模式 (FinMind) ===
    else:
        bar = st.progress(0, text="🐕 盤前掃描昨收 (FinMind)...")
        dl = DataLoader()
        start_date = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
        
        # 為了效率，分批取樣
        count = 0
        total = len(target_codes)
        
        for sid in target_codes:
            count += 1
            if count % 5 == 0: bar.progress(min(count/total, 0.9))
            try:
                df = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
                if df.empty or len(df) < 2: continue
                
                curr = df.iloc[-1]
                prev = df.iloc[-2]
                price = float(curr['close'])
                prev_price = float(prev['close'])
                pct = round(((price-prev_price)/prev_price)*100, 2)
                
                name = code_info[sid]['name']
                is_inv = code_info[sid]['is_inv']
                sec = code_info[sid]['sector']
                
                signal = "🛡️ 觀望"
                code_val = 0
                
                if pct > 2.0:
                    signal = "🔥 昨轉強"
                    code_val = 10
                    buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%)", 'is_inv': is_inv, 'sector': sec})
                elif pct < -2.0:
                    signal = "📉 昨弱勢"
                    code_val = -10
                    sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%)", 'is_inv': is_inv, 'sector': sec})
                
                results.append({
                    '代號': sid, '名稱': name, '現價': price, '漲幅': pct, 
                    '訊號': signal, 'code': code_val, '族群': sec, 'is_inv': is_inv
                })
            except: pass
        bar.empty()

    if not results: return pd.DataFrame(), [], []
    return pd.DataFrame(results), buy_sigs, sell_sigs


# --- 8. 主程式邏輯 ---

# 建立目標清單
targets, info = get_targets(portfolio, selected_sectors)
df = pd.DataFrame()
buys, sells = [], []
run_source = None # 'manual', '830', '915', '1230'

# A. 手動按鈕
if st.button("🔍 立即手動更新 (抓即時)", type="primary"):
    run_source = 'manual'

# B. 自動排程檢查
now = datetime.datetime.now()
current_time_str = now.strftime("%H:%M")

if not run_source: # 如果沒按按鈕，檢查時間
    if now.hour == 8 and now.minute >= 30 and not st.session_state.done_830:
        run_source = '830'
    elif now.hour == 9 and now.minute >= 15 and not st.session_state.done_915:
        run_source = '915'
    elif now.hour == 12 and now.minute >= 30 and not st.session_state.done_1230:
        run_source = '1230'

# --- 執行掃描與發送 ---
if run_source:
    if run_source == '830':
        st.toast("⏰ 08:30 盤前掃描啟動...")
        df, buys, sells = scan_stocks(targets, info, mode="yesterday")
        st.session_state.done_830 = True
        msg_title = "🐕 總柴早報 (盤前)"
    elif run_source == 'manual':
        st.toast("🚀 手動更新啟動...")
        df, buys, sells = scan_stocks(targets, info, mode="realtime")
        msg_title = "🐕 總柴即時快報 (手動)"
    else: # 915, 1230
        st.toast(f"⏰ {run_source} 定時掃描啟動...")
        df, buys, sells = scan_stocks(targets, info, mode="realtime")
        if run_source == '915': st.session_state.done_915 = True
        if run_source == '1230': st.session_state.done_1230 = True
        msg_title = f"🐕 總柴定時快報 ({current_time_str})"
    
    # 顯示結果
    if not df.empty:
        st.success(f"掃描完成！({len(df)} 筆資料)")
        
        # 恢復原本的「庫存 + 分頁」架構
        if portfolio:
            st.markdown("### 💼 我的庫存")
            my_df = df[df['is_inv'] == True]
            if not my_df.empty:
                for row in my_df.itertuples():
                    color = "#FF4444" if row.漲幅 > 0 else "#00FF00"
                    st.markdown(f"**{row.名稱} ({row.代號})**: {row.訊號} | ${row.現價} (<span style='color:{color}'>{row.漲幅}%</span>)", unsafe_allow_html=True)
            else:
                st.info("庫存無資料")

        st.divider()
        st.subheader("全市場掃描結果")
        
        # === 這裡就是你要的「架構」回來了 ===
        t1, t2, t3, t4 = st.tabs(["👍 推薦買進", "👎 推薦賣出", "🔥 觀察名單", "全部"])
        
        cols = ['名稱', '族群', '現價', '漲幅', '訊號']
        
        with t1:
            # code = 10 (強勢)
            d1 = df[df['code'] == 10].sort_values('漲幅', ascending=False)
            st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True)
            
        with t2:
            # code = -10 (弱勢)
            d2 = df[df['code'] == -10].sort_values('漲幅', ascending=True)
            st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True)
            
        with t3:
            # code = 5 (觀察/續抱) 或 漲跌幅不大的
            d3 = df[(df['code'] != 10) & (df['code'] != -10)].sort_values('漲幅', ascending=False)
            st.dataframe(d3, column_order=cols, use_container_width=True, hide_index=True)
            
        with t4:
            st.dataframe(df, column_order=cols, use_container_width=True, hide_index=True)

        # === 發送 LINE 通知 (確保一定發送) ===
        if LINE_TOKEN:
            final_msg = f"{msg_title} | {datetime.date.today()}\n"
            
            # 庫存優先
            my_inv_msg = [x['msg'] for x in buys if x['is_inv']] + [x['msg'] for x in sells if x['is_inv']]
            if my_inv_msg:
                final_msg += "\n【💼 庫存警示】\n" + "\n".join(my_inv_msg) + "\n"
            elif run_source == 'manual':
                 final_msg += "\n【💼 庫存】無特殊訊號\n"

            # 市場訊號
            others_buy = [x['msg'] for x in buys if not x['is_inv']]
            others_sell = [x['msg'] for x in sells if not x['is_inv']]
            
            if others_buy:
                final_msg += "\n【🔥 市場強勢】\n" + "\n".join(others_buy[:10]) + "\n"
            if others_sell:
                final_msg += "\n【❄️ 市場弱勢】\n" + "\n".join(others_sell[:10]) + "\n"
            
            # 如果是手動更新，就算沒訊號也要發個通知確認
            if not buys and not sells and run_source == 'manual':
                final_msg += "\n(目前市場平靜，無符合策略之標的)"
                
            # 發送
            ok, res = send_line(final_msg)
            if ok: st.toast("✅ LINE 通知已發送！")
            else: st.error(f"LINE 發送失敗: {res}")
            
    else:
        st.error("無法取得資料，請稍後再試。")

# --- 狀態列與自動刷新 ---
st.markdown(f"<div class='patrol-mode'>🕒 現在時間: {current_time_str} | 自動監控: {'開啟' if auto_refresh else '關閉'}</div>", unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
col1.metric("08:30 盤前", "已執行" if st.session_state.done_830 else "待命")
col2.metric("09:15 早盤", "已執行" if st.session_state.done_915 else "待命")
col3.metric("12:30 午盤", "已執行" if st.session_state.done_1230 else "待命")

if auto_refresh:
    time.sleep(30)
    st.rerun()

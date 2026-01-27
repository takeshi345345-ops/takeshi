import streamlit as st
import pandas as pd
import twstock
import time
import datetime
import requests
import urllib3
from FinMind.data import DataLoader

# --- 🔥 暴力破解 SSL 憑證問題 (關鍵修正) ---
# 告訴 Python：不要檢查證交所的憑證，直接連線！
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
old_merge_environment_settings = requests.Session.merge_environment_settings

def merge_environment_settings(self, url, proxies, stream, verify, cert):
    # 強制將 verify 設定為 False (不檢查 SSL)
    if 'twse.com.tw' in url or 'mis.twse.com.tw' in url:
        verify = False
    return old_merge_environment_settings(self, url, proxies, stream, verify, cert)

requests.Session.merge_environment_settings = merge_environment_settings
# ---------------------------------------------

# --- 0. 頁面設定 ---
st.set_page_config(
    page_title="總柴台股快報 (暴力破解版)",
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
    .error-box { background: #550000; padding: 10px; border-radius: 5px; color: #ffcccc; margin-bottom: 10px; font-size: 0.8rem;}
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴台股快報：終極修復版")

# --- 1. Token ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

# --- 2. 資料庫 ---
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
    inv = st.text_area("代號", "2330, 2603")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    all_sectors = list(SECTOR_DB.keys())
    selected_sectors = st.multiselect("掃描族群", all_sectors, default=all_sectors)

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

def get_targets(user_port, sectors):
    target_codes = set(user_port)
    code_info = {p: {'name': f"庫存({p})", 'sector': '💼 我的庫存', 'is_inv': True} for p in user_port}
    for sec in sectors:
        for code, name in SECTOR_DB[sec].items():
            target_codes.add(code)
            if code not in code_info:
                code_info[code] = {'name': name, 'sector': sec, 'is_inv': False}
    return list(target_codes), code_info

# --- A. 備援方案：FinMind (修正版) ---
def scan_yesterday_finmind(target_codes, code_info):
    dl = DataLoader()
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
    results, buy_sigs, sell_sigs = [], [], []
    
    # 修正錯誤：不能用 date=... 抓全市場，改用迴圈抓個股
    bar = st.progress(0, text="🐕 啟動備援 FinMind (逐檔掃描)...")
    
    # 為了速度，我們只抓前 20 檔代表 (雲端資源有限)
    # 或是分批抓
    count = 0
    total = len(target_codes)
    
    for sid in target_codes:
        count += 1
        if count % 5 == 0: bar.progress(min(count/total, 0.9))
        
        try:
            # 正確寫法：指定 stock_id
            stock_data = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
            if stock_data.empty or len(stock_data) < 20: continue
            
            curr = stock_data.iloc[-1]
            prev = stock_data.iloc[-2]
            
            price = float(curr['close'])
            prev_price = float(prev['close'])
            
            # 簡單算 MA20
            stock_data['MA20'] = stock_data['close'].rolling(20).mean()
            ma20 = stock_data.iloc[-1]['MA20']
            
            pct = round(((price - prev_price)/prev_price)*100, 2)
            
            name = code_info.get(sid, {}).get('name', sid)
            is_inv = code_info.get(sid, {}).get('is_inv', False)
            sec = code_info.get(sid, {}).get('sector', '')
            
            msg = None
            signal = "昨收"
            if price > ma20 and pct > 2:
                msg = f"🔴 {name} ${price} (+{pct}%) 🔥昨轉強"
                buy_sigs.append({'msg': msg, 'is_inv': is_inv, 'sector': sec})
                signal = "🔥轉強"
            elif price < ma20 and pct < -2:
                msg = f"🟢 {name} ${price} ({pct}%) 📉昨破線"
                sell_sigs.append({'msg': msg, 'is_inv': is_inv, 'sector': sec})
                signal = "📉破線"
                
            results.append({'代號': sid, '名稱': name, '現價': price, '漲幅': pct, '訊號': signal})
            
        except Exception as e:
            pass # 跳過失敗的
            
    bar.empty()
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- B. 主要方案：Twstock 即時 (含 SSL 破解) ---
def scan_realtime(target_codes, code_info):
    results, buy_sigs, sell_sigs = [], [], []
    bar = st.progress(0, text="🐕 暴力連線證交所 (SSL已忽略)...")
    error_msg = None
    
    BATCH = 10
    has_success = False
    
    for i in range(0, len(target_codes), BATCH):
        batch = target_codes[i:i+BATCH]
        try:
            # twstock 會使用我們上面修改過的 requests，所以不會報 SSL 錯
            stocks = twstock.realtime.get(batch)
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        has_success = True
                        rt = data['realtime']
                        try:
                            price = float(rt['latest_trade_price'])
                        except:
                            try:
                                if rt.get('best_bid_price'): price = float(rt['best_bid_price'][0])
                                else: continue
                            except: continue
                            
                        if price == 0: continue
                        
                        try: prev = float(rt['previous_close'])
                        except: prev = price
                        
                        pct = round(((price-prev)/prev)*100, 2)
                        
                        name = code_info[sid]['name']
                        is_inv = code_info[sid]['is_inv']
                        sec = code_info[sid]['sector']
                        
                        signal = "觀望"
                        if pct > 2.5:
                            signal = "🔥攻擊"
                            buy_sigs.append({'msg': f"🔴 {name} ${price} (+{pct}%)", 'is_inv': is_inv, 'sector': sec})
                        elif pct < -2:
                            signal = "📉弱勢"
                            sell_sigs.append({'msg': f"🟢 {name} ${price} ({pct}%)", 'is_inv': is_inv, 'sector': sec})
                            
                        results.append({'代號': sid, '名稱': name, '現價': price, '漲幅': pct, '訊號': signal})
            
            bar.progress(min((i+BATCH)/len(target_codes), 0.9))
            time.sleep(1)
        except Exception as e:
            error_msg = str(e)
            
    bar.empty()
    
    if not has_success:
        if error_msg: st.markdown(f"<div class='error-box'>即時連線失敗: {error_msg}</div>", unsafe_allow_html=True)
        return None, [], []
        
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 主程式 ---
if st.button("🔍 立即手動更新", type="primary"):
    targets, info = get_targets(portfolio, selected_sectors)
    
    # 1. 嘗試即時 (已加強 SSL 通過率)
    df, buys, sells = scan_realtime(targets, info)
    
    # 2. 如果還是失敗，切換到修正後的 FinMind
    if df is None or df.empty:
        st.warning("⚠️ 即時連線受阻，切換至 [FinMind 昨日備援] 模式")
        df, buys, sells = scan_yesterday_finmind(targets, info)
        
    # 3. 顯示
    if not df.empty:
        st.success(f"掃描完成！共 {len(df)} 筆")
        
        if portfolio:
            st.subheader("💼 我的庫存")
            st.dataframe(df[df['代號'].isin(portfolio)], hide_index=True)
            
        st.subheader("市場掃描")
        col1, col2 = st.columns(2)
        with col1:
            st.caption("🔥 漲幅排行")
            st.dataframe(df.sort_values('漲幅', ascending=False).head(20), hide_index=True)
        with col2:
            st.caption("📉 跌幅排行")
            st.dataframe(df.sort_values('漲幅', ascending=True).head(20), hide_index=True)
            
        if (buys or sells) and LINE_TOKEN:
            msg = f"🐕 總柴測試發送\n"
            for b in buys[:3]: msg += f"{b['msg']}\n"
            send_line(msg)
            st.toast("測試通知已發送")
    else:
        st.error("❌ 所有資料來源皆無法使用，請稍後再試。")

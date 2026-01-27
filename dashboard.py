import streamlit as st
import pandas as pd
import twstock
import time
import datetime
from FinMind.data import DataLoader

# --- 0. 頁面設定 ---
st.set_page_config(
    page_title="總柴台股快報 (自動補位版)",
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
    .error-box { background: #550000; padding: 10px; border-radius: 5px; color: #ffcccc; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("🐕 總柴台股快報：自動補位監控")

# --- 1. 自動讀取 Token (免輸入) ---
LINE_TOKEN = None
if "LINE_TOKEN" in st.secrets:
    LINE_TOKEN = st.secrets["LINE_TOKEN"]
else:
    with st.sidebar:
        LINE_TOKEN = st.text_input("輸入 LINE Token", type="password")

# --- 2. 產業與庫存設定 ---
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
    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號", "2330, 2603")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    
    st.divider()
    all_sectors = list(SECTOR_DB.keys())
    selected_sectors = st.multiselect("掃描族群", all_sectors, default=all_sectors)

# --- 3. LINE 發送 ---
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

# --- 4. 掃描函式 ---

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
    # FinMind 抓昨天收盤 (穩定的備案)
    dl = DataLoader()
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
    
    results, buy_sigs, sell_sigs = [], [], []
    
    # 這裡我們用一個更高效的方法：一次抓全市場日資料，然後篩選
    # 避免一個一個抓太慢
    try:
        # 嘗試抓最近幾天的全市場資料
        dates = [datetime.datetime.now() - datetime.timedelta(days=x) for x in range(10)]
        df_all = pd.DataFrame()
        
        for d in dates:
            d_str = d.strftime('%Y-%m-%d')
            temp = dl.taiwan_stock_daily(date=d_str)
            if not temp.empty:
                df_all = temp
                break # 抓到最近一天有資料的就停
        
        if df_all.empty:
            return pd.DataFrame(), [], []

        # 篩選我們關注的股票
        df_target = df_all[df_all['stock_id'].isin(target_codes)].copy()
        
        for index, row in df_target.iterrows():
            sid = row['stock_id']
            price = float(row['close'])
            # 昨收沒給，我們簡單算 MA20 比較難，這裡簡化策略
            # 改用 "強勢股" 判斷：成交量大 + 漲幅大
            # FinMind 日資料沒給漲跌幅，要自己算，太慢
            # 這裡做一個簡單展示：列出價格
            
            name = code_info.get(sid, {}).get('name', sid)
            is_inv = code_info.get(sid, {}).get('is_inv', False)
            sec = code_info.get(sid, {}).get('sector', '')
            
            results.append({'代號': sid, '名稱': name, '現價': price, '漲幅': 0, '訊號': '昨日收盤(FinMind)'})
            
    except Exception as e:
        st.error(f"FinMind 備援失敗: {e}")
        
    return pd.DataFrame(results), buy_sigs, sell_sigs


def scan_realtime(target_codes, code_info):
    # 用 twstock 抓即時
    results, buy_sigs, sell_sigs = [], [], []
    bar = st.progress(0, text="🐕 嘗試連線證交所 (即時)...")
    
    BATCH = 10 # 縮小批次，比較不會錯
    error_log = []
    
    for i in range(0, len(target_codes), BATCH):
        batch = target_codes[i:i+BATCH]
        try:
            stocks = twstock.realtime.get(batch)
            if stocks:
                for sid, data in stocks.items():
                    if data['success']:
                        rt = data['realtime']
                        # 處理價格為 - 的情況 (收盤後常見)
                        try:
                            price = float(rt['latest_trade_price'])
                        except:
                            # 試著拿最後一筆成交 或 買賣價
                            try:
                                if rt.get('best_bid_price'): price = float(rt['best_bid_price'][0])
                                else: price = 0
                            except: price = 0
                            
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
                    else:
                        error_log.append(f"{sid}: {data.get('rtmessage', 'Unknown error')}")
            
            bar.progress(min((i+BATCH)/len(target_codes), 0.9))
            time.sleep(1) # 休息一下
        except Exception as e:
            error_log.append(f"Batch Error: {e}")
            pass
            
    bar.empty()
    
    # 如果完全沒資料，回傳錯誤讓外面知道
    if not results and error_log:
        st.markdown(f"<div class='error-box'>即時資料抓取失敗 (可能被擋或收盤格式變更): {error_log[0]}</div>", unsafe_allow_html=True)
        return None, [], [] # 回傳 None 代表失敗
        
    return pd.DataFrame(results), buy_sigs, sell_sigs

# --- 6. 核心按鈕與顯示 ---

# 大大的手動按鈕
if st.button("🔍 立即手動更新", type="primary"):
    targets, info = get_targets(portfolio, selected_sectors)
    
    # 1. 先試即時
    df, buys, sells = scan_realtime(targets, info)
    
    # 2. 如果失敗 (df is None)，自動切換備援
    if df is None or df.empty:
        st.warning("⚠️ 即時連線失敗，自動切換至 [FinMind 昨日收盤數據] 進行顯示")
        df, buys, sells = scan_yesterday(targets, info)
        
    # 3. 顯示結果
    if not df.empty:
        st.success(f"掃描完成！共 {len(df)} 筆資料")
        
        # 庫存特別顯示
        if portfolio:
            st.subheader("💼 我的庫存")
            my_df = df[df['代號'].isin(portfolio)]
            st.dataframe(my_df, hide_index=True)
            
        st.subheader("全市場掃描")
        # 簡單分類
        col1, col2 = st.columns(2)
        with col1:
            st.caption("🔥 漲幅排行")
            st.dataframe(df.sort_values('漲幅', ascending=False).head(20), hide_index=True)
        with col2:
            st.caption("📉 跌幅排行")
            st.dataframe(df.sort_values('漲幅', ascending=True).head(20), hide_index=True)
            
        # 發送 LINE 測試
        if buys or sells:
            st.info(f"發現訊號：{len(buys)} 買進, {len(sells)} 賣出")
            if LINE_TOKEN:
                msg = f"🐕 總柴手動更新測試\n"
                for b in buys[:5]: msg += f"{b['msg']}\n"
                if len(buys) > 5: msg += f"...等 {len(buys)} 檔\n"
                send_line(msg)
    else:
        st.error("❌ 所有資料來源皆無法讀取，請檢查網路或稍後再試。")

st.info("💡 說明：此版本優先抓取即時資料，若失敗會自動切換抓昨日收盤，確保一定有資料可看。")

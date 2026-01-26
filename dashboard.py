import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from FinMind.data import DataLoader
import requests
import json
import datetime

# --- 0. 頁面設定 ---
st.set_page_config(
    page_title="總柴台股快報 (庫存優先版)",
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

# --- 標題已更改為柴犬 ---
st.title("🐕 總柴台股快報：庫存優先監控")

# --- 1. 初始化 Session State ---
if 'daily_notify_count' not in st.session_state:
    st.session_state.daily_notify_count = 0
if 'last_notify_time' not in st.session_state:
    st.session_state.last_notify_time = None
if 'last_notify_date' not in st.session_state:
    st.session_state.last_notify_date = datetime.date.today()

if st.session_state.last_notify_date != datetime.date.today():
    st.session_state.daily_notify_count = 0
    st.session_state.last_notify_time = None
    st.session_state.last_notify_date = datetime.date.today()

# --- 2. 內建核心資料庫 (850+ 檔) ---
SECTOR_DB = {
    "🔥 半導體": {'2330':'台積電','2454':'聯發科','2303':'聯電','3711':'日月光','3034':'聯詠','2379':'瑞昱','3443':'創意','3661':'世芯-KY','3035':'智原','3529':'力旺','6531':'愛普','3189':'景碩','8046':'南電','3037':'欣興','8299':'群聯','3260':'威剛','2408':'南亞科','4966':'譜瑞','6104':'創惟','6415':'矽力','6756':'威鋒','2344':'華邦電','2337':'旺宏','6271':'同欣電','5269':'祥碩','8016':'矽創','8131':'福懋科'},
    "🤖 AI與電腦": {'2382':'廣達','3231':'緯創','2356':'英業達','6669':'緯穎','2376':'技嘉','2357':'華碩','2324':'仁寶','2301':'光寶科','3017':'奇鋐','3324':'雙鴻','2421':'建準','3653':'健策','3483':'力致','8996':'高力','2368':'金像電','6274':'台燿','6213':'聯茂','2395':'研華','6414':'樺漢'},
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

# --- 3. LINE 通知功能 ---
def send_line_broadcast(access_token, text_msg):
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    payload = {"messages": [{"type": "text", "text": text_msg}]}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload))
        return r.status_code == 200, r.status_code, r.text
    except Exception as e:
        return False, 0, str(e)

# --- 4. 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 設定")
    if st.button("🔄 刷新數據"): st.cache_data.clear()
    
    st.divider()
    st.subheader("🤖 LINE 設定")
    line_token = st.text_input("Channel Access Token", type="password")
    
    col_auto, col_force = st.columns(2)
    with col_auto:
        enable_notify = st.checkbox("自動排程 (開盤3次)", value=True)
    
    force_send_clicked = st.button("🔥 強制發送快報", type="primary")
    if force_send_clicked and not line_token:
        st.error("請先輸入 Token！")

    st.divider()
    st.subheader("庫存")
    inv = st.text_area("代號 (逗號分隔)", "2330, 2603")
    portfolio = [x.strip() for x in inv.split(",") if x.strip()]
    
    st.divider()
    all_sectors = list(SECTOR_DB.keys())
    selected_sectors = st.multiselect("掃描族群", all_sectors, default=all_sectors)

# --- 5. 核心掃描 ---
@st.cache_data(ttl=60, show_spinner=False)
def scan_all_sectors(sectors_to_scan, user_portfolio):
    code_map = {}
    sector_map = {}
    
    # 建立對照表
    for p in user_portfolio:
        if p:
            code_map[p], sector_map[p] = f"庫存({p})", "💼 我的庫存"
    for sec in sectors_to_scan:
        for code, name in SECTOR_DB[sec].items():
            code_map[code], sector_map[code] = name, sec
            
    target_list = list(code_map.keys())
    tw_tickers = [f"{x}.TW" for x in target_list]
    
    try: data_tw = yf.download(tw_tickers, period="1mo", group_by='ticker', progress=False)
    except: data_tw = pd.DataFrame()
        
    results = []
    buy_signals = [] 
    sell_signals = []
    failed_codes = []
    
    def analyze(df, sid, name, sector):
        try:
            df = df.dropna(subset=['Close'])
            if len(df) < 20: return None
            df['MA20'] = df['Close'].rolling(20).mean()
            
            curr = df.iloc[-1]
            prev = df.iloc[-2]
            price = float(curr['Close'])
            ma20 = float(curr['MA20'])
            pct = round(((price - float(prev['Close'])) / float(prev['Close'])) * 100, 2)
            vol = int(curr['Volume'])
            vol_avg = float(df['Volume'].tail(5).mean())
            vol_ratio = round(vol / vol_avg, 1) if vol_avg > 0 else 0
            bias = ((price - ma20) / ma20) * 100
            
            signal, code = "🛡️ 觀望", 0
            pct_fmt = f"+{pct}%" if pct > 0 else f"{pct}%"
            
            # 判斷是否為庫存
            is_inv = sid in user_portfolio
            
            # --- 訊號邏輯 ---
            if price > ma20:
                if vol_ratio < 0.8 and pct > -3 and abs(bias) < 4:
                    signal, code = "👍 推薦買進 (量縮回測)", 10
                    # 庫存特別標註
                    prefix = "🔴 [加碼]" if is_inv else "🔴"
                    item = {
                        'sector': sector,
                        'is_inv': is_inv,
                        'msg': f"{prefix} {name}({sid}) ${price} ({pct_fmt})\n   └ 量縮回測 (量比{vol_ratio})"
                    }
                    buy_signals.append(item)
                    
                elif vol_ratio > 1.5 and pct > 2:
                    signal, code = "👍 推薦買進 (帶量攻擊)", 10
                    prefix = "🔴 [加碼]" if is_inv else "🔴"
                    item = {
                        'sector': sector,
                        'is_inv': is_inv,
                        'msg': f"{prefix} {name}({sid}) ${price} ({pct_fmt})\n   └ 🔥爆量攻擊 (量比{vol_ratio})"
                    }
                    buy_signals.append(item)
                else:
                    signal, code = "👀 多頭觀察", 2
            else:
                if pct < 0:
                    signal, code = "👎 推薦賣出 (破線)", -10
                    prefix = "🟢 [減碼]" if is_inv else "🟢"
                    item = {
                        'sector': sector,
                        'is_inv': is_inv,
                        'msg': f"{prefix} {name}({sid}) ${price} ({pct_fmt})\n   └ 📉破線轉弱"
                    }
                    sell_signals.append(item)
                else:
                    signal, code = "❄️ 反彈無力", -1
            
            return {
                "代號": sid, "名稱": name, "族群": sector, "現價": price, "漲幅": pct, 
                "量比": vol_ratio, "訊號": signal, "code": code, "MA20": round(ma20, 2)
            }
        except: return None

    # 第一輪
    for sid in target_list:
        ticker = f"{sid}.TW"
        df = pd.DataFrame()
        if len(tw_tickers)==1 and not data_tw.empty: df = data_tw
        elif ticker in data_tw: df = data_tw[ticker]
        
        if df.empty or 'Close' not in df.columns or df['Close'].isna().all(): failed_codes.append(sid)
        else:
            res = analyze(df, sid, code_map[sid], sector_map[sid])
            if res: results.append(res)
            
    # 第二輪
    if failed_codes:
        two_tickers = [f"{x}.TWO" for x in failed_codes]
        try:
            data_two = yf.download(two_tickers, period="1mo", group_by='ticker', progress=False)
            for sid in failed_codes:
                ticker = f"{sid}.TWO"
                df = pd.DataFrame()
                if len(two_tickers)==1 and not data_two.empty: df = data_two
                elif ticker in data_two: df = data_two[ticker]
                
                if not df.empty and 'Close' in df.columns and not df['Close'].isna().all():
                    res = analyze(df, sid, code_map[sid], sector_map[sid])
                    if res: results.append(res)
        except: pass
        
    return pd.DataFrame(results), buy_signals, sell_signals

# --- 6. 執行掃描 ---
# --- 載入動畫文字也更改為柴犬 ---
with st.spinner("🐕 總柴正在幫你掃描全產業..."):
    df, buy_list, sell_list = scan_all_sectors(selected_sectors, portfolio)

# --- 7. 發送邏輯 (庫存優先 + 族群分類) ---

def build_grouped_message(data_list, title):
    if not data_list: return ""
    
    # 依照族群分組
    grouped = {}
    for item in data_list:
        # 如果是庫存，不加入一般族群分組 (避免重複顯示在下方)
        if item['is_inv']: continue 
        
        sec = item['sector']
        if sec not in grouped: grouped[sec] = []
        grouped[sec].append(item['msg'])
        
    msg = f"\n{title} (共{len(data_list)}檔)\n"
    
    for sec, items in grouped.items():
        msg += f"\n[{sec}]\n"
        msg += "\n".join(items) + "\n"
        
    return msg

def build_full_notify():
    # 1. 提取庫存訊號
    my_inv_msgs = []
    
    # 從買進清單找庫存
    for item in buy_list:
        if item['is_inv']: my_inv_msgs.append(item['msg'])
        
    # 從賣出清單找庫存
    for item in sell_list:
        if item['is_inv']: my_inv_msgs.append(item['msg'])
        
    now_str = datetime.datetime.now().strftime('%H:%M')
    # --- LINE 通知標題更改為柴犬 ---
    final_msg = f"🐕 總柴台股快報 | {now_str}\n==================\n"
    
    # A. 庫存區塊 (最優先)
    if my_inv_msgs:
        final_msg += "\n【💼 庫存關鍵快報】\n"
        final_msg += "\n".join(my_inv_msgs) + "\n"
        final_msg += "-"*20 + "\n" # 分隔線
        
    # B. 市場買進區塊 (依照族群)
    if buy_list:
        final_msg += build_grouped_message(buy_list, "【👍 市場推薦買進】")
        
    # C. 市場賣出區塊 (依照族群)
    if sell_list:
        final_msg += build_grouped_message(sell_list, "【👎 市場推薦賣出】")
        
    return final_msg

# 檢查是否發送
if line_token and (buy_list or sell_list):
    
    msg_to_send = build_full_notify()
    
    # A. 強制發送
    if force_send_clicked:
        msg_to_send = "🔴 [強制發送] " + msg_to_send
        success, code, err = send_line_broadcast(line_token, msg_to_send)
        if success: st.toast("✅ 強制發送成功！", icon="🚀")
        else: st.error(f"發送失敗: {err}")

    # B. 自動排程
    elif enable_notify:
        now = datetime.datetime.now()
        start = now.replace(hour=8, minute=45, second=0, microsecond=0)
        end = now.replace(hour=13, minute=30, second=0, microsecond=0)
        
        should_send = False
        if start <= now <= end:
            if st.session_state.daily_notify_count < 3:
                time_diff = 999
                if st.session_state.last_notify_time:
                    time_diff = (now - st.session_state.last_notify_time).total_seconds() / 60
                
                if st.session_state.last_notify_time is None or time_diff >= 90:
                    should_send = True
        
        if should_send:
            success, code, err = send_line_broadcast(line_token, msg_to_send)
            if success:
                st.session_state.daily_notify_count += 1
                st.session_state.last_notify_time = now
                st.toast(f"✅ 自動通知已發送")

# --- 狀態顯示 ---
next_msg = "隨時可發"
if st.session_state.last_notify_time:
    next_run = st.session_state.last_notify_time + datetime.timedelta(minutes=90)
    next_msg = f"冷卻中 (預計 {next_run.strftime('%H:%M')})"
    
st.markdown(f"""
<div class="notify-status">
    🔔 自動排程: {st.session_state.daily_notify_count}/3 次 | {next_msg}
</div>
""", unsafe_allow_html=True)

# --- 8. 介面呈現 ---

if df.empty:
    st.error("無法取得數據，請檢查網路。")
else:
    if portfolio:
        with st.expander("💼 我的庫存", expanded=True):
            my_df = df[df['代號'].isin(portfolio)]
            if not my_df.empty:
                for row in my_df.itertuples():
                    cls = "card-buy" if row.code==10 else "card-sell" if row.code==-10 else "card-wait"
                    color = "#FF4444" if row.漲幅 > 0 else "#00FF00"
                    st.markdown(f"""
                    <div class="stock-card {cls}">
                        <div class="ticker">{row.名稱} ({row.代號}) <span class="sector-tag">{row.族群}</span></div>
                        <div class="info">
                            {row.訊號} | 價: {row.現價} (<span style="color:{color}">{row.漲幅}%</span>) | 量比: {row.量比}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

    # --- 副標題更改為柴犬 ---
    st.subheader(f"🐕 總柴全產業訊號 ({len(df)} 檔)")
    t1, t2, t3, t4 = st.tabs(["👍 推薦買進", "👎 推薦賣出", "🔥 資金排行", "全部"])
    cols = ['名稱', '族群', '現價', '漲幅', '量比', '訊號']
    
    with t1:
        st.caption("條件：**股價 > 20MA** 且 (**量縮回測** 或 **帶量攻擊**)")
        d1 = df[df['code'] == 10].sort_values('量比', ascending=True)
        st.dataframe(d1, column_order=cols, use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun", key="t1")
    with t2:
        st.caption("條件：**跌破 20MA**")
        d2 = df[df['code'] <= -1].sort_values('漲幅', ascending=True)
        st.dataframe(d2, column_order=cols, use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun", key="t2")
    with t3:
        d3 = df.sort_values('現價', ascending=False)
        st.dataframe(d3, column_order=cols, use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun", key="t3")
    with t4:
        st.dataframe(df, column_order=cols, use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun", key="t4")

    sel = None
    if st.session_state.t1.selection.rows: sel = d1.iloc[st.session_state.t1.selection.rows[0]]
    elif st.session_state.t2.selection.rows: sel = d2.iloc[st.session_state.t2.selection.rows[0]]
    elif st.session_state.t3.selection.rows: sel = d3.iloc[st.session_state.t3.selection.rows[0]]
    elif st.session_state.t4.selection.rows: sel = df.iloc[st.session_state.t4.selection.rows[0]]
    
    if sel is not None:
        sid = sel['代號']
        name = sel['名稱']
        st.divider()
        st.markdown(f"### 📈 {name} ({sid})")
        
        try:
            chart_df = yf.download(f"{sid}.TW", period="9mo", progress=False)
            if chart_df.empty: chart_df = yf.download(f"{sid}.TWO", period="9mo", progress=False)
            if isinstance(chart_df.columns, pd.MultiIndex): chart_df.columns = chart_df.columns.get_level_values(0)
            
            chart_df['MA5'] = chart_df['Close'].rolling(5).mean()
            chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
            
            dl = DataLoader()
            short_data = dl.taiwan_stock_margin_purchase_short_sale(
                stock_id=sid, start_date=(pd.Timestamp.now()-pd.Timedelta(days=120)).strftime('%Y-%m-%d')
            )
            
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.2, 0.3],
                                subplot_titles=("K線 (橘=20MA)", "成交量", "融券(紅) vs 借券(黃)"))
            
            fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA5'], name='5MA', line=dict(color='white', width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], name='20MA', line=dict(color='orange', width=2)), row=1, col=1)
            
            colors = ['red' if o < c else 'green' for o, c in zip(chart_df['Open'], chart_df['Close'])]
            fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], name='量', marker_color=colors), row=2, col=1)
            
            if not short_data.empty:
                val_m = short_data.get('ShortSaleBalance', short_data.iloc[:, -2] if len(short_data.columns)>2 else None)
                if val_m is not None: fig.add_trace(go.Scatter(x=short_data['date'], y=val_m, name='融券', line=dict(color='red', width=2)), row=3, col=1)
            
            fig.update_layout(template="plotly_dark", height=700, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
        except: st.error("圖表載入失敗")
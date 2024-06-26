import openai
import streamlit as st
import sqlite3
import pandas as pd
import folium
from streamlit_folium import st_folium
import wikipedia
import requests
import urllib.parse
import time
import os

# 設定 API 金鑰
openai_api_key = os.getenv('OPENAI_API_KEY')
opencage_api_key = os.getenv('OPENCAGE_API_KEY')

if not openai_api_key or not opencage_api_key:
    st.error("請設定您的 OpenAI 和 OpenCage API 金鑰")
else:
    openai.api_key = openai_api_key
    geocoder = OpenCageGeocode(opencage_api_key)

# 連接到 SQLite 資料庫
conn = sqlite3.connect('account.db')
c = conn.cursor()

# 創建或修改 users 表格
c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        usage INTEGER NOT NULL DEFAULT 0,
        payment_done BOOLEAN NOT NULL DEFAULT 0
    )
''')

conn.commit()

def add_user(username, password):
    try:
        c.execute("INSERT INTO users (username, password, usage, payment_done) VALUES (?, ?, 0, 0)", (username, password))
        conn.commit()
        st.success("用戶添加成功！")
    except sqlite3.IntegrityError:
        st.error("用戶名已存在！")

def authenticate_user(username, password):
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
    user = c.fetchone()
    return user

def display_users():
    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    if rows:
        df = pd.DataFrame(rows, columns=["ID", "Username", "Password", "Usage", "Payment Done"])
        st.dataframe(df)
    else:
        st.write("沒有用戶資料。")

def update_user(user_id, new_username, new_password):
    try:
        c.execute("UPDATE users SET username = ?, password = ? WHERE id = ?", (new_username, new_password, user_id))
        conn.commit()
        st.success("用戶更新成功！")
    except sqlite3.IntegrityError:
        st.error("用戶名已存在！")

def delete_user(user_id):
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    st.success("用戶刪除成功！")

def increment_usage(user_id):
    c.execute("UPDATE users SET usage = usage + 1 WHERE id = ? AND payment_done = 0", (user_id,))
    conn.commit()

def get_usage(user_id):
    c.execute("SELECT usage FROM users WHERE id = ?", (user_id,))
    usage = c.fetchone()[0]
    return usage

def reset_usage(user_id):
    c.execute("UPDATE users SET usage = 0 WHERE id = ?", (user_id,))
    conn.commit()

def set_payment_done(user_id):
    c.execute("UPDATE users SET payment_done = 1 WHERE id = ?", (user_id,))
    conn.commit()

def get_payment_status(user_id):
    c.execute("SELECT payment_done FROM users WHERE id = ?", (user_id,))
    payment_done = c.fetchone()[0]
    return payment_done

# 設定頁面狀態
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if 'current_user_id' not in st.session_state:
    st.session_state.current_user_id = None

if 'payment_made' not in st.session_state:
    st.session_state.payment_made = False

if 'input_count' not in st.session_state:
    st.session_state.input_count = 0

def get_location(address, retries=3, delay=2):
    url = f"https://api.opencagedata.com/geocode/v1/json?q={urllib.parse.quote(address)}&key={opencage_api_key}"
    for _ in range(retries):
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['results']:
                location = data['results'][0]['geometry']
                return location['lat'], location['lng']
        time.sleep(delay)
    return None

def create_map(lat, lon, location_input):
    map_obj = folium.Map(location=[lat, lon], zoom_start=15)
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(map_obj)
    folium.Marker([lat, lon], popup=location_input).add_to(map_obj)
    
    # 使用 Overpass API 來獲取附近的著名景點
    overpass_url = "http://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json];
    node(around:1000,{lat},{lon})["tourism"];
    out body;
    """
    response = requests.get(overpass_url, params={'data': overpass_query})
    data = response.json()

    for element in data['elements']:
        if 'tags' in element and 'name' in element['tags']:
            place_lat = element['lat']
            place_lon = element['lon']
            name = element['tags']['name']
            search_url = f"https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(name)}&utf8=&format=json"
            search_response = requests.get(search_url).json()
            if search_response['query']['search']:
                page_id = search_response['query']['search'][0]['pageid']
                page_url = f"https://zh.wikipedia.org/?curid={page_id}"
            else:
                page_url = f"https://zh.wikipedia.org/wiki/{urllib.parse.quote(name)}"

            folium.Marker(
                location=[place_lat, place_lon],
                tooltip=name,
                popup=folium.Popup(f"<b>{name}</b><br>經緯度: ({place_lat}, {place_lon})<br><a href='{page_url}' target='_blank'>查看更多</a>", max_width=300)
            ).add_to(map_obj)
    
    return map_obj

def show_map():
    # 地圖功能頁面
    st.title("地圖")

    # 使用者輸入提示
    user_input = st.text_input("請輸入您的提示")

    if st.button("送出提示"):
        st.session_state.input_count += 1
        increment_usage(st.session_state.current_user_id)
    
    if st.session_state.input_count > 2:
        return

    if user_input:
        # 呼叫 OpenAI API 並顯示回應
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一個地理助手"},
                {"role": "user", "content": user_input}
            ]
        )

        # 輸出生成的文本
        answer = response['choices'][0]['message']['content'].strip()
        st.write("回答：")
        st.write(answer)

        # 提取地名
        def extract_location(text):
            # 使用 OpenAI API 來提取地名
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "你是一個地理位置提取助手"},
                    {"role": "user", "content": f"從以下句子中提取地點：{text}"}
                ]
            )
            location = response['choices'][0]['message']['content'].strip()
            # 移除不需要的字串
            location = location.replace("地點提取：", "").replace("。", "").strip()
            return location

        location_input = extract_location(user_input)

        # 顯示地理關鍵字
        st.write(f"{location_input}")

        # 地理編碼
        location = get_location(location_input)
        if location:
            lat, lon = location
            st.success(f"找到位置：{lat}, {lon}")
            map_obj = create_map(lat, lon, location_input)
            st_folium(map_obj, width=700, height=500)
            
            # 顯示維基百科的地理和歷史摘要
            def get_wikipedia_summary(location):
                wikipedia.set_lang('zh')
                try:
                    page = wikipedia.page(location)
                    summary = page.content
                    geo_index = summary.find("地理")
                    history_index = summary.find("歷史")

                    geo_summary = summary[geo_index:summary.find("==", geo_index)]
                    history_summary = summary[history_index:summary.find("==", history_index)]

                    return geo_summary, history_summary
                except wikipedia.exceptions.DisambiguationError as e:
                    return "有多個條目與此名稱匹配，請更具體輸入名稱。", ""
                except wikipedia.exceptions.PageError:
                    return "無法找到該地點的維基百科條目。", ""
                except Exception as e:
                    return "查詢維基百科時出錯。", ""

            geo_summary, history_summary = get_wikipedia_summary(location_input)

            st.sidebar.header(f"{location_input} 的歷史資訊")
            st.sidebar.write(history_summary)
        else:
            st.error("無法找到該地址的地理位置")

if not st.session_state.logged_in:
    # 主功能
    st.title("用戶管理系統")

    # 選擇功能
    option = st.sidebar.selectbox(
        '選擇功能',
        ('登入', '註冊', '用戶管理')
    )

    # 登入功能
    if option == '登入':
        st.header("登入")
        login_username = st.text_input("用戶名", key="login_username")
        login_password = st.text_input("密碼", type="password", key="login_password")

        if st.button("登入", key="login_button"):
            user = authenticate_user(login_username, login_password)
            if user:
                st.success("登入成功！")
                st.session_state.logged_in = True
                st.session_state.current_user_id = user[0]
                st.session_state.username = login_username
                st.session_state.payment_made = user[4]
                st.experimental_rerun()
            else:
                st.error("用戶名或密碼錯誤！")

    # 註冊功能
    elif option == '註冊':
        st.header("註冊")
        register_username = st.text_input("新用戶名", key="register_username")
        register_password = st.text_input("新密碼", type="password", key="register_password")

        if st.button("註冊", key="register_button"):
            add_user(register_username, register_password)

    # 用戶管理功能
    elif option == '用戶管理':
        st.header("用戶管理")
        display_users()

        user_id = st.number_input("用戶ID", min_value=1, step=1, key="update_user_id")
        new_username = st.text_input("新用戶名", key="update_username")
        new_password = st.text_input("新密碼", type="password", key="update_password")

        if st.button("更新", key="update_button"):
            update_user(user_id, new_username, new_password)

        if st.button("刪除", key="delete_button"):
            delete_user(user_id)

else:
    # 根據使用次數決定是否顯示地圖或付款頁面
    usage = get_usage(st.session_state.current_user_id)
    payment_done = get_payment_status(st.session_state.current_user_id)

    if (usage > 2 or st.session_state.input_count > 2) and not st.session_state.payment_made and not payment_done:
        st.title("免費次數已用完")
        st.write("請付款以繼續使用此服務。")
        if st.button("信用卡付款"):
            st.session_state.payment_made = True
            st.experimental_rerun()
    elif st.session_state.payment_made:
        st.title("信用卡付款頁面")
        username = st.text_input("使用者名稱", value=st.session_state.username)
        card_number = st.text_input("信用卡卡號", max_chars=16)
        amount = st.number_input("付款金額", min_value=0.0, format="%.2f")
        security_code = st.text_input("信用卡安全碼", max_chars=3)

        if st.button("提交付款"):
            if username == st.session_state.username:
                if len(card_number) == 16 and len(security_code) == 3:
                    set_payment_done(st.session_state.current_user_id)
                    st.success("付款成功！")
                    st.session_state.payment_made = True
                    st.experimental_rerun()
                else:
                    st.error("信用卡資訊無效！")
            else:
                st.error("使用者名稱錯誤！")
    else:
        show_map()

        # 登出按鈕
        if st.button("登出"):
            st.session_state.logged_in = False
            st.session_state.current_user_id = None
            st.session_state.username = ""
            st.session_state.input_count = 0
            st.experimental_rerun()

conn.close()

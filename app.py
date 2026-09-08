import streamlit as st
import pandas as pd
import pdfplumber
import re
import requests
import folium
from streamlit_folium import st_folium
import time

# ตั้งค่าคอนฟิกของหน้า Streamlit
st.set_page_config(
    page_title="การตรวจสอบเส้นทางการจัดส่ง",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 โปรเจกต์: การตรวจสอบเส้นทางการจัดส่ง")
st.markdown("ระบบวิเคราะห์รายงานการส่งสินค้า คำนวณเที่ยววิ่ง และจำลองเส้นทางบนถนนจริง (OSRM Routing)")

# --- SIDEBAR: การตั้งค่าพิกัดคลัง และความเร็ว ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")
wh_lat = st.sidebar.number_input("Latitude คลังสินค้า", value=13.66800, format="%.5f")
wh_lng = st.sidebar.number_input("Longitude คลังสินค้า", value=100.61000, format="%.5f")
warehouse_coord = (wh_lat, wh_lng)

st.sidebar.header("🎬 การตั้งค่าการจำลอง (Simulation)")
play_mode = st.sidebar.radio(
    "รูปแบบการแสดงผลบนแผนที่:",
    (
        "แบบที่ 1: แสดงหมุดครบทั้งหมดก่อน (เส้นทางค่อยๆ วิ่ง)",
        "แบบที่ 2: ปรากฏหมุดและเส้นทางทีละจุดตามลำดับเวลา"
    )
)

anim_speed = st.sidebar.slider("ความเร็วในการเล่น (วินาที/Step)", min_value=0.1, max_value=2.0, value=0.5, step=0.1)


# --- FUNCTION: ดึงเส้นทางบนถนนจริงจาก OSRM ---
@st.cache_data(show_spinner=False)
def get_osrm_route(p1_lat, p1_lng, p2_lat, p2_lng):
    """
    เรียกใช้งาน OSRM API เพื่อหาเส้นทางบนถนนจริงสำหรับรถยนต์
    ระหว่างพิกัด p1 และ p2
    """
    url = f"http://router.project-osrm.org/route/v1/driving/{p1_lng},{p1_lat};{p2_lng},{p2_lat}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("routes"):
                coords = data["routes"][0]["geometry"]["coordinates"]
                route_latlon = [[pt[1], pt[0]] for pt in coords]
                return route_latlon
    except Exception:
        pass
    return [[p1_lat, p1_lng], [p2_lat, p2_lng]]


# --- FUNCTION: ดึงข้อมูลจากไฟล์ PDF ---
def parse_pdf_data(pdf_file):
    header_info = {
        "date": "ไม่ระบุ",
        "truck_no": "ไม่ระบุ",
        "driver": "ไม่ระบุ"
    }
    
    dw_net = {}
    records = []

    with pdfplumber.open(pdf_file) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            lines = text.split('\n')
            for line in lines:
                if "ประจําวัน" in line and header_info["date"] == "ไม่ระบุ":
                    date_match = re.search(r'ประจําวัน\s*([\d/]+)', line)
                    if date_match:
                        header_info["date"] = date_match.group(1)
                    
                    truck_match = re.search(r'รถส่ง\s*(\w+)', line)
                    if truck_match:
                        header_info["truck_no"] = truck_match.group(1)

                if "พนักงานขับรถ" in line and header_info["driver"] == "ไม่ระบุ":
                    driver_match = re.search(r'พนักงานขับรถ\s*(.*)', line)
                    if driver_match:
                        header_info["driver"] = driver_match.group(1).strip()

                dw_match = re.search(r'DW\w+/(\d{3})\s+(\d+)', line)
                if dw_match:
                    trip_no = int(dw_match.group(1))
                    qty = int(dw_match.group(2))
                    dw_net[trip_no] = dw_net.get(trip_no, 0) + qty

                re_match = re.search(r'RE\w+/(\d{3})\s+(\d+)', line)
                if re_match:
                    trip_no = int(re_match.group(1))
                    qty = int(re_match.group(2))
                    dw_net[trip_no] = dw_net.get(trip_no, 0) - qty

                gps_match = re.search(r'(\d{1,2}\.\d+),(\d{1,3}\.\d+)', line)
                time_match = re.search(r'(\d{2}:\d{2})\s*น\.', line)

                if gps_match and time_match:
                    lat = float(gps_match.group(1))
                    lng = float(gps_match.group(2))
                    delivery_time = time_match.group(1)

                    cust_id_match = re.search(r'^([\d/]+)\s+', line.strip())
                    cust_id = cust_id_match.group(1) if cust_id_match else "N/A"

                    status = "จัดส่งตรงเวลา"
                    if "จัดส่งไม่ตรงเวลา" in line or "ไม่ตรงเวลา" in line:
                        status = "จัดส่งไม่ตรงเวลา"
                    elif "สมาชิกใหม่" in line:
                        status = "สมาชิกใหม่"
                    elif "รอบเสริม" in line:
                        status = "รอบเสริม"
                    elif "ย้ายรอบ" in line:
                        status = "ย้ายรอบ"

                    tokens = line.strip().split()
                    cust_name = "ไม่ระบุ"
                    qty_sent = 1

                    for idx, t in enumerate(tokens):
                        if "," in t and ("13." in t or "14." in t):
                            if idx >= 2 and tokens[idx-2].isdigit():
                                qty_sent = int(tokens[idx-2])
                            
                            if len(tokens) > 2:
                                name_tokens = []
                                for name_t in tokens[1:idx-2]:
                                    if not name_t.isdigit():
                                        name_tokens.append(name_t)
                                if name_tokens:
                                    cust_name = " ".join(name_tokens)
                            break

                    records.append({
                        "cust_id": cust_id,
                        "cust_name": cust_name,
                        "lat": lat,
                        "lng": lng,
                        "time": delivery_time,
                        "qty": qty_sent,
                        "status": status
                    })

    df = pd.DataFrame(records)

    if not df.empty:
        df = df.sort_values(by="time").reset_index(drop=True)

        trips = []
        acc_qty_list = []
        
        current_trip = 1
        current_trip_acc = 0
        total_acc = 0

        max_trip_qty = dw_net.get(current_trip, 80)

        for idx, row in df.iterrows():
            qty = row['qty']
            
            if current_trip_acc + qty > max_trip_qty and current_trip_acc > 0:
                current_trip += 1
                current_trip_acc = 0
                max_trip_qty = dw_net.get(current_trip, 80)

            current_trip_acc += qty
            total_acc += qty

            trips.append(f"เที่ยวที่ {current_trip}")
            acc_qty_list.append(total_acc)

        df['trip'] = trips
        df['acc_qty'] = acc_qty_list

    return df, dw_net, header_info


# --- MAIN INTERFACE ---
uploaded_file = st.file_uploader("📂 กรุณาอัปโหลดไฟล์รายงานการส่งสินค้า (PDF)", type=["pdf"])

if uploaded_file:
    with st.spinner("กำลังอ่านและประมวลผลข้อมูลจาก PDF..."):
        df, dw_net, header_info = parse_pdf_data(uploaded_file)

    if df.empty:
        st.error("❌ ไม่พบข้อมูลพิกัด GPS หรือรายการจัดส่งในไฟล์ PDF นี้")
    else:
        st.success("✅ ประมวลผลข้อมูลสำเร็จ!")

        # --- ส่วนแสดง HEADER ข้อมูลประจำวัน ---
        st.subheader("📌 ข้อมูลปฏิบัติงานประจำวัน")
        h_col1, h_col2, h_col3 = st.columns(3)
        h_col1.info(f"📅 **งานประจำวันที่:** {header_info['date']}")
        h_col2.info(f"🚛 **รถส่ง:** {header_info['truck_no']}")
        h_col3.info(f"👨‍✈️ **พนักงานขับรถ:** {header_info['driver']}")

        # --- ตารางแสดงรายการจัดส่ง ---
        st.subheader("📋 ตารางรายการจัดส่งสินค้า (เรียงตามลำดับเวลา)")
        
        display_df = df[[
            'time', 'trip', 'cust_id', 'cust_name', 
            'qty', 'acc_qty', 'status', 'lat', 'lng'
        ]].copy()

        display_df.columns = [
            'เวลาส่ง', 'เที่ยวส่ง', 'รหัสลูกค้า', 'ชื่อลูกค้า', 
            'ยอดส่ง (ใบ/ถัง)', 'ยอดส่งสะสม', 'สถานะการส่ง', 'Latitude', 'Longitude'
        ]

        st.dataframe(display_df, use_container_width=True, height=280)

        # --- สรุปยอดส่งแต่ละเที่ยว ---
        st.subheader("📊 รายงานสรุปยอดส่งแบ่งตามเที่ยว (Trip Summary)")
        
        trip_summaries = []
        for trip_name, group in df.groupby('trip', sort=False):
            trip_num = int(trip_name.replace("เที่ยวที่ ", ""))
            net_withdraw = dw_net.get(trip_num, "N/A")
            total_sent = group['qty'].sum()
            ontime_count = len(group[group['status'] == 'จัดส่งตรงเวลา'])
            late_count = len(group[group['status'] != 'จัดส่งตรงเวลา'])

            trip_summaries.append({
                "เที่ยวการส่ง": trip_name,
                "ยอดเบิกสุทธิ (DW-RE)": net_withdraw,
                "ยอดจัดส่งจริงสุทธิ": total_sent,
                "จำนวนจุดส่งทั้งหมด": len(group),
                "จัดส่งตรงเวลา (จุด)": ontime_count,
                "จัดส่งไม่ตรงเวลา/อื่นๆ (จุด)": late_count,
                "หมายเหตุ": "วิ่งออกจากคลัง -> ส่งสินค้า -> วิ่งกลับคลัง"
            })

        summary_df = pd.DataFrame(trip_summaries)
        st.table(summary_df)

        # แก้ไขบรรทัดนี้จาก st.hr() เป็น st.divider()
        st.divider()

        # --- MAP VISUALIZATION & SIMULATION ---
        st.subheader("🗺️ แผนที่และระบบจำลองการวิ่งจัดส่ง (Road Routing Animation)")

        trip_colors = {
            "เที่ยวที่ 1": "blue",
            "เที่ยวที่ 2": "green",
            "เที่ยวที่ 3": "orange",
            "เที่ยวที่ 4": "purple",
            "เที่ยวที่ 5": "red"
        }

        with st.spinner("กำลังคำนวณเส้นทางบนถนนจริงจาก OSRM (อาจใช้เวลาสักครู่)..."):
            segments = []
            grouped = df.groupby('trip', sort=False)
            
            for trip_name, group in grouped:
                pts = [warehouse_coord] + list(zip(group['lat'], group['lng'])) + [warehouse_coord]
                group_records = group.to_dict('records')

                for i in range(len(pts) - 1):
                    p1 = pts[i]
                    p2 = pts[i+1]
                    
                    route_path = get_osrm_route(p1[0], p1[1], p2[0], p2[1])
                    
                    if i < len(group_records):
                        target_info = group_records[i]
                    else:
                        target_info = {"cust_name": "คลังสินค้า", "status": "กลับคลัง", "qty": 0, "time": "จบเที่ยว"}

                    segments.append({
                        "trip": trip_name,
                        "from": p1,
                        "to": p2,
                        "path": route_path,
                        "target_info": target_info,
                        "is_return_wh": (i == len(pts) - 2)
                    })

        total_steps = len(df)
        
        col_ctrl1, col_ctrl2 = st.columns([1, 4])
        
        with col_ctrl1:
            auto_play = st.checkbox("▶️ เล่นอัตโนมัติ (Auto Play)")
            
        with col_ctrl2:
            step_idx = st.slider(
                "เลื่อนดูความคืบหน้าตามลำดับจุดจัดส่ง:",
                min_value=1,
                max_value=total_steps,
                value=1,
                step=1
            )

        if auto_play:
            placeholder_map = st.empty()
            placeholder_info = st.empty()

            for current_step in range(1, total_steps + 1):
                m = folium.Map(location=[df['lat'].mean(), df['lng'].mean()], zoom_start=13)

                folium.Marker(
                    location=warehouse_coord,
                    popup="<b>คลังสินค้า (Warehouse)</b>",
                    icon=folium.Icon(color="black", icon="home", prefix="fa")
                ).add_to(m)

                current_row = df.iloc[current_step - 1]
                
                if "แบบที่ 1" in play_mode:
                    for idx_all, r_all in df.iterrows():
                        color_marker = "green" if r_all['status'] == "จัดส่งตรงเวลา" else "red"
                        folium.CircleMarker(
                            location=[r_all['lat'], r_all['lng']],
                            radius=7,
                            color=color_marker,
                            fill=True,
                            fill_color=trip_colors.get(r_all['trip'], 'blue'),
                            fill_opacity=0.8,
                            popup=f"ลำดับที่ {idx_all+1}: {r_all['cust_name']} ({r_all['time']})"
                        ).add_to(m)

                    active_df = df.iloc[:current_step]
                    for trip_k, trip_g in active_df.groupby('trip', sort=False):
                        t_color = trip_colors.get(trip_k, 'blue')
                        for seg in segments:
                            if seg['trip'] == trip_k and seg['target_info'] in trip_g.to_dict('records'):
                                folium.PolyLine(
                                    seg['path'], color=t_color, weight=5, opacity=0.8
                                ).add_to(m)

                else:
                    active_df = df.iloc[:current_step]
                    for idx_act, r_act in active_df.iterrows():
                        color_marker = "green" if r_act['status'] == "จัดส่งตรงเวลา" else "red"
                        folium.Marker(
                            location=[r_act['lat'], r_act['lng']],
                            popup=f"ลำดับที่ {idx_act+1}: {r_act['cust_name']}<br>เวลา: {r_act['time']}",
                            icon=folium.Icon(color=color_marker, icon="flag")
                        ).add_to(m)

                        for seg in segments:
                            if seg['target_info'] == r_act.to_dict():
                                folium.PolyLine(
                                    seg['path'], 
                                    color=trip_colors.get(seg['trip'], 'blue'), 
                                    weight=5, 
                                    opacity=0.8
                                ).add_to(m)

                with placeholder_map.container():
                    st_folium(m, width=1100, height=550, key=f"sim_map_{current_step}")

                with placeholder_info.container():
                    st.info(
                        f"🚚 **กำลังจัดส่งจุดที่ {current_step}/{total_steps}** | "
                        f"**เที่ยว:** {current_row['trip']} | "
                        f"**เวลา:** {current_row['time']} น. | "
                        f"**ลูกค้า:** {current_row['cust_name']} (รหัส: {current_row['cust_id']}) | "
                        f"**ยอดส่ง:** {current_row['qty']} | "
                        f"**สถานะ:** {current_row['status']}"
                    )

                time.sleep(anim_speed)

        else:
            m = folium.Map(location=[df['lat'].mean(), df['lng'].mean()], zoom_start=13)

            folium.Marker(
                location=warehouse_coord,
                popup="<b>คลังสินค้า (Warehouse)</b>",
                icon=folium.Icon(color="black", icon="home", prefix="fa")
            ).add_to(m)

            current_row = df.iloc[step_idx - 1]

            if "แบบที่ 1" in play_mode:
                for idx_all, r_all in df.iterrows():
                    color_marker = "green" if r_all['status'] == "จัดส่งตรงเวลา" else "red"
                    folium.CircleMarker(
                        location=[r_all['lat'], r_all['lng']],
                        radius=7,
                        color=color_marker,
                        fill=True,
                        fill_color=trip_colors.get(r_all['trip'], 'blue'),
                        fill_opacity=0.8,
                        popup=f"ลำดับที่ {idx_all+1}: {r_all['cust_name']} ({r_all['time']})"
                    ).add_to(m)

                active_df = df.iloc[:step_idx]
                for trip_k, trip_g in active_df.groupby('trip', sort=False):
                    t_color = trip_colors.get(trip_k, 'blue')
                    g_records = trip_g.to_dict('records')
                    
                    for seg in segments:
                        if seg['trip'] == trip_k and seg['target_info'] in g_records:
                            folium.PolyLine(
                                seg['path'], color=t_color, weight=5, opacity=0.8
                            ).add_to(m)

            else:
                active_df = df.iloc[:step_idx]
                for idx_act, r_act in active_df.iterrows():
                    color_marker = "green" if r_act['status'] == "จัดส่งตรงเวลา" else "red"
                    folium.Marker(
                        location=[r_act['lat'], r_act['lng']],
                        popup=f"ลำดับที่ {idx_act+1}: {r_act['cust_name']}<br>เวลา: {r_act['time']}",
                        icon=folium.Icon(color=color_marker, icon="info-sign")
                    ).add_to(m)

                    for seg in segments:
                        if seg['target_info'] == r_act.to_dict():
                            folium.PolyLine(
                                seg['path'], 
                                color=trip_colors.get(seg['trip'], 'blue'), 
                                weight=5, 
                                opacity=0.8
                            ).add_to(m)

            st_folium(m, width=1100, height=550, key="manual_map")

            st.info(
                f"🚚 **สถานะจุดที่ {step_idx}/{total_steps}** | "
                f"**เที่ยว:** {current_row['trip']} | "
                f"**เวลา:** {current_row['time']} น. | "
                f"**ลูกค้า:** {current_row['cust_name']} (รหัส: {current_row['cust_id']}) | "
                f"**ยอดส่ง:** {current_row['qty']} | "
                f"**ยอดส่งสะสม:** {current_row['acc_qty']} | "
                f"**สถานะ:** {current_row['status']}"
            )

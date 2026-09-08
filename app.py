import streamlit as st
import pandas as pd
import pdfplumber
import re
import requests
import folium
import streamlit.components.v1 as components
import json

# ตั้งค่าคอนฟิกของหน้า Streamlit
st.set_page_config(
    page_title="การตรวจสอบเส้นทางการจัดส่ง",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 โปรเจกต์: การตรวจสอบเส้นทางการจัดส่ง")
st.markdown("ระบบวิเคราะห์รายงานการส่งสินค้า คำนวณเที่ยววิ่ง และจำลองเส้นทางบนถนนจริง (OSRM Routing)")

# --- SIDEBAR: การตั้งค่าพิกัดคลัง และรูปแบบการแสดงผล ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")
wh_lat = st.sidebar.number_input("Latitude คลังสินค้า", value=13.66800, format="%.5f")
wh_lng = st.sidebar.number_input("Longitude คลังสินค้า", value=100.61000, format="%.5f")
warehouse_coord = (wh_lat, wh_lng)

st.sidebar.header("🎬 การตั้งค่ารูปแบบแผนที่")
play_mode = st.sidebar.radio(
    "รูปแบบการแสดงผลบนแผนที่:",
    (
        "แบบที่ 1: แสดงหมุดครบทั้งหมดก่อน (เส้นทางวิ่งเชื่อมตามถนนจริง)",
        "แบบที่ 2: ปรากฏหมุดและเส้นทางทีละจุดตามลำดับเวลา"
    )
)

anim_speed_ms = st.sidebar.slider("ความเร็วการเล่น (มิลลิวินาที/เฟรม)", min_value=100, max_value=2000, value=500, step=100)


# --- FUNCTION: ดึงเส้นทางบนถนนจริงจาก OSRM ---
@st.cache_data(show_spinner=False)
def get_osrm_route(p1_lat, p1_lng, p2_lat, p2_lng):
    """
    เรียกใช้งาน OSRM API เพื่อหาเส้นทางบนถนนจริงสำหรับรถยนต์
    ระหว่างพิกัด p1 และ p2
    """
    url = f"http://router.project-osrm.org/route/v1/driving/{p1_lng},{p1_lat};{p2_lng},{p2_lat}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data.get("routes"):
                coords = data["routes"][0]["geometry"]["coordinates"]
                return [[pt[1], pt[0]] for pt in coords]
    except Exception:
        pass
    # หากเรียก API ไม่สำเร็จ ให้ลากเส้นตรงระหว่าง 2 จุดแทนเพื่อไม่ให้ระบบค้าง
    return [[p1_lat, p1_lng], [p2_lat, p2_lng]]


# --- FUNCTION: แกะข้อมูล PDF ยืดหยุ่นพิเศษ ---
def parse_pdf_data(pdf_file):
    header_info = {
        "date": "ไม่ระบุ",
        "truck_no": "ไม่ระบุ",
        "driver": "ไม่ระบุ"
    }
    
    dw_net = {}
    records = []

    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                lines = text.split('\n')
                
                # --- 1. อ่าน Header ---
                for line in lines:
                    if "ประจําวัน" in line or "ประจำวัน" in line:
                        date_match = re.search(r'([\d]{1,2}/[\d]{1,2}/[\d]{2,4})', line)
                        if date_match and header_info["date"] == "ไม่ระบุ":
                            header_info["date"] = date_match.group(1)
                        
                        truck_match = re.search(r'รถส่ง\s*(\w+)', line)
                        if truck_match and header_info["truck_no"] == "ไม่ระบุ":
                            header_info["truck_no"] = truck_match.group(1)

                    if "พนักงานขับรถ" in line and header_info["driver"] == "ไม่ระบุ":
                        driver_match = re.search(r'พนักงานขับรถ\s*(.*)', line)
                        if driver_match:
                            header_info["driver"] = driver_match.group(1).strip()

                    dw_match = re.search(r'DW\w*/(\d{3})\s+(\d+)', line)
                    if dw_match:
                        trip_no = int(dw_match.group(1))
                        qty = int(dw_match.group(2))
                        dw_net[trip_no] = dw_net.get(trip_no, 0) + qty

                    re_match = re.search(r'RE\w*/(\d{3})\s+(\d+)', line)
                    if re_match:
                        trip_no = int(re_match.group(1))
                        qty = int(re_match.group(2))
                        dw_net[trip_no] = dw_net.get(trip_no, 0) - qty

                # --- 2. อ่านข้อมูลแถวพิกัด GPS ---
                words = page.extract_words()
                lines_by_y = {}
                for w in words:
                    top = round(w['top'], 1)
                    lines_by_y.setdefault(top, []).append(w['text'])

                for top_y in sorted(lines_by_y.keys()):
                    line_str = " ".join(lines_by_y[top_y])
                    
                    # Regex พิกัด GPS ยืดหยุ่น
                    gps_match = re.search(r'(1[2-9]\.\d+)\s*[\,\/\s]\s*(9[8-9]\.\d+|10[0-5]\.\d+)', line_str)
                    time_match = re.search(r'(\d{1,2}:\d{2})', line_str)

                    if gps_match:
                        lat = float(gps_match.group(1))
                        lng = float(gps_match.group(2))
                        delivery_time = time_match.group(1) if time_match else "00:00"

                        cust_id_match = re.search(r'^([\d/]+)\s+', line_str.strip())
                        cust_id = cust_id_match.group(1) if cust_id_match else "N/A"

                        status = "จัดส่งตรงเวลา"
                        if "ไม่ตรงเวลา" in line_str:
                            status = "จัดส่งไม่ตรงเวลา"
                        elif "สมาชิกใหม่" in line_str:
                            status = "สมาชิกใหม่"
                        elif "รอบเสริม" in line_str:
                            status = "รอบเสริม"
                        elif "ย้ายรอบ" in line_str:
                            status = "ย้ายรอบ"

                        tokens = line_str.split()
                        qty_sent = 1
                        cust_name = "ลูกค้าทั่วไป"

                        for idx, t in enumerate(tokens):
                            if ("13." in t or "14." in t or "12." in t) and "." in t:
                                if idx >= 2 and tokens[idx-2].isdigit():
                                    qty_sent = int(tokens[idx-2])
                                
                                if len(tokens) > 2:
                                    name_tokens = [nt for nt in tokens[1:idx-2] if not nt.isdigit()]
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
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์ PDF: {e}")

    df = pd.DataFrame(records)

    if not df.empty:
        df = df.drop_duplicates(subset=['time', 'lat', 'lng']).sort_values(by="time").reset_index(drop=True)

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
    with st.spinner("กำลังอ่านและประมวลผลข้อมูลพิกัดทั้งหมดจาก PDF..."):
        df, dw_net, header_info = parse_pdf_data(uploaded_file)

    if df.empty:
        st.error("❌ ไม่พบข้อมูลพิกัด GPS หรือรายการจัดส่งในไฟล์ PDF นี้ กรุณาตรวจสอบว่าไม่ใช่ไฟล์ภาพสแกน")
    else:
        st.success(f"✅ ประมวลผลข้อมูลสำเร็จ! พบรายการจัดส่งทั้งหมด {len(df)} จุดส่ง")

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

        st.divider()

        # --- MAP VISUALIZATION ---
        st.subheader("🗺️ แผนที่และระบบจำลองการวิ่งจัดส่งตามถนนจริง (Smooth Animation)")

        trip_colors = {
            "เที่ยวที่ 1": "#1E90FF",
            "เที่ยวที่ 2": "#2E8B57",
            "เที่ยวที่ 3": "#FF8C00",
            "เที่ยวที่ 4": "#9370DB",
            "เที่ยวที่ 5": "#DC143C"
        }

        # คำนวณเส้นทาง OSRM ถนนจริง
        with st.spinner("กำลังคำนวณเส้นทางถนนจริง (OSRM Engine)..."):
            segments_data = []
            grouped = df.groupby('trip', sort=False)

            for trip_name, group in grouped:
                pts = [warehouse_coord] + list(zip(group['lat'], group['lng'])) + [warehouse_coord]
                records_list = group.to_dict('records')

                for i in range(len(pts) - 1):
                    p1 = pts[i]
                    p2 = pts[i+1]
                    road_path = get_osrm_route(p1[0], p1[1], p2[0], p2[1])

                    info = records_list[i] if i < len(records_list) else {"cust_name": "คลังสินค้า", "time": "จบเที่ยว", "qty": 0, "status": "กลับคลัง"}

                    segments_data.append({
                        "trip": trip_name,
                        "color": trip_colors.get(trip_name, "#1E90FF"),
                        "path": road_path,
                        "info": info
                    })

        points_json = json.dumps(df.to_dict('records'))
        segments_json = json.dumps(segments_data)
        wh_json = json.dumps(warehouse_coord)
        is_mode_1 = "แบบที่ 1" in play_mode

        map_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map {{ width: 100%; height: 550px; border-radius: 10px; }}
                .controls {{ margin-bottom: 10px; font-family: sans-serif; display: flex; gap: 10px; align-items: center; }}
                button {{ padding: 8px 16px; background-color: #008CBA; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
                button:hover {{ background-color: #005f73; }}
                #info-box {{ margin-top: 10px; padding: 10px; background: #eef2f5; border-left: 5px solid #008CBA; font-family: sans-serif; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="controls">
                <button onclick="startAnimation()">▶️ เริ่มเล่น (Play)</button>
                <button onclick="pauseAnimation()">⏸️ หยุดพัก (Pause)</button>
                <button onclick="resetAnimation()">🔄 เริ่มใหม่ (Reset)</button>
                <span id="status-text" style="font-weight: bold; font-family: sans-serif;">เตรียมพร้อมสำหรับการจำลอง...</span>
            </div>
            <div id="map"></div>
            <div id="info-box">📍 **ข้อมูลจุดส่ง**: กดปุ่ม "เริ่มเล่น" เพื่อดูเส้นทางการจัดส่งตามถนนจริง</div>

            <script>
                const points = {points_json};
                const segments = {segments_json};
                const warehouse = {wh_json};
                const isMode1 = {str(is_mode_1).lower()};
                const speedMs = {anim_speed_ms};

                const map = L.map('map').setView([warehouse[0], warehouse[1]], 13);
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap'
                }}).addTo(map);

                L.marker(warehouse).addTo(map).bindPopup("<b>🏢 คลังสินค้าหลัก (Warehouse)</b>");

                let allMarkers = [];
                let activePolylines = [];
                let currentStep = 0;
                let animTimer = null;

                if (isMode1) {{
                    points.forEach((pt, idx) => {{
                        let color = pt.status === "จัดส่งตรงเวลา" ? "green" : "red";
                        let circle = L.circleMarker([pt.lat, pt.lng], {{
                            radius: 6,
                            color: color,
                            fillColor: "#3388ff",
                            fillOpacity: 0.3
                        }}).addTo(map).bindPopup(`<b>ลำดับที่ ${{idx+1}}: ${{pt.cust_name}}</b><br>เวลา: ${{pt.time}} น.`);
                        allMarkers.push(circle);
                    }});
                }}

                function renderStep(step) {{
                    if (step >= segments.length) return;

                    const seg = segments[step];
                    const info = seg.info;

                    const polyline = L.polyline(seg.path, {{
                        color: seg.color,
                        weight: 5,
                        opacity: 0.8
                    }}).addTo(map);
                    activePolylines.push(polyline);

                    if (info.lat && info.lng) {{
                        let markerColor = info.status === "จัดส่งตรงเวลา" ? "green" : "red";
                        let m = L.circleMarker([info.lat, info.lng], {{
                            radius: 8,
                            color: markerColor,
                            fillColor: seg.color,
                            fillOpacity: 0.9
                        }}).addTo(map).bindPopup(`<b>${{info.cust_name}}</b><br>เวลา: ${{info.time}} น.`);
                        allMarkers.push(m);
                    }}

                    document.getElementById('status-text').innerText = `กำลังรันจุดที่ ${{step + 1}} / ${{segments.length}} (${{seg.trip}})`;
                    document.getElementById('info-box').innerHTML = `
                        <b>🚚 สถานะปัจจุบัน:</b> ${{seg.trip}} | 
                        <b>เวลา:</b> ${{info.time || 'N/A'}} | 
                        <b>ลูกค้า:</b> ${{info.cust_name}} | 
                        <b>ยอดส่ง:</b> ${{info.qty || 0}} ใบ | 
                        <b>สถานะ:</b> ${{info.status}}
                    `;
                }}

                function startAnimation() {{
                    if (animTimer) clearInterval(animTimer);
                    animTimer = setInterval(() => {{
                        if (currentStep < segments.length) {{
                            renderStep(currentStep);
                            currentStep++;
                        }} else {{
                            clearInterval(animTimer);
                            document.getElementById('status-text').innerText = "✅ จำลองการจัดส่งครบถ้วนทุกจุดแล้ว!";
                        }}
                    }}, speedMs);
                }}

                function pauseAnimation() {{
                    if (animTimer) clearInterval(animTimer);
                    document.getElementById('status-text').innerText = "⏸️ หยุดการจำลองชั่วคราว";
                }}

                function resetAnimation() {{
                    if (animTimer) clearInterval(animTimer);
                    currentStep = 0;
                    activePolylines.forEach(p => map.removeLayer(p));
                    activePolylines = [];
                    document.getElementById('status-text').innerText = "เตรียมพร้อมสำหรับการจำลอง...";
                    document.getElementById('info-box').innerHTML = "📍 **ข้อมูลจุดส่ง**: กดปุ่ม 'เริ่มเล่น' เพื่อดูเส้นทางการจัดส่งตามถนนจริง";
                }}
            </script>
        </body>
        </html>
        """

        components.html(map_html, height=650)

import streamlit as st
import pandas as pd
import pdfplumber
import re
import requests
import streamlit.components.v1 as components
import json

# ตั้งค่าคอนฟิกของหน้า Streamlit
st.set_page_config(
    page_title="ระบบตรวจสอบเส้นทางการจัดส่งสินค้า",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 โปรเจกต์: การตรวจสอบเส้นทางการจัดส่งสินค้า (Sprinkle Delivery Route Inspector)")
st.markdown("ระบบวิเคราะห์รายงานการส่งสินค้า คำนวณเที่ยววิ่งตามเอกสาร DW และจำลองเส้นทางบนถนนจริง (OSRM Routing)")

# --- SIDEBAR: การตั้งค่าพิกัดคลังสินค้า และรูปแบบการแสดงผล ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")
wh_input = st.sidebar.text_input("พิกัดคลังสินค้า (Lat, Lng)", value="13.66800, 100.61000")

try:
    wh_lat, wh_lng = [float(x.strip()) for x in wh_input.split(',')]
    warehouse_coord = (wh_lat, wh_lng)
except Exception:
    st.sidebar.error("⚠️ รูปแบบพิกัดคลังไม่ถูกต้อง กรุณากรอกเป็น 'Latitude, Longitude'")
    warehouse_coord = (13.66800, 100.61000)

st.sidebar.header("🎬 การตั้งค่าการจำลองแผนที่")
play_mode = st.sidebar.radio(
    "รูปแบบการแสดงผลบนแผนที่:",
    (
        "แบบที่ 1: แสดงหมุดครบทั้งหมดล่วงหน้า (เส้นทางวิ่งตามเวลา)",
        "แบบที่ 2: ปรากฏหมุดและเส้นทางเฉพาะจุดล่าสุดทีละจุดตามลำดับเวลา"
    )
)

anim_speed_ms = st.sidebar.slider("ความเร็วการเล่น (มิลลิวินาที/เฟรม)", min_value=100, max_value=2000, value=600, step=100)


# --- FUNCTION: ดึงเส้นทางบนถนนจริงจาก OSRM ---
@st.cache_data(show_spinner=False)
def get_osrm_route(p1_lat, p1_lng, p2_lat, p2_lng):
    url = f"http://router.project-osrm.org/route/v1/driving/{p1_lng},{p1_lat};{p2_lng},{p2_lat}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=4)
        if response.status_code == 200:
            data = response.json()
            if data.get("routes"):
                coords = data["routes"][0]["geometry"]["coordinates"]
                return [[pt[1], pt[0]] for pt in coords]
    except Exception:
        pass
    return [[p1_lat, p1_lng], [p2_lat, p2_lng]]


# --- FUNCTION: สกัดข้อมูลจาก PDF ฉบับปรุงปรุงเพื่อ Sprinkle Report โดยเฉพาะ ---
def parse_pdf_data(pdf_file):
    header_info = {"date": "ไม่ระบุ", "truck_no": "ไม่ระบุ", "driver": "ไม่ระบุ"}
    dw_list = []
    records = []

    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = text.split('\n')
                
                # 1. แกะข้อมูลส่วนหัวเอกสาร และข้อมูล DW (รายการเบิกสินค้า)
                for line in lines:
                    if "ประจําวัน" in line or "ประจำวัน" in line:
                        date_match = re.search(r'([\d]{1,2}/[\d]{1,2}/[\d]{2,4})', line)
                        if date_match and header_info["date"] == "ไม่ระบุ":
                            header_info["date"] = date_match.group(1)
                        
                        truck_match = re.search(r'รถส่ง\s*(\w+)', line)
                        if truck_match and header_info["truck_no"] == "ไม่ระบุ":
                            header_info["truck_no"] = truck_match.group(1)

                    if "พนักงานขับรถ" in line and header_info["driver"] == "ไม่ระบุ":
                        driver_match = re.search(r'พนักงานขับรถ\s*(\d+\s*[\u0E00-\u0E7F\s]+)', line)
                        if driver_match:
                            header_info["driver"] = driver_match.group(1).strip()
                        else:
                            driver_match_alt = re.search(r'พนักงานขับรถ\s*(.*)', line)
                            if driver_match_alt:
                                header_info["driver"] = driver_match_alt.group(1).split("พนักงานยก")[0].strip()

                    # แกะรายการเบิก DWS
                    dw_match = re.search(r'DWS\d+/\d+\s+\|\s*(\d+)', line)
                    if dw_match:
                        dw_list.append(int(dw_match.group(1)))

                # 2. แกะตารางข้อมูลรายการส่งแบบ Row-by-Row ด้วย pdfplumber words
                words = page.extract_words()
                lines_by_y = {}
                for w in words:
                    top = round(w['top'], 1)
                    lines_by_y.setdefault(top, []).append(w)

                for top_y in sorted(lines_by_y.keys()):
                    line_words = sorted(lines_by_y[top_y], key=lambda x: x['x0'])
                    line_str = " ".join([w['text'] for w in line_words])
                    
                    # ค้นหาพิกัด GPS (Lat, Lng)
                    gps_match = re.search(r'(1[2-9]\.\d+)\s*[\,\/]\s*(10[0-5]\.\d+|9[8-9]\.\d+)', line_str)
                    
                    if gps_match:
                        lat = float(gps_match.group(1))
                        lng = float(gps_match.group(2))

                        # สกัดเวลาส่ง (เช่น 09:30 น.)
                        time_match = re.search(r'(\d{1,2}:\d{2}\s*น\.)', line_str)
                        delivery_time = time_match.group(1) if time_match else "ไม่ระบุ"

                        # สกัดสถานะ
                        status = "จัดส่งตรงเวลา"
                        if "จัดส่งไม่ตรงเวลา" in line_str:
                            status = "จัดส่งไม่ตรงเวลา"
                        elif "รอบเสริม" in line_str:
                            status = "รอบเสริม"
                        elif "ย้าย" in line_str or "ย้ายรอบ" in line_str:
                            status = "ย้ายรอบ"

                        # สกัดรหัสลูกค้า (คำแรกที่เป็นตัวเลข)
                        cust_id = "N/A"
                        if len(line_words) > 0 and re.match(r'^[\d/]+$', line_words[0]['text']):
                            cust_id = line_words[0]['text']

                        # สกัดยอดส่ง (ตัวเลขถัดจากชื่อลูกค้า)
                        qty_sent = 1
                        for w in line_words[1:]:
                            if w['text'].isdigit() and int(w['text']) < 100:
                                qty_sent = int(w['text'])
                                break

                        # สกัดชื่อลูกค้า
                        name_words = []
                        for w in line_words[1:]:
                            text_w = w['text']
                            if text_w in ["|", "น.", "จัดส่งตรงเวลา", "จัดส่งไม่ตรงเวลา", "รอบเสริม", "ย้ายรอบ"]:
                                continue
                            if re.match(r'^(1[2-9]\.\d+|10[0-5]\.\d+|\d{1,2}:\d{2})$', text_w):
                                continue
                            if text_w.isdigit() and int(text_w) <= 100:
                                break
                            name_words.append(text_w)
                        
                        cust_name = " ".join(name_words).strip()
                        cust_name = cust_name.replace("'", "").replace('"', '').replace("|", "").strip()
                        if not cust_name:
                            cust_name = "ไม่ระบุชื่อ"

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
        # แบ่งเที่ยวการส่งตามวงเงินเบิกสินค้าจริงใน DW
        trips = []
        acc_qty_list = []
        
        # หากอ่าน DW List ได้ จะแบ่งตามโควต้า DW แต่ละรอบ (เช่น 80, 80)
        dw_limits = dw_list if len(dw_list) > 0 else [80, 80]
        
        current_trip = 1
        current_trip_qty = 0
        current_limit = dw_limits[0] if len(dw_limits) > 0 else 80
        total_acc = 0

        for idx, row in df.iterrows():
            qty = row['qty']
            if current_trip_qty + qty > current_limit and current_trip_qty > 0 and current_trip < len(dw_limits):
                current_trip += 1
                current_trip_qty = 0
                current_limit = dw_limits[current_trip - 1] if current_trip <= len(dw_limits) else 80

            current_trip_qty += qty
            total_acc += qty
            trips.append(f"เที่ยวที่ {current_trip}")
            acc_qty_list.append(total_acc)

        df['trip'] = trips
        df['acc_qty'] = acc_qty_list

    return df, dw_list, header_info


# --- MAIN APPLICATION INTERFACE ---
uploaded_file = st.file_uploader("📂 กรุณาอัปโหลดไฟล์รายงานการส่งสินค้า (PDF)", type=["pdf"])

if uploaded_file:
    with st.spinner("กำลังอ่านและประมวลผลข้อมูลพิกัดจากไฟล์ PDF..."):
        df, dw_list, header_info = parse_pdf_data(uploaded_file)

    if df.empty:
        st.error("❌ ไม่พบข้อมูลรายการจัดส่งในไฟล์ PDF กรุณาตรวจสอบว่าเป็นไฟล์รายงาน Sprinkle PDF ที่ถูกต้อง")
    else:
        st.success(f"✅ ประมวลผลสำเร็จ! พบรายการจัดส่งทั้งหมด {len(df)} จุดส่ง | ยอดจัดส่งรวมทั้งหมด {df['qty'].sum()} ถัง ({df['trip'].nunique()} เที่ยวส่ง)")

        # --- ส่วนแสดง HEADER ข้อมูลประจำวัน ---
        st.subheader("📌 ข้อมูลปฏิบัติงานประจำวัน")
        h_col1, h_col2, h_col3 = st.columns(3)
        h_col1.info(f"📅 **งานประจำวันที่:** {header_info['date']}")
        h_col2.info(f"🚛 **รถส่ง:** {header_info['truck_no']}")
        h_col3.info(f"👨‍✈️ **พนักงานขับรถ:** {header_info['driver']}")

        # --- ตารางแสดงรายการจัดส่ง ---
        st.subheader("📋 ตารางรายการจัดส่งสินค้า (เรียงตามลำดับเวลาปฏิบัติงาน)")
        display_df = df[['time', 'trip', 'cust_id', 'cust_name', 'qty', 'acc_qty', 'status', 'lat', 'lng']].copy()
        display_df.columns = ['เวลาส่ง', 'เที่ยวส่ง', 'รหัสลูกค้า', 'ชื่อลูกค้า / สมาชิก', 'ยอดส่ง (ถัง)', 'ยอดส่งสะสม', 'สถานะการส่ง', 'Latitude', 'Longitude']
        st.dataframe(display_df, use_container_width=True, height=280)

        # --- สรุปยอดส่งแต่ละเที่ยว ---
        st.subheader("📊 รายงานสรุปยอดส่งแบ่งตามเที่ยว (Trip Summary)")
        trip_summaries = []
        for idx, (trip_name, group) in enumerate(df.groupby('trip', sort=False)):
            dw_val = dw_list[idx] if idx < len(dw_list) else group['qty'].sum()
            trip_summaries.append({
                "เที่ยวการส่ง": trip_name,
                "จำนวนถังที่เบิก (DW)": dw_val,
                "ยอดจัดส่งจริง (ถัง)": group['qty'].sum(),
                "จำนวนจุดส่งทั้งหมด (จุด)": len(group),
                "จัดส่งตรงเวลา (จุด)": len(group[group['status'] == 'จัดส่งตรงเวลา']),
                "จัดส่งไม่ตรงเวลา/อื่นๆ (จุด)": len(group[group['status'] != 'จัดส่งตรงเวลา']),
                "เส้นทางวิ่ง": "วิ่งออกจากคลัง -> ส่งสินค้าตามลำดับ -> วิ่งกลับคลัง"
            })
        st.table(pd.DataFrame(trip_summaries))

        st.divider()

        # --- MAP VISUALIZATION ---
        st.subheader("🗺️ แผนที่และระบบจำลองการวิ่งจัดส่งตามถนนจริง (Interactive OSRM Routing)")

        # กำหนดโทนสีแต่ละเที่ยวให้แตกต่างกันอย่างเด่นชัด
        trip_colors = {
            "เที่ยวที่ 1": "#0055FF",  # สีน้ำเงินเข้ม
            "เที่ยวที่ 2": "#FF0055",  # สีชมพูแดงเข้ม
            "เที่ยวที่ 3": "#00AA44",  # สีเขียวสด
            "เที่ยวที่ 4": "#AA00FF",  # สีม่วงเข้ม
            "เที่ยวที่ 5": "#FF6600"   # สีส้มสว่าง
        }

        # คำนวณเส้นทาง OSRM
        with st.spinner("กำลังเชื่อมต่อ OSRM Engine เพื่อคำนวณเส้นทางถนนจริง..."):
            segments_data = []
            grouped = df.groupby('trip', sort=False)

            for trip_name, group in grouped:
                pts = [warehouse_coord] + list(zip(group['lat'], group['lng'])) + [warehouse_coord]
                records_list = group.to_dict('records')

                for i in range(len(pts) - 1):
                    p1, p2 = pts[i], pts[i+1]
                    road_path = get_osrm_route(p1[0], p1[1], p2[0], p2[1])
                    
                    info = records_list[i] if i < len(records_list) else {
                        "cust_id": "WH-001",
                        "cust_name": "คลังสินค้าหลัก (Warehouse)", 
                        "time": "เสร็จสิ้นเที่ยววิ่ง", 
                        "qty": 0, 
                        "status": "วิ่งกลับเข้าคลังเรียบร้อย"
                    }

                    segments_data.append({
                        "trip": trip_name,
                        "color": trip_colors.get(trip_name, "#0055FF"),
                        "path": road_path,
                        "info": info
                    })

        points_json = json.dumps(df.to_dict('records'), ensure_ascii=False)
        segments_json = json.dumps(segments_data, ensure_ascii=False)
        wh_json = json.dumps(warehouse_coord)
        is_mode_1 = "แบบที่ 1" in play_mode

        map_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map {{ width: 100%; height: 580px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
                .controls {{ margin-bottom: 12px; font-family: 'Sarabun', sans-serif; display: flex; gap: 10px; align-items: center; }}
                button {{ padding: 8px 18px; background-color: #008CBA; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: bold; transition: 0.2s; }}
                button:hover {{ background-color: #005f73; transform: scale(1.02); }}
                #info-box {{ margin-top: 12px; padding: 12px 16px; background: #f8f9fa; border-left: 6px solid #008CBA; font-family: sans-serif; border-radius: 4px; font-size: 15px; line-height: 1.6; color: #333; }}
                .legend {{ display: flex; gap: 15px; margin-bottom: 8px; font-family: sans-serif; font-size: 13px; font-weight: bold; }}
                .legend-item {{ display: flex; align-items: center; gap: 5px; }}
                .color-box {{ width: 14px; height: 14px; border-radius: 3px; display: inline-block; }}
            </style>
        </head>
        <body>
            <div class="legend">
                <div class="legend-item"><span class="color-box" style="background:#0055FF;"></span> เที่ยวที่ 1 (สีน้ำเงิน)</div>
                <div class="legend-item"><span class="color-box" style="background:#FF0055;"></span> เที่ยวที่ 2 (สีชมพูแดง)</div>
            </div>
            <div class="controls">
                <button onclick="startAnimation()">▶️ เริ่มเล่น (Play)</button>
                <button onclick="pauseAnimation()">⏸️ หยุดพัก (Pause)</button>
                <button onclick="resetAnimation()">🔄 เริ่มใหม่ (Reset)</button>
                <span id="status-text" style="font-weight: bold; font-family: sans-serif; color: #2c3e50;">พร้อมสำหรับการจำลองเส้นทาง...</span>
            </div>
            <div id="map"></div>
            <div id="info-box">📍 **สถานะพิกัด**: กดปุ่ม "เริ่มเล่น" เพื่อดูการเดินทางแบบ Real-time</div>

            <script>
                const points = {points_json};
                const segments = {segments_json};
                const warehouse = {wh_json};
                const isMode1 = {str(is_mode_1).lower()};
                const speedMs = {anim_speed_ms};

                const map = L.map('map').setView([warehouse[0], warehouse[1]], 13);
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap contributors'
                }}).addTo(map);

                // คลังสินค้า Marker
                L.marker(warehouse).addTo(map)
                    .bindPopup("<b>🏢 คลังสินค้าหลัก (Warehouse)</b>")
                    .bindTooltip("🏢 คลังสินค้าหลัก", {{permanent: false, direction: 'top'}});

                let allMarkers = [];
                let activePolylines = [];
                let currentStep = 0;
                let animTimer = null;
                let currentActiveMarker = null;

                // แบบที่ 1: ปักหมุดทั้งหมดล่วงหน้า พร้อม Tooltip ชี้แล้วโชว์ข้อมูล
                if (isMode1) {{
                    points.forEach((pt, idx) => {{
                        let color = pt.status === "จัดส่งตรงเวลา" ? "#00AA44" : "#FF0000";
                        let popupText = `<b>ลำดับที่ ${{idx+1}}: ${{pt.cust_name}}</b><br>` +
                                        `รหัสลูกค้า: ${{pt.cust_id}}<br>` +
                                        `เวลาส่ง: ${{pt.time}}<br>` +
                                        `ยอดส่ง: ${{pt.qty}} ถัง<br>` +
                                        `สถานะ: ${{pt.status}}`;
                        
                        let tooltipText = `${{idx+1}}. ${{pt.cust_name}} (${{pt.time}})`;

                        let circle = L.circleMarker([pt.lat, pt.lng], {{
                            radius: 7,
                            color: color,
                            fillColor: color,
                            fillOpacity: 0.7
                        }}).addTo(map)
                        .bindPopup(popupText)
                        .bindTooltip(tooltipText, {{permanent: false, direction: 'top'}});
                        
                        allMarkers.push(circle);
                    }});
                }}

                function renderStep(step) {{
                    if (step >= segments.length) return;

                    const seg = segments[step];
                    const info = seg.info;

                    // วาดเส้นทาง OSRM ตามสีของเที่ยววิ่งนั้นๆ
                    const polyline = L.polyline(seg.path, {{
                        color: seg.color,
                        weight: 6,
                        opacity: 0.85
                    }}).addTo(map);
                    activePolylines.push(polyline);

                    // ย้ายจุดเน้นตำแหน่งล่าสุด (Current Location Marker)
                    if (currentActiveMarker) {{
                        map.removeLayer(currentActiveMarker);
                    }}

                    if (info.lat && info.lng) {{
                        let popupText = `<b>🚚 พิกัดล่าสุด: ${{info.cust_name}}</b><br>` +
                                        `รหัสลูกค้า: ${{info.cust_id}}<br>` +
                                        `เวลาส่ง: ${{info.time}}<br>` +
                                        `ยอดส่ง: ${{info.qty}} ถัง<br>` +
                                        `เที่ยววิ่ง: ${{seg.trip}}`;

                        let tooltipText = `📍 ${{info.cust_name}} (${{info.time}})`;

                        // สร้างหมุดขนาดใหญ่เน้นจุดล่าสุด
                        currentActiveMarker = L.circleMarker([info.lat, info.lng], {{
                            radius: 12,
                            color: "#FFFFFF",
                            weight: 3,
                            fillColor: seg.color,
                            fillOpacity: 1.0
                        }}).addTo(map)
                        .bindPopup(popupText)
                        .bindTooltip(tooltipText, {{permanent: true, direction: 'top'}})
                        .openPopup();

                        // แบบที่ 2: เพิ่มหมุดสะสมถาวร
                        if (!isMode1) {{
                            let permanentMarker = L.circleMarker([info.lat, info.lng], {{
                                radius: 7,
                                color: seg.color,
                                fillColor: seg.color,
                                fillOpacity: 0.6
                            }}).addTo(map)
                            .bindPopup(popupText)
                            .bindTooltip(tooltipText, {{permanent: false, direction: 'top'}});
                            allMarkers.push(permanentMarker);
                        }}

                        map.panTo([info.lat, info.lng]);
                    }}

                    // อัปเดตกล่องข้อมูลด้านล่างแผนที่ให้แสดงข้อมูลเฉพาะจุดนั้น
                    document.getElementById('status-text').innerText = `กำลังเดินทาง: จุดที่ ${{step + 1}} / ${{segments.length}} (${{seg.trip}})`;
                    document.getElementById('info-box').innerHTML = `
                        <div style="color:${{seg.color}}; font-weight:bold; font-size:16px;">🚚 ${{seg.trip}} - จุดส่งที่ ${{step + 1}}</div>
                        <b>เวลาจัดส่ง:</b> ${{info.time || 'ไม่ระบุ'}} | 
                        <b>รหัสลูกค้า:</b> ${{info.cust_id}} | 
                        <b>ชื่อลูกค้า / สมาชิก:</b> <span style="color:#0055FF; font-weight:bold;">${{info.cust_name}}</span><br>
                        <b>ยอดส่งสินค้า:</b> ${{info.qty || 0}} ถัง | 
                        <b>สถานะการจัดส่ง:</b> ${{info.status}}
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
                            document.getElementById('status-text').innerText = "✅ จำลองการจัดส่งสินค้าเสร็จสิ้นครบถ้วนทุกจุด!";
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
                    
                    if (currentActiveMarker) {{
                        map.removeLayer(currentActiveMarker);
                        currentActiveMarker = null;
                    }}

                    if (!isMode1) {{
                        allMarkers.forEach(m => map.removeLayer(m));
                        allMarkers = [];
                    }}
                    
                    map.setView([warehouse[0], warehouse[1]], 13);
                    document.getElementById('status-text').innerText = "พร้อมสำหรับการจำลองเส้นทาง...";
                    document.getElementById('info-box').innerHTML = "📍 **สถานะพิกัด**: กดปุ่ม 'เริ่มเล่น' เพื่อดูการเดินทางแบบ Real-time";
                }}
            </script>
        </body>
        </html>
        """

        components.html(map_html, height=720)

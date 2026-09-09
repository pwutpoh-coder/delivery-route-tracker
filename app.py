import streamlit as st
import pandas as pd
import pdfplumber
import re
import requests
import json
import streamlit.components.v1 as components

# --- ตั้งค่าหน้าตาแอปพลิเคชัน ---
st.set_page_config(
    page_title="ระบบวิเคราะห์และติดตามเส้นทางส่งสินค้า Sprinkle",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 ระบบวิเคราะห์และติดตามเส้นทางส่งสินค้า (Sprinkle Delivery Inspector)")
st.markdown("ดึงข้อมูลจากเอกสารสรุปการส่งสินค้าประจำวัน (PDF) พร้อมจำลองเส้นทางบนถนนจริงผ่าน OSRM")

# --- SIDEBAR: ตั้งค่าคลังสินค้าและการเล่นแผนที่ ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")
wh_input = st.sidebar.text_input("พิกัดคลังสินค้า (Lat, Lng)", value="13.66800, 100.61000")

try:
    wh_lat, wh_lng = [float(x.strip()) for x in wh_input.split(',')]
    warehouse_coord = (wh_lat, wh_lng)
except Exception:
    st.sidebar.error("⚠️ รูปแบบพิกัดไม่ถูกต้อง ใช้ค่าเริ่มต้น 13.66800, 100.61000")
    warehouse_coord = (13.66800, 100.61000)

st.sidebar.header("🎬 การตั้งค่าการจำลองเส้นทาง")
play_mode = st.sidebar.radio(
    "รูปแบบการแสดงผลบนแผนที่:",
    (
        "แบบที่ 1: แสดงหมุดครบทั้งหมดล่วงหน้า (เส้นทางวิ่งตามเวลา)",
        "แบบที่ 2: ปรากฏหมุดและเส้นทางเฉพาะจุดล่าสุดทีละจุดตามลำดับเวลา"
    )
)

anim_speed_ms = st.sidebar.slider("ความเร็วการจำลอง (มิลลิวินาที/จุด)", min_value=100, max_value=2000, value=600, step=100)


# --- FUNCTION: ดึงเส้นทางถนนจริงจาก OSRM ---
@st.cache_data(show_spinner=False)
def get_osrm_route(p1_lat, p1_lng, p2_lat, p2_lng):
    url = f"http://router.project-osrm.org/route/v1/driving/{p1_lng},{p1_lat};{p2_lng},{p2_lat}?overview=full&geometries=geojson"
    try:
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data.get("routes"):
                coords = data["routes"][0]["geometry"]["coordinates"]
                return [[pt[1], pt[0]] for pt in coords]
    except Exception:
        pass
    return [[p1_lat, p1_lng], [p2_lat, p2_lng]]


# --- FUNCTION: PARSE PDF (แก้ปัญหาอ่านข้อมูลไม่ครบยอดไม่ตรงอย่างสมบูรณ์) ---
def parse_pdf_data(pdf_file):
    header_info = {"date": "ไม่ระบุ", "truck_no": "ไม่ระบุ", "driver": "ไม่ระบุ"}
    dw_list = []
    records = []

    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            
            # 1. สกัดข้อมูล Header & DW
            if page_num == 0:
                date_m = re.search(r'ประจําวัน\s*([\d/]+)', text) or re.search(r'ประจำวัน\s*([\d/]+)', text)
                if date_m:
                    header_info["date"] = date_m.group(1)
                
                truck_m = re.search(r'รถส่ง\s*(\w+)', text)
                if truck_m:
                    header_info["truck_no"] = truck_m.group(1)

                driver_m = re.search(r'พนักงานขับรถ\s*([\d]+\s*[\u0E00-\u0E7F\s]+)', text)
                if driver_m:
                    header_info["driver"] = driver_m.group(1).split("พนักงานยก")[0].strip()

                # แกะ DW เบิกสินค้า
                dw_matches = re.findall(r'DWS\d+/\d+\s+\|\s*(\d+)', text)
                for dw_val in dw_matches:
                    dw_list.append(int(dw_val))

            # 2. สกัดตารางข้อมูลรายการส่งด้วย Regex Pattern ขั้นสูง
            # ค้นหาบล็อกรายการส่งจากพิกัด GPS เช่น 13.74693,100.59154
            raw_lines = text.split('\n')
            
            # รวมบรรทัดเพื่อจัดการกรณีชื่อลูกค้าอยู่คนละบรรทัดกับพิกัด
            full_text = "\n".join(raw_lines)
            
            # Regex ตรวจจับรูปแบบแพทเทิร์นรายการส่งใน PDF Sprinkle
            pattern = re.compile(
                r'([\d/]+)\s*\n?\s*\|\s*([^\n|]+?)\s*\n?\s*\|\s*(\d+)\s*\|\s*[\d\s|]*?\s*(1[2-9]\.\d+)\s*,\s*(10[0-5]\.\d+)\s*\|\s*[\d\.]+\s*\|\s*(\d{1,2}:\d{2}\s*น\.[^\n]*)'
            )

            matches = pattern.findall(full_text)
            
            if matches:
                for m in matches:
                    cust_id = m[0].strip()
                    cust_name = m[1].replace('\n', ' ').strip()
                    qty = int(m[2])
                    lat = float(m[3])
                    lng = float(m[4])
                    time_status_str = m[5].strip()

                    # แยกเวลาและสถานะ
                    time_m = re.search(r'(\d{1,2}:\d{2}\s*น\.)', time_status_str)
                    deliv_time = time_m.group(1) if time_m else "ไม่ระบุ"

                    status = "จัดส่งตรงเวลา"
                    if "จัดส่งไม่ตรงเวลา" in time_status_str:
                        status = "จัดส่งไม่ตรงเวลา"
                    elif "รอบเสริม" in time_status_str:
                        status = "รอบเสริม"
                    elif "ย้าย" in time_status_str:
                        status = "ย้ายรอบ"

                    records.append({
                        "cust_id": cust_id,
                        "cust_name": cust_name,
                        "qty": qty,
                        "lat": lat,
                        "lng": lng,
                        "time": deliv_time,
                        "status": status
                    })
            else:
                # Fallback Parsing (บรรทัดต่อบรรทัดแบบยืดหยุ่น)
                i = 0
                while i < len(raw_lines):
                    line = raw_lines[i]
                    gps_m = re.search(r'(1[2-9]\.\d+)\s*,\s*(10[0-5]\.\d+)', line)
                    if gps_m:
                        lat = float(gps_m.group(1))
                        lng = float(gps_m.group(2))
                        
                        time_m = re.search(r'(\d{1,2}:\d{2}\s*น\.)', line)
                        deliv_time = time_m.group(1) if time_m else "ไม่ระบุ"
                        
                        status = "จัดส่งตรงเวลา"
                        if "จัดส่งไม่ตรงเวลา" in line:
                            status = "จัดส่งไม่ตรงเวลา"
                        elif "รอบเสริม" in line:
                            status = "รอบเสริม"
                        elif "ย้าย" in line:
                            status = "ย้ายรอบ"

                        # ถอยหลังหาส่วนของ รหัส, ชื่อ, ยอดส่ง
                        cust_id = "N/A"
                        cust_name = "ไม่ระบุชื่อ"
                        qty = 1

                        # ค้นหาข้อความในบรรทัดย้อนหลัง 1-2 บรรทัด
                        search_block = " ".join(raw_lines[max(0, i-2):i+1])
                        
                        # ค้นหารหัสลูกค้า
                        cid_m = re.search(r'(\b\d{5,6}(?:/\d+)?\b)', search_block)
                        if cid_m:
                            cust_id = cid_m.group(1)

                        # ค้นหายอดส่ง
                        qty_m = re.search(r'\|\s*(\d{1,2})\s*\|', line) or re.search(r'\s(\d{1,2})\s+\|\s*\d+', search_block)
                        if qty_m:
                            qty = int(qty_m.group(1))

                        # ค้นหาชื่อ
                        name_m = re.search(r'\|\s*([\u0E00-\u0E7FA-Za-z\s\.\(\)]+)\s*\|', search_block)
                        if name_m:
                            cust_name = name_m.group(1).strip()

                        records.append({
                            "cust_id": cust_id,
                            "cust_name": cust_name,
                            "qty": qty,
                            "lat": lat,
                            "lng": lng,
                            "time": deliv_time,
                            "status": status
                        })
                    i += 1

    # สร้าง DataFrame และขจัดรายการซ้ำ (ถ้ามี)
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=['lat', 'lng', 'time']).reset_index(drop=True)

        # จัดกลุ่มเที่ยวส่งตาม DW (ยอดเบิกจริง)
        dw_limits = dw_list if len(dw_list) > 0 else [80, 80]
        trips = []
        acc_qty_list = []
        
        curr_trip = 1
        curr_trip_qty = 0
        curr_limit = dw_limits[0] if len(dw_limits) > 0 else 80
        total_acc = 0

        for idx, row in df.iterrows():
            q = row['qty']
            if curr_trip_qty + q > curr_limit and curr_trip_qty > 0 and curr_trip < len(dw_limits):
                curr_trip += 1
                curr_trip_qty = 0
                curr_limit = dw_limits[curr_trip - 1] if curr_trip <= len(dw_limits) else 80

            curr_trip_qty += q
            total_acc += q
            trips.append(f"เที่ยวที่ {curr_trip}")
            acc_qty_list.append(total_acc)

        df['trip'] = trips
        df['acc_qty'] = acc_qty_list

    return df, dw_list, header_info


# --- MAIN APP LOGIC ---
uploaded_file = st.file_uploader("📂 กรุณาอัปโหลดไฟล์ PDF รายงานการจัดส่ง (REP115_90306.pdf)", type=["pdf"])

if uploaded_file:
    with st.spinner("กำลังประมวลผลอ่านข้อมูลตารางและพิกัดจาก PDF..."):
        df, dw_list, header_info = parse_pdf_data(uploaded_file)

    if df.empty:
        st.error("❌ ไม่สามารถดึงข้อมูลได้ กรุณาตรวจสอบว่าเป็นไฟล์เอกสาร Sprinkle PDF ที่ถูกต้อง")
    else:
        st.success(f"✅ ประมวลผลสำเร็จ! ดึงข้อมูลได้ทั้งหมด {len(df)} รายการ | ยอดจัดส่งรวม {df['qty'].sum()} ถัง | เที่ยวการส่ง {df['trip'].nunique()} เที่ยว")

        # --- ส่วนแสดง HEADERS ---
        st.subheader("📌 ข้อมูลสรุปการปฏิบัติงาน")
        c1, c2, c3 = st.columns(3)
        c1.info(f"📅 **ประจำวันที่:** {header_info['date']}")
        c2.info(f"🚛 **รหัสรถส่ง:** {header_info['truck_no']}")
        c3.info(f"👨‍✈️ **พนักงานขับรถ:** {header_info['driver']}")

        # --- ส่วนแสดง ตารางรายการจัดส่ง ---
        st.subheader("📋 ตารางรายการจัดส่งสินค้าประจำวัน (Data Table)")
        disp_df = df[['time', 'trip', 'cust_id', 'cust_name', 'qty', 'acc_qty', 'status', 'lat', 'lng']].copy()
        disp_df.columns = ['เวลาส่ง', 'เที่ยวส่ง', 'รหัสลูกค้า', 'ชื่อลูกค้า / สมาชิก', 'ยอดส่ง (ถัง)', 'ยอดส่งสะสม', 'สถานะการส่ง', 'Latitude', 'Longitude']
        st.dataframe(disp_df, use_container_width=True, height=300)

        # --- สรุปยอดตามเที่ยววิ่ง ---
        st.subheader("📊 สรุปภาพรวมแบ่งตามเที่ยวการส่ง (Trip Summary)")
        summaries = []
        for idx, (trip_name, group) in enumerate(df.groupby('trip', sort=False)):
            dw_val = dw_list[idx] if idx < len(dw_list) else group['qty'].sum()
            summaries.append({
                "เที่ยวการส่ง": trip_name,
                "จำนวนถังที่เบิก (DW)": dw_val,
                "ยอดจัดส่งจริง (ถัง)": group['qty'].sum(),
                "จำนวนจุดส่ง (จุด)": len(group),
                "จัดส่งตรงเวลา (จุด)": len(group[group['status'] == 'จัดส่งตรงเวลา']),
                "จัดส่งไม่ตรงเวลา/รอบเสริม (จุด)": len(group[group['status'] != 'จัดส่งตรงเวลา'])
            })
        st.table(pd.DataFrame(summaries))

        st.divider()

        # ---ส่วนแผนที่ MAP ANIMATION & ROUTING ---
        st.subheader("🗺️ แผนที่จำลองการวิ่งจัดส่งตามเส้นทางจริง (OSRM Map)")

        # กำหนดสีแต่ละเที่ยว
        trip_colors = {
            "เที่ยวที่ 1": "#0055FF",  # สีน้ำเงินสด
            "เที่ยวที่ 2": "#FF0055",  # สีชมพูแดง
            "เที่ยวที่ 3": "#00AA44",  # สีเขียว
            "เที่ยวที่ 4": "#AA00FF"   # สีม่วง
        }

        # คำนวณเส้นทาง OSRM
        with st.spinner("กำลังคำนวณเส้นทางถนนจริง (OSRM Routing)..."):
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
                        "time": "จบเที่ยววิ่ง", 
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

                // Mode 1: ปักหมุดทั้งหมดไว้ล่วงหน้า ชี้เมาส์แล้วโชว์ Tooltip ข้อมูล
                if (isMode1) {{
                    points.forEach((pt, idx) => {{
                        let color = pt.status === "จัดส่งตรงเวลา" ? "#00AA44" : "#FF0000";
                        let popupText = `<b>ลำดับที่ ${{idx+1}}: ${{pt.cust_name}}</b><br>` +
                                        `รหัสลูกค้า: ${{pt.cust_id}}<br>` +
                                        `เวลาส่ง: ${{pt.time}}<br>` +
                                        `ยอดส่ง: ${{pt.qty}} ถัง<br>` +
                                        `สถานะ: ${{pt.status}}`;
                        
                        let tooltipText = `${{idx+1}}. ${{pt.cust_name}} (${{pt.time}} - ${{pt.qty}}ถัง)`;

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

                    // วาดเส้นทางตามสีของเที่ยววิ่งนั้นๆ
                    const polyline = L.polyline(seg.path, {{
                        color: seg.color,
                        weight: 6,
                        opacity: 0.85
                    }}).addTo(map);
                    activePolylines.push(polyline);

                    if (currentActiveMarker) {{
                        map.removeLayer(currentActiveMarker);
                    }}

                    if (info.lat && info.lng) {{
                        let popupText = `<b>🚚 จุดส่งล่าสุด: ${{info.cust_name}}</b><br>` +
                                        `รหัสลูกค้า: ${{info.cust_id}}<br>` +
                                        `เวลาส่ง: ${{info.time}}<br>` +
                                        `ยอดส่ง: ${{info.qty}} ถัง<br>` +
                                        `เที่ยววิ่ง: ${{seg.trip}}`;

                        let tooltipText = `📍 ${{info.cust_name}} (${{info.time}} - ${{info.qty}}ถัง)`;

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

                        if (!isMode1) {{
                            let permanentMarker = L.circleMarker([info.lat, info.lng], {{
                                radius: 7,
                                color: seg.color,
                                fillColor: seg.color,
                                fillOpacity: 0.7
                            }}).addTo(map)
                            .bindPopup(popupText)
                            .bindTooltip(tooltipText, {{permanent: false, direction: 'top'}});
                            allMarkers.push(permanentMarker);
                        }}

                        map.panTo([info.lat, info.lng]);
                    }}

                    document.getElementById('status-text').innerText = `กำลังจำลองการวิ่ง: จุดที่ ${{step + 1}} / ${{segments.length}} (${{seg.trip}})`;
                    document.getElementById('info-box').innerHTML = `
                        <div style="color:${{seg.color}}; font-weight:bold; font-size:16px;">🚚 ${{seg.trip}} - จุดส่งที่ ${{step + 1}}</div>
                        <b>เวลาจัดส่ง:</b> ${{info.time || 'ไม่ระบุ'}} | 
                        <b>รหัสลูกค้า:</b> ${{info.cust_id}} | 
                        <b>ชื่อลูกค้า / สมาชิก:</b> <span style="color:#0055FF; font-weight:bold;">${{info.cust_name}}</span><br>
                        <b>ยอดส่งสินค้า:</b> <span style="color:#D32F2F; font-weight:bold;">${{info.qty || 0}} ถัง</span> | 
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
                            document.getElementById('status-text').innerText = "✅ จำลองการจัดส่งสินค้าเสร็จสิ้นเรียบร้อยแล้ว!";
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

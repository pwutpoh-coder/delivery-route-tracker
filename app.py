import streamlit as st
import pandas as pd
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
st.markdown("ดึงข้อมูลจากเอกสารสรุปการส่งสินค้าประจำวัน (Excel) พร้อมจำลองเส้นทางบนถนนจริงผ่าน OSRM")

# --- SIDEBAR: ตั้งค่าคลังสินค้า ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")

@st.cache_data(show_spinner=False)
def geocode_location(location_str):
    if not location_str or not location_str.strip():
        return None, None
        
    clean_str = location_str.strip()
    
    coord_match = re.match(r'^(-?\d+\.\d+)\s*[\s,]\s*(-?\d+\.\d+)$', clean_str)
    if coord_match:
        lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
        return (lat, lng), f"พิกัดแบบระบุเอง ({lat:.5f}, {lng:.5f})"
    
    headers = {
        "User-Agent": "SprinkleDeliveryApp/3.0 (Contact: delivery_admin@sprinkle.co.th)",
        "Accept-Language": "th,en;q=0.9"
    }
    
    search_queries = [
        clean_str,
        f"{clean_str} ประเทศไทย",
        f"{clean_str} Thailand"
    ]
    
    for query in search_queries:
        url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(query)}&format=json&limit=1&countrycodes=th"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data and len(data) > 0:
                    lat = float(data[0]['lat'])
                    lon = float(data[0]['lon'])
                    display_name = data[0].get('display_name', clean_str)
                    return (lat, lon), display_name
        except Exception:
            continue
            
    return None, None

wh_input = st.sidebar.text_input(
    "กรอกชื่อสถานที่ หรือ พิกัด (Lat, Lng):", 
    value="",
    placeholder="ตัวอย่าง: คลังสินค้า บางนา, บางนา, หรือ 13.66800, 100.61000",
    help="สามารถพิมพ์ชื่อสถานที่ภาษาไทย ภาษาอังกฤษ หรือพิกัด Lat, Lng ได้โดยตรง"
)

DEFAULT_WAREHOUSE = (13.66800, 100.61000)

if wh_input.strip():
    warehouse_coord, location_display_name = geocode_location(wh_input)
    if warehouse_coord:
        st.sidebar.success(f"📍 พบพิกัด: {warehouse_coord[0]:.5f}, {warehouse_coord[1]:.5f}")
        if location_display_name:
            st.sidebar.caption(f"🏢 **สถานที่:** {location_display_name[:60]}...")
    else:
        st.sidebar.warning("⚠️ ไม่พบพิกัดจากชื่อสถานที่นี้ (ใช้พิกัดเริ่มต้นสำรอง บางนา)")
        warehouse_coord = DEFAULT_WAREHOUSE
else:
    st.sidebar.info("ℹ️ ใช้พิกัดคลังสินค้าเริ่มต้น (13.66800, 100.61000)")
    warehouse_coord = DEFAULT_WAREHOUSE

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
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            if data.get("routes"):
                coords = data["routes"][0]["geometry"]["coordinates"]
                return [[pt[1], pt[0]] for pt in coords]
    except Exception:
        pass
    return [[p1_lat, p1_lng], [p2_lat, p2_lng]]


# --- PARSER: Sprinkle Excel Data Extraction System ---
def parse_excel_data(excel_file):
    header_info = {"date": "ไม่ระบุ", "truck_no": "ไม่ระบุ", "driver": "ไม่ระบุ"}
    dw_list = []
    re_list = []
    records = []

    raw_df = pd.read_excel(excel_file, header=None)

    # 1. สกัดข้อมูล Header (วันที่ / รถส่ง / พนักงานขับรถ)
    try:
        header_blob = " ".join(raw_df.iloc[:15].fillna("").astype(str).to_numpy().flatten())
        
        # วันที่
        d_match = re.search(r'ประจำวันที่\s*([\d/]+)', header_blob)
        if d_match:
            header_info["date"] = d_match.group(1)

        # รถส่ง
        t_match = re.search(r'รถส่ง\s*([\w\-]+)', header_blob)
        if t_match:
            header_info["truck_no"] = t_match.group(1)

        # พนักงานขับรถ
        drv_match = re.search(r'พนักงานขับรถ\s*([\d]+\s*[\u0E00-\u0E7F\s]+)', header_blob)
        if drv_match:
            driver_text = drv_match.group(1).split("พนักงานยก")[0].strip()
            header_info["driver"] = driver_text
    except Exception:
        pass

    # 2. สกัดรายการเบิก/คืน (DWS / RES)
    try:
        header_text = " ".join(raw_df.iloc[:15].fillna("").astype(str).to_numpy().flatten())
        dw_matches = re.findall(r'DWS\d+/\d+\s+(\d+)', header_text)
        for dw_val in dw_matches:
            dw_list.append(int(dw_val))

        re_matches = re.findall(r'RES\d+/\d+\s+(\d+)', header_text)
        for re_val in re_matches:
            re_list.append(int(re_val))
    except Exception:
        pass

    # 3. วนลูปอ่านข้อมูลทุกบรรทัดตั้งแต่ต้นจนจบไฟล์
    for idx in range(len(raw_df)):
        row = raw_df.iloc[idx]
        
        val_a = row.iloc[0] if 0 < len(row) else None
        val_c = row.iloc[2] if 2 < len(row) else None
        val_e = row.iloc[4] if 4 < len(row) else None
        val_f = row.iloc[5] if 5 < len(row) else None

        if pd.isna(val_e):
            continue

        str_e = str(val_e).strip()
        
        # ดึงพิกัด GPS (Lat, Lng) และ ค่าความต่าง GPS จากคอลัมน์ E (Index 4)
        gps_match = re.search(r'([1-9]\d*\.\d+)\s*,\s*([1-9]\d*\.\d+)(?:\s+([\d\.]+))?', str_e)
        if not gps_match:
            continue

        lat = float(gps_match.group(1))
        lng = float(gps_match.group(2))
        gps_diff = gps_match.group(3) if gps_match.group(3) else "0.00"

        # ดึงรหัสสมาชิกจากคอลัมน์ A (Index 0)
        cust_id = str(val_a).strip() if pd.notna(val_a) else "N/A"
        if cust_id in ["รหัสลูกค้า", "รวม", "N/A", "nan", "None"]:
            continue

        # ดึงยอดส่งสินค้า (ถัง) จากคอลัมน์ C (Index 2)
        try:
            qty = int(float(val_c)) if pd.notna(val_c) else 1
        except Exception:
            qty = 1

        # ดึงเวลาส่ง และ สถานะ จากคอลัมน์ F (Index 5)
        str_f = str(val_f).strip() if pd.notna(val_f) else ""
        time_match = re.search(r'(\d{1,2}:\d{2})', str_f)
        delivery_time = time_match.group(1) + " น." if time_match else "ไม่ระบุเวลา"

        if "จัดส่งตรงเวลา" in str_f:
            status = "จัดส่งตรงเวลา"
        elif "ไม่ตรงเวลา" in str_f:
            status = "จัดส่งไม่ตรงเวลา"
        elif "สมาชิกใหม่" in str_f:
            status = "สมาชิกใหม่"
        elif "ย้าย" in str_f:
            status = "ย้ายรอบ"
        else:
            status_clean = re.sub(r'^\d{1,2}:\d{2}\s*(น\.)?\s*', '', str_f)
            status = status_clean if status_clean else "จัดส่งตรงเวลา"

        records.append({
            "cust_id": cust_id,
            "qty": qty,
            "lat": lat,
            "lng": lng,
            "gps_diff": gps_diff,
            "time": delivery_time,
            "status": status
        })

    # 4. สร้าง DataFrame และจัดหมวดหมู่เที่ยววิ่ง (Trip) โดยไม่ลบแถวซ้ำ
    df = pd.DataFrame(records)
    if not df.empty:
        dw_limits = dw_list if len(dw_list) > 0 else [80, 80, 72]
        trips = []
        acc_qty_list = []
        
        curr_trip_idx = 0
        curr_trip_qty = 0
        total_acc = 0

        for idx, row in df.iterrows():
            q = row['qty']
            target_limit = dw_limits[curr_trip_idx] if curr_trip_idx < len(dw_limits) else 80

            # ตัดขึ้นเที่ยวใหม่เมื่อยอดสะสมเกินโควต้าของเที่ยวปัจจุบัน
            if (curr_trip_qty + q > target_limit) and (curr_trip_idx + 1 < len(dw_limits)):
                curr_trip_idx += 1
                curr_trip_qty = 0

            curr_trip_qty += q
            total_acc += q
            trips.append(f"เที่ยวที่ {curr_trip_idx + 1}")
            acc_qty_list.append(total_acc)

        df['trip'] = trips
        df['acc_qty'] = acc_qty_list

    return df, dw_list, re_list, header_info


# --- MAIN APP INTERFACE ---
uploaded_file = st.file_uploader("📂 กรุณาอัปโหลดไฟล์ Excel รายงานการจัดส่ง (REP115_XXXXX.xlsx)", type=["xlsx", "xls"])

if uploaded_file:
    with st.spinner("กำลังอ่านและประมวลผลข้อมูลจากเอกสาร Excel..."):
        df, dw_list, re_list, header_info = parse_excel_data(uploaded_file)

    if df.empty:
        st.error("❌ ไม่พบข้อมูลรายการจัดส่งในไฟล์ Excel กรุณาตรวจสอบว่าเป็นไฟล์ Sprinkle Excel ที่ถูกต้อง")
    else:
        st.success(f"✅ ประมวลผลสำเร็จ! ดึงข้อมูลได้ทั้งหมด {len(df)} รายการ | ยอดจัดส่งรวม {df['qty'].sum()} ถัง | เที่ยวการส่ง {df['trip'].nunique()} เที่ยว")

        st.subheader("📌 ข้อมูลสรุปการปฏิบัติงาน")
        c1, c2, c3 = st.columns(3)
        c1.info(f"📅 **ประจำวันที่:** {header_info['date']}")
        c2.info(f"🚛 **รหัสรถส่ง:** {header_info['truck_no']}")
        c3.info(f"👨‍✈️ **พนักงานขับรถ:** {header_info['driver']}")

        st.subheader("📋 ตารางรายการจัดส่งสินค้าประจำวัน (Data Table)")
        disp_df = df[['time', 'trip', 'cust_id', 'qty', 'acc_qty', 'status', 'lat', 'lng', 'gps_diff']].copy()
        disp_df.columns = ['เวลาส่ง', 'เที่ยวส่ง', 'รหัสสมาชิก', 'ยอดส่ง (ถัง)', 'ยอดส่งสะสม', 'สถานะการส่ง', 'Latitude', 'Longitude', 'ค่าความต่าง GPS']
        st.dataframe(disp_df, use_container_width=True, height=400)

        st.subheader("📊 สรุปภาพรวมแบ่งตามเที่ยวการส่ง (Trip Summary)")
        summaries = []
        for idx, (trip_name, group) in enumerate(df.groupby('trip', sort=False)):
            dw_val = dw_list[idx] if idx < len(dw_list) else group['qty'].sum()
            summaries.append({
                "เที่ยวการส่ง": trip_name,
                "จำนวนถังที่เบิก (DWS)": dw_val,
                "ยอดจัดส่งจริง (ถัง)": group['qty'].sum(),
                "จำนวนจุดส่ง (จุด)": len(group),
                "จัดส่งตรงเวลา (จุด)": len(group[group['status'] == 'จัดส่งตรงเวลา']),
                "จัดส่งไม่ตรงเวลา/รอบเสริม (จุด)": len(group[group['status'] != 'จัดส่งตรงเวลา'])
            })
        st.table(pd.DataFrame(summaries))

        st.divider()

        st.subheader("🗺️ แผนที่จำลองการวิ่งจัดส่งตามเส้นทางจริง (OSRM Map)")

        trip_colors = {
            "เที่ยวที่ 1": "#0055FF",
            "เที่ยวที่ 2": "#FF0055",
            "เที่ยวที่ 3": "#00AA44",
            "เที่ยวที่ 4": "#AA00FF"
        }

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
                        "time": "จบเที่ยววิ่ง", 
                        "qty": 0, 
                        "gps_diff": "0.00",
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
                
                .number-icon {{
                    background-color: #008CBA;
                    color: white;
                    border: 2px solid white;
                    border-radius: 50%;
                    text-align: center;
                    font-weight: bold;
                    font-size: 13px;
                    line-height: 24px;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.4);
                }}
            </style>
        </head>
        <body>
            <div class="legend">
                <div class="legend-item"><span class="color-box" style="background:#0055FF;"></span> เที่ยวที่ 1 (สีน้ำเงิน)</div>
                <div class="legend-item"><span class="color-box" style="background:#FF0055;"></span> เที่ยวที่ 2 (สีชมพูแดง)</div>
                <div class="legend-item"><span class="color-box" style="background:#00AA44;"></span> เที่ยวที่ 3 (สีเขียว)</div>
            </div>
            <div class="controls">
                <button onclick="startAnimation()">▶️ เริ่มเล่น (Play)</button>
                <button onclick="pauseAnimation()">⏸️ หยุดพัก (Pause)</button>
                <button onclick="resetAnimation()">🔄 รีเซ็ต (Reset)</button>
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

                L.marker(warehouse).addTo(map)
                    .bindTooltip("🏢 คลังสินค้าหลัก", {{permanent: false, direction: 'top'}});

                let allMarkers = [];
                let activePolylines = [];
                let currentStep = 0;
                let animTimer = null;
                let currentActiveMarker = null;

                if (isMode1) {{
                    points.forEach((pt, idx) => {{
                        let seqNumber = idx + 1;
                        let customIcon = L.divIcon({{
                            className: 'number-icon',
                            html: String(seqNumber),
                            iconSize: [28, 28],
                            iconAnchor: [14, 14]
                        }});

                        let marker = L.marker([pt.lat, pt.lng], {{ icon: customIcon }}).addTo(map);
                        allMarkers.push(marker);
                    }});
                }}

                function renderStep(step) {{
                    if (step >= segments.length) return;

                    const seg = segments[step];
                    const info = seg.info;
                    const seqNumber = step + 1;

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
                        let dynamicIcon = L.divIcon({{
                            className: 'number-icon',
                            html: String(seqNumber),
                            iconSize: [32, 32],
                            iconAnchor: [16, 16]
                        }});

                        currentActiveMarker = L.marker([info.lat, info.lng], {{ icon: dynamicIcon }}).addTo(map);

                        if (!isMode1) {{
                            let permanentMarker = L.marker([info.lat, info.lng], {{ icon: dynamicIcon }}).addTo(map);
                            allMarkers.push(permanentMarker);
                        }}

                        map.panTo([info.lat, info.lng]);
                    }}

                    document.getElementById('status-text').innerText = `กำลังจำลองการวิ่ง: จุดที่ ${{seqNumber}} / ${{segments.length}} (${{seg.trip}})`;
                    
                    document.getElementById('info-box').innerHTML = `
                        <div style="color:${{seg.color}}; font-weight:bold; font-size:16px;">🚚 ${{seg.trip}} - จุดส่งลำดับที่ ${{seqNumber}}</div>
                        <b>เวลาจัดส่ง:</b> ${{info.time || 'ไม่ระบุ'}} | 
                        <b>รหัสสมาชิก:</b> <span style="color:#0055FF; font-weight:bold;">${{info.cust_id}}</span> | 
                        <b>ยอดส่งสินค้า:</b> <span style="color:#D32F2F; font-weight:bold;">${{info.qty || 0}} ถัง</span><br>
                        <b>ค่าความต่าง GPS:</b> ${{info.gps_diff || '0.00'}} | 
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

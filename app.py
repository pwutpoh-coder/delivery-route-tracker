import json
import re
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
import pandas as pd
import requests
import streamlit as st

# --- ตั้งค่าหน้าตาแอปพลิเคชัน ---
st.set_page_config(
    page_title="ระบบวิเคราะห์และติดตามเส้นทางส่งสินค้า Sprinkle",
    page_icon="🚚",
    layout="wide",
)

st.title(
    "🚚 ระบบวิเคราะห์และเปรียบเทียบเส้นทางส่งสินค้า (Sprinkle Delivery Inspector)"
)
st.markdown(
    "เปรียบเทียบเส้นทางระหว่าง **แบบที่ 1 (ตามเวลาจริง)** และ **แบบที่ 2"
    " (ปรับปรุงระยะทางสั้นที่สุด)** พร้อมสรุปผลการเปรียบเทียบและการสลับลำดับจุดส่ง"
)

# --- SIDEBAR: ตั้งค่าคลังสินค้าและการจัดการข้อมูล ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")

warehouse_options = {
    "สาขากรุงเทพกรีฑา": (13.743777, 100.673184),
    "สาขากิ่งแก้ว": (13.614988, 100.700414),
    "สาขาดอนเมือง": (13.949959, 100.612249),
    "สาขาบางบัวทอง": (13.909905, 100.407209),
    "สาขาบางพลี": (13.593901, 100.80256),
    "สาขาบุคคโล": (13.698775, 100.487137),
    "สาขาปทุมธานี": (14.037360, 100.606717),
    "สาขาประชาชื่น": (13.837436, 100.538753),
    "สาขาประเวศ": (13.711951, 100.689231),
    "สาขาปากเกร็ด": (13.937801, 100.507829),
    "สาขาพระราม 2": (13.612861, 100.384407),
    "สาขาพระราม 3": (13.684123, 100.548952),
    "สาขาพุทธมณฑลสาย1": (13.729497, 100.428533),
    "สาขารามอินทรา": (13.832754, 100.714387),
    "สาขาราษฎร์บูรณะ": (13.684947, 100.496656),
    "สาขาวังน้อย": (14.270937, 100.756769),
    "สาขาสำโรง": (13.660759, 100.593191),
    "สาขาสุขุมวิท 50": (13.699439, 100.587817),
    "อื่นๆ (ระบุพิกัดเอง)": None,
}

selected_wh_name = st.sidebar.selectbox(
    "เลือกสาขาคลังสินค้า:", list(warehouse_options.keys())
)

if selected_wh_name == "อื่นๆ (ระบุพิกัดเอง)":
    wh_input = st.sidebar.text_input(
        "กรอกพิกัด (Lat, Lng) หรือชื่อสถานที่:",
        value="",
        placeholder="ตัวอย่าง: 13.66800, 100.61000",
    )
    if wh_input.strip():
        coord_match = re.match(
            r"^(-?\d+\.\d+)\s*[\s,]\s*(-?\d+\.\d+)$", wh_input.strip()
        )
        if coord_match:
            warehouse_coord = (
                float(coord_match.group(1)),
                float(coord_match.group(2)),
            )
            st.sidebar.success(
                f"พบพิกัด: {warehouse_coord[0]:.5f}, {warehouse_coord[1]:.5f}"
            )
        else:
            warehouse_coord = (13.66800, 100.61000)
            st.sidebar.info(
                "ใช้พิกัดเริ่มต้นสำรอง เนื่องจากรูปแบบพิกัดไม่ถูกต้อง"
            )
    else:
        warehouse_coord = (13.66800, 100.61000)
        st.sidebar.info("ใช้พิกัดเริ่มต้นสำรอง (บางนา)")
else:
    warehouse_coord = warehouse_options[selected_wh_name]
    st.sidebar.success(
        f"เลือก {selected_wh_name} (พิกัด: {warehouse_coord[0]:.5f}, {warehouse_coord[1]:.5f})"
    )

st.sidebar.divider()

st.sidebar.header("🔄 จัดการข้อมูล")
if st.sidebar.button(
    "🗑️ ล้างข้อมูล / นำเข้าไฟล์ใหม่", use_container_width=True
):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

st.sidebar.header("🎬 การตั้งค่าการจำลองเส้นทาง")
anim_speed_ms = st.sidebar.slider(
    "ความเร็วการจำลอง (มิลลิวินาที/จุด)",
    min_value=100,
    max_value=3000,
    value=600,
    step=100,
)


# --- FUNCTION: Haversine Distance ---
def haversine(lat1, lon1, lat2, lon2):
    r = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


# --- FUNCTION: ดึงเส้นทางถนนจริงและระยะทางจาก OSRM ---
@st.cache_data(show_spinner=False)
def get_osrm_route(p1_lat, p1_lng, p2_lat, p2_lng):
    url = f"http://router.project-osrm.org/route/v1/driving/{p1_lng},{p1_lat};{p2_lng},{p2_lat}?overview=full&geometries=geojson"
    try:
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            if data.get("routes"):
                route = data["routes"][0]
                coords = route["geometry"]["coordinates"]
                distance_km = route["distance"] / 1000.0
                return [[pt[1], pt[0]] for pt in coords], distance_km
    except Exception:
        pass

    dist = haversine(p1_lat, p1_lng, p2_lat, p2_lng)
    return [[p1_lat, p1_lng], [p2_lat, p2_lng]], dist


# --- PARSER: Sprinkle Excel Data Extraction ---
def parse_excel_data(excel_file):
    header_info = {"date": "ไม่ระบุ", "truck_no": "ไม่ระบุ", "driver": "ไม่ระบุ"}
    raw_df = pd.read_excel(excel_file, header=None)

    try:
        header_blob = " ".join(
            raw_df.iloc[:15].fillna("").astype(str).to_numpy().flatten()
        )
        d_match = re.search(r"ประจำวันที่\s*([\d/]+)", header_blob)
        if d_match:
            header_info["date"] = d_match.group(1)

        t_match = re.search(r"รถส่ง\s*([\w\-]+)", header_blob)
        if t_match:
            header_info["truck_no"] = t_match.group(1)

        drv_match = re.search(
            r"พนักงานขับรถ\s*([\d]+\s*[\u0E00-\u0E7F\s]+)", header_blob
        )
        if drv_match:
            driver_text = drv_match.group(1).split("พนักงานยก")[0].strip()
            header_info["driver"] = driver_text
    except Exception:
        pass

    dw_records = []
    re_records = []

    for idx in range(len(raw_df)):
        row = raw_df.iloc[idx]
        col_a = (
            str(row.iloc[0]).strip()
            if 0 < len(row) and pd.notna(row.iloc[0])
            else ""
        )
        col_d = row.iloc[3] if 3 < len(row) and pd.notna(row.iloc[3]) else 0

        try:
            qty_val = int(float(col_d))
        except Exception:
            qty_val = 0

        if "DW" in col_a.upper():
            num_match = re.search(r"(\d+)$", col_a)
            sort_key = int(num_match.group(1)) if num_match else idx
            dw_records.append(
                {"sort_key": sort_key, "qty": qty_val, "raw_text": col_a}
            )

        elif "RE" in col_a.upper():
            num_match = re.search(r"(\d+)$", col_a)
            sort_key = int(num_match.group(1)) if num_match else idx
            re_records.append(
                {"sort_key": sort_key, "qty": qty_val, "raw_text": col_a}
            )

    dw_records = sorted(dw_records, key=lambda x: x["sort_key"])
    re_records = sorted(re_records, key=lambda x: x["sort_key"])

    trip_quotas = []
    for i, dw in enumerate(dw_records):
        dw_q = dw["qty"]
        re_q = re_records[i]["qty"] if i < len(re_records) else 0
        net_qty = max(0, dw_q - re_q)
        trip_quotas.append(
            {
                "trip_no": i + 1,
                "dws_qty": dw_q,
                "res_qty": re_q,
                "net_qty": net_qty,
                "dw_text": dw["raw_text"],
            }
        )

    if not trip_quotas:
        trip_quotas = [
            {
                "trip_no": 1,
                "dws_qty": 80,
                "res_qty": 0,
                "net_qty": 80,
                "dw_text": "DEFAULT",
            }
        ]

    records = []
    for idx in range(len(raw_df)):
        row = raw_df.iloc[idx]

        col_a = row.iloc[0] if 0 < len(row) else None
        col_c = row.iloc[2] if 2 < len(row) else None
        col_e = row.iloc[4] if 4 < len(row) else None
        col_f = row.iloc[5] if 5 < len(row) else None

        if pd.isna(col_e):
            continue

        str_e = str(col_e).strip()

        gps_match = re.search(
            r"([1-9]\d*\.\d{5,})\s*,\s*([1-9]\d*\.\d{5,})(?:\s+([\d,]+\.?\d*))?",
            str_e,
        )
        if not gps_match:
            gps_match = re.search(
                r"([1-9]\d*\.\d+)\s*[\s,]\s*([1-9]\d*\.\d+)(?:\s+([\d,]+\.?\d*))?",
                str_e,
            )
            if not gps_match:
                continue

        lat = float(gps_match.group(1))
        lng = float(gps_match.group(2))

        if not (5.0 <= lat <= 21.0 and 97.0 <= lng <= 106.0):
            continue

        raw_diff_str = gps_match.group(3) if gps_match.group(3) else "0.0"
        try:
            gps_diff_val = float(raw_diff_str.replace(",", ""))
        except Exception:
            gps_diff_val = 0.0

        gps_diff_str = f"{gps_diff_val:.2f}"

        cust_id = str(col_a).strip() if pd.notna(col_a) else "N/A"
        if (
            cust_id in ["รหัสลูกค้า", "รวม", "N/A", "nan", "None"]
            or "DW" in cust_id.upper()
            or "RE" in cust_id.upper()
        ):
            continue

        try:
            if pd.notna(col_c) and str(col_c).strip() != "":
                qty = int(float(col_c))
            else:
                qty = 0
        except Exception:
            qty = 0

        str_f = str(col_f).strip() if pd.notna(col_f) else ""

        is_extra_trip = "รอบเสริม" in str_f
        is_cannot_calc = (
            "ไม่สามารถคำนวณได้" in str_f or "คำนวณไม่ได้" in str_f
        )
        is_new_member = "สมาชิกใหม่" in str_f
        is_moved_trip = "ย้ายรอบ" in str_f

        time_match = re.search(r"(\d{1,2}:\d{2}\s*น\.)", str_f)
        if not time_match:
            time_match = re.search(r"(\d{1,2}:\d{2})", str_f)
            delivery_time = (
                time_match.group(1) + " น." if time_match else "ไม่ระบุเวลา"
            )
        else:
            delivery_time = time_match.group(1)

        time_sort_key = (
            time_match.group(1) if time_match else f"99:{idx:02d}"
        )

        status_part = re.sub(
            r"^\d{1,2}:\d{2}\s*(น\.)?\s*", "", str_f
        ).strip()
        if not status_part:
            status_part = "จัดส่งตรงเวลา"

        status = status_part

        lat_str = (
            f"{lat:.5f}" if len(str(lat).split(".")[1]) < 5 else str(lat)
        )
        lng_str = (
            f"{lng:.5f}" if len(str(lng).split(".")[1]) < 5 else str(lng)
        )

        records.append(
            {
                "excel_idx": idx,
                "cust_id": cust_id,
                "qty": qty,
                "lat": lat,
                "lng": lng,
                "lat_display": lat_str,
                "lng_display": lng_str,
                "gps_diff": gps_diff_str,
                "gps_diff_num": gps_diff_val,
                "time": delivery_time,
                "time_key": time_sort_key,
                "status": status,
                "is_extra_trip": is_extra_trip,
                "is_cannot_calc": is_cannot_calc,
                "is_new_member": is_new_member,
                "is_moved_trip": is_moved_trip,
            }
        )

    df_raw = pd.DataFrame(records)
    if not df_raw.empty:
        df_raw = df_raw.sort_values(
            by=["time_key", "excel_idx"]
        ).reset_index(drop=True)

        assigned_records = []
        curr_trip_idx = 0
        curr_trip_sum = 0
        total_acc = 0

        for r in df_raw.to_dict("records"):
            if curr_trip_idx >= len(trip_quotas):
                curr_trip_idx = len(trip_quotas) - 1

            target_net = trip_quotas[curr_trip_idx]["net_qty"]

            remaining_needed = target_net - curr_trip_sum
            if (
                r["qty"] > remaining_needed
                and curr_trip_idx + 1 < len(trip_quotas)
                and remaining_needed > 0
            ):
                r1 = r.copy()
                r1["qty"] = remaining_needed
                r1["trip"] = f"เที่ยวที่ {curr_trip_idx + 1}"
                curr_trip_sum += remaining_needed
                total_acc += remaining_needed
                r1["acc_qty"] = total_acc
                assigned_records.append(r1)

                remainder_qty = r["qty"] - remaining_needed
                curr_trip_idx += 1
                curr_trip_sum = 0

                while remainder_qty > 0 and curr_trip_idx < len(trip_quotas):
                    next_target = trip_quotas[curr_trip_idx]["net_qty"]
                    if (
                        remainder_qty > next_target
                        and curr_trip_idx + 1 < len(trip_quotas)
                    ):
                        r2 = r.copy()
                        r2["qty"] = next_target
                        r2["trip"] = f"เที่ยวที่ {curr_trip_idx + 1}"
                        curr_trip_sum += next_target
                        total_acc += next_target
                        r2["acc_qty"] = total_acc
                        assigned_records.append(r2)
                        remainder_qty -= next_target
                        curr_trip_idx += 1
                        curr_trip_sum = 0
                    else:
                        r2 = r.copy()
                        r2["qty"] = remainder_qty
                        r2["trip"] = f"เที่ยวที่ {curr_trip_idx + 1}"
                        curr_trip_sum += remainder_qty
                        total_acc += remainder_qty
                        r2["acc_qty"] = total_acc
                        assigned_records.append(r2)
                        remainder_qty = 0
            else:
                r["trip"] = f"เที่ยวที่ {curr_trip_idx + 1}"
                curr_trip_sum += r["qty"]
                total_acc += r["qty"]
                r["acc_qty"] = total_acc
                assigned_records.append(r)

                if (
                    curr_trip_sum >= target_net
                    and curr_trip_idx + 1 < len(trip_quotas)
                ):
                    curr_trip_idx += 1
                    curr_trip_sum = 0

        df = pd.DataFrame(assigned_records)
    else:
        df = df_raw

    return df, trip_quotas, header_info


# --- MAIN APP INTERFACE ---
uploaded_file = st.file_uploader(
    "📂 กรุณาอัปโหลดไฟล์ Excel รายงานการจัดส่ง (REP115_XXXXX.xlsx)",
    type=["xlsx", "xls"],
)

if uploaded_file:
    with st.spinner("กำลังอ่านและประมวลผลข้อมูลจากเอกสาร Excel..."):
        df, trip_quotas, header_info = parse_excel_data(uploaded_file)

    if df.empty:
        st.error(
            "❌ ไม่พบข้อมูลรายการจัดส่งในไฟล์ Excel"
            " กรุณาตรวจสอบรูปแบบคอลัมน์ A, C, E และ F อีกครั้ง"
        )
    else:
        st.success(
            f"✅ ประมวลผลสำเร็จ! ดึงข้อมูลได้ทั้งหมด {len(df)} รายการ |"
            f" ยอดจัดส่งรวม {df['qty'].sum()} ถัง | จำนวนเที่ยวการส่ง"
            f" {len(trip_quotas)} เที่ยว"
        )

        # สร้างแท็บตามโจทย์: Tab 1 (ตามเวลาจริง), Tab 2 (แบบไม่เรียงตามเวลา/Optimized), Tab 3 (สรุปเปรียบเทียบ)
        tab1, tab2, tab3 = st.tabs([
            "📊 1. แผนที่และเส้นทางตามเวลาจริง (Chronological)",
            "🚀 2. แผนที่และเส้นทางแบบปรับปรุงระยะทาง (Optimized)",
            "📋 3. สรุปเปรียบเทียบและลำดับที่เปลี่ยนแปลง",
        ])

        trip_colors = {
            "เที่ยวที่ 1": "#0055FF",
            "เที่ยวที่ 2": "#FF0055",
            "เที่ยวที่ 3": "#00AA44",
            "เที่ยวที่ 4": "#AA00FF",
        }

        # --- TAB 1: ตามเวลาจริง ---
        with tab1:
            st.subheader(
                "📌 แผนที่และเส้นทางรูปแบบการจัดส่งตามระยะเวลาตามจริง"
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.info(f"📅 **ประจำวันที่:** {header_info['date']}")
            c2.info(f"🚛 **รหัสรถส่ง:** {header_info['truck_no']}")
            c3.info(f"👨‍✈️ **พนักงานขับรถ:** {header_info['driver']}")

            with st.spinner("กำลังคำนวณเส้นทางตามเวลาจริง..."):
                segments_data_1 = []
                grouped = df.groupby("trip", sort=False)
                trip_distances_1 = {}
                point_counter = 0
                row_inc_dist_1 = []
                last_time_dt = None

                for trip_name, group in grouped:
                    pts = (
                        [warehouse_coord]
                        + list(zip(group["lat"], group["lng"]))
                        + [warehouse_coord]
                    )
                    records_list = group.to_dict("records")
                    total_trip_dist = 0.0

                    for i in range(len(pts) - 1):
                        p1, p2 = pts[i], pts[i + 1]
                        road_path, dist_km = get_osrm_route(
                            p1[0], p1[1], p2[0], p2[1]
                        )
                        total_trip_dist += dist_km

                        if i < len(records_list):
                            info = records_list[i]
                            info["point_idx"] = point_counter
                            point_counter += 1
                            row_inc_dist_1.append(round(dist_km, 2))
                        else:
                            info = {
                                "cust_id": "WH-001",
                                "time": "จบเที่ยววิ่ง",
                                "qty": 0,
                                "gps_diff": "0.00",
                                "gps_diff_num": 0.0,
                                "status": "วิ่งกลับเข้าคลังเรียบร้อย",
                                "point_idx": None,
                            }
                        info["trip"] = trip_name
                        info["seg_dist_km"] = round(dist_km, 2)
                        segments_data_1.append({
                            "trip": trip_name,
                            "color": trip_colors.get(trip_name, "#0055FF"),
                            "path": road_path,
                            "info": info,
                            "dist_km": round(dist_km, 2),
                        })
                    trip_distances_1[trip_name] = round(total_trip_dist, 2)

                total_dist_1 = round(sum(trip_distances_1.values()), 2)
            c4.success(
                f"📏 **ระยะทางรวม (ตามเวลาจริง):** {total_dist_1:.2f} กม."
            )

            df_records_1 = df.to_dict("records")
            for idx, r in enumerate(df_records_1):
                r["color"] = trip_colors.get(r.get("trip"), "#0055FF")
                r["point_idx"] = idx

            points_json_1 = json.dumps(df_records_1, ensure_ascii=False)
            segments_json_1 = json.dumps(segments_data_1, ensure_ascii=False)
            wh_json = json.dumps(warehouse_coord)

            map_html_1 = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
                <style>
                    #map1 {{ width: 100%; height: 540px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
                    #top-banner1 {{ background: linear-gradient(135deg, #1e3d59, #17b978); color: white; padding: 12px 18px; border-radius: 8px; margin-bottom: 12px; font-family: sans-serif; }}
                    .controls {{ margin-bottom: 10px; font-family: sans-serif; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
                    button {{ padding: 8px 16px; background-color: #008CBA; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: bold; }}
                    button:hover {{ background-color: #005f73; }}
                    .timeline-container {{ width: 100%; display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-family: sans-serif; background: #eef2f5; padding: 8px 12px; border-radius: 6px; box-sizing: border-box; }}
                    .timeline-slider {{ flex-grow: 1; height: 8px; cursor: pointer; accent-color: #0055FF; }}
                    #info-box1 {{ margin-top: 10px; padding: 12px 16px; background: #f8f9fa; border-left: 6px solid #008CBA; font-family: sans-serif; border-radius: 4px; font-size: 14px; line-height: 1.6; color: #333; }}
                    .number-icon {{ color: #FFFFFF !important; border: 2px solid #FFFFFF !important; border-radius: 50% !important; text-align: center !important; font-weight: bold !important; font-size: 11px !important; line-height: 22px !important; width: 26px !important; height: 26px !important; display: flex !important; align-items: center !important; justify-content: center !important; box-sizing: border-box !important; box-shadow: 0 2px 6px rgba(0,0,0,0.6); }}
                    .number-icon-active {{ transform: scale(1.6) !important; z-index: 1000 !important; box-shadow: 0 0 14px #FFD700, 0 4px 10px rgba(0,0,0,0.8) !important; }}
                </style>
            </head>
            <body>
                <div id="top-banner1">
                    <div style="font-size: 12px; color: #ffeb3b; font-weight: bold; margin-bottom: 3px;">📍 พิกัดกำลังเดินทาง (ตามเวลาจริง):</div>
                    <div id="banner-content1" style="font-size: 14px; font-weight: bold;">กำลังโหลด...</div>
                </div>
                <div class="controls">
                    <button onclick="startAnim1()">▶️ เล่น (Play)</button>
                    <button onclick="pauseAnim1()">⏸️ หยุด (Pause)</button>
                    <button onclick="resetAnim1()">🔄 รีเซ็ต (Reset)</button>
                    <span id="status-text1" style="font-weight: bold; font-family: sans-serif; color: #2c3e50;">พร้อมจำลอง...</span>
                </div>
                <div class="timeline-container">
                    <span style="font-weight:bold; font-size:13px;">⏱️ ลำดับเวลา:</span>
                    <input type="range" id="slider1" class="timeline-slider" min="0" max="{max(len(segments_data_1)-1, 0)}" value="0" oninput="onSlide1(this.value)">
                    <span id="slider-label1" style="font-weight:bold; font-size:12px; background:#fff; padding:4px 10px; border-radius:4px; border:1px solid #ccc;">จุดที่ 1</span>
                </div>
                <div id="map1"></div>
                <div id="info-box1">รายละเอียดจุดส่ง</div>
                <script>
                    const pts1 = {points_json_1};
                    const segs1 = {segments_json_1};
                    const wh1 = {wh_json};
                    let curStep1 = 0, timer1 = null, isPlay1 = false, activeMk1 = null;

                    const map1 = L.map('map1').setView([wh1[0], wh1[1]], 13);
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: '© OpenStreetMap' }}).addTo(map1);
                    L.marker(wh1).addTo(map1).bindTooltip("🏢 คลังสินค้าหลัก");

                    let activePolylines1 = [], stepMarkers1 = [];

                    function createMkIcon(num, col) {{
                        return L.divIcon({{ className: '', html: `<div class="number-icon" style="background-color: ${{col}};">${{num}}</div>`, iconSize: [26,26], iconAnchor: [13,13] }});
                    }}

                    function updateStep1(idx) {{
                        if(idx < 0 || idx >= segs1.length) return;
                        curStep1 = idx;
                        let seg = segs1[curStep1];
                        let info = seg.info;
                        document.getElementById('slider1').value = curStep1;

                        document.getElementById('banner-content1').innerHTML = `จุดที่ ${{info.point_idx !== null ? info.point_idx+1 : curStep1+1}} (${{info.trip}}) | เวลา: <b>${{info.time}}</b> | รหัส: <span style="color:#64ffda;">${{info.cust_id}}</span> | ยอด: ${{info.qty}} ถัง`;
                        document.getElementById('slider-label1').innerText = `จุดที่ ${{info.point_idx !== null ? info.point_idx+1 : curStep1+1}} (${{info.time}})`;

                        activePolylines1.forEach(p => map1.removeLayer(p));
                        activePolylines1 = [];
                        stepMarkers1.forEach(m => {{ if(m) map1.removeLayer(m); }});
                        stepMarkers1 = [];

                        let accDist = 0;
                        for(let i=0; i<=curStep1; i++) {{
                            let s = segs1[i];
                            accDist += s.dist_km;
                            let pl = L.polyline(s.path, {{ color: s.color, weight: 5, opacity: 0.85 }}).addTo(map1);
                            activePolylines1.push(pl);
                            if(s.info && s.info.point_idx !== null && s.info.point_idx !== undefined) {{
                                let pIdx = s.info.point_idx;
                                let pInfo = pts1[pIdx];
                                if(pInfo && !stepMarkers1[pIdx]) {{
                                    let mk = L.marker([pInfo.lat, pInfo.lng], {{ icon: createMkIcon(pIdx+1, pInfo.color) }}).addTo(map1);
                                    stepMarkers1[pIdx] = mk;
                                }}
                            }}
                        }}

                        document.getElementById('info-box1').innerHTML = `<b>🚛 ${{seg.trip}} | จุดที่ ${{info.point_idx !== null ? info.point_idx+1 : '-'}}</b><br>🕒 เวลา: ${{info.time}} | 👤 รหัสลูกค้า: <b>${{info.cust_id}}</b> | 📦 ยอดส่ง: <b>${{info.qty}} ถัง</b><br>📏 ระยะทางช่วงนี้: <b>${{seg.dist_km}} กม.</b> | 🛣️ ระยะทางสะสม: <b>${{accDist.toFixed(2)}} กม.</b> | 📌 สถานะ: ${{info.status}}`;
                        if(seg.path.length > 0) map1.panTo(seg.path[seg.path.length - 1]);
                    }}

                    function nextStep1() {{
                        if(curStep1 < segs1.length - 1) {{ curStep1++; updateStep1(curStep1); }}
                        else {{ pauseAnim1(); document.getElementById('status-text1').innerText = "🏁 จบการจำลอง"; }}
                    }}
                    function startAnim1() {{ if(isPlay1) return; isPlay1=true; document.getElementById('status-text1').innerText="▶️ กำลังเล่น..."; timer1=setInterval(nextStep1, {anim_speed_ms}); }}
                    function pauseAnim1() {{ isPlay1=false; if(timer1) clearInterval(timer1); document.getElementById('status-text1').innerText="⏸️ หยุดพัก"; }}
                    function resetAnim1() {{ pauseAnim1(); curStep1=0; updateStep1(0); document.getElementById('status-text1').innerText="🔄 รีเซ็ตแล้ว"; }}
                    function onSlide1(v) {{ pauseAnim1(); updateStep1(parseInt(v)); }}

                    if(segs1.length > 0) updateStep1(0);
                </script>
            </body>
            </html>
            """
            st.components.v1.html(map_html_1, height=800, scrolling=False)

        # --- คำนวณข้อมูลแบบที่ 2 (Optimized) ล่วงหน้าสำหรับ Tab 2 และ Tab 3 ---
        optimized_trip_data = {}
        total_opt_dist_all = 0.0
        total_orig_dist_all = 0.0
        comparison_table_rows = []
        mapping_details = []

        grouped_opt = df.groupby("trip", sort=False)
        for trip_name, group in grouped_opt:
            orig_records = group.to_dict("records")
            orig_coords = (
                [warehouse_coord]
                + list(zip(group["lat"], group["lng"]))
                + [warehouse_coord]
            )

            orig_dist = 0.0
            for i in range(len(orig_coords) - 1):
                _, d = get_osrm_route(
                    orig_coords[i][0],
                    orig_coords[i][1],
                    orig_coords[i + 1][0],
                    orig_coords[i + 1][1],
                )
                orig_dist += d
            total_orig_dist_all += orig_dist

            # TSP Nearest Neighbor
            unvisited = orig_records.copy()
            current_pos = warehouse_coord
            opt_records = []
            while unvisited:
                best_idx = 0
                min_d = float("inf")
                for idx, pt in enumerate(unvisited):
                    d = haversine(
                        current_pos[0], current_pos[1], pt["lat"], pt["lng"]
                    )
                    if d < min_d:
                        min_d = d
                        best_idx = idx
                next_item = unvisited.pop(best_idx)
                opt_records.append(next_item)
                current_pos = (next_item["lat"], next_item["lng"])

            opt_coords = (
                [warehouse_coord]
                + [(pt["lat"], pt["lng"]) for pt in opt_records]
                + [warehouse_coord]
            )
            opt_dist = 0.0
            opt_segments = []
            for i in range(len(opt_coords) - 1):
                p1, p2 = opt_coords[i], opt_coords[i + 1]
                path, d = get_osrm_route(p1[0], p1[1], p2[0], p2[1])
                opt_dist += d
                seg_info = (
                    opt_records[i]
                    if i < len(opt_records)
                    else {
                        "cust_id": "WH-001",
                        "time": "จบเที่ยว",
                        "qty": 0,
                        "status": "กลับคลัง",
                    }
                )
                opt_segments.append({
                    "trip": trip_name,
                    "color": trip_colors.get(trip_name, "#0055FF"),
                    "path": path,
                    "info": seg_info,
                    "dist_km": round(d, 2),
                })

            total_opt_dist_all += opt_dist
            optimized_trip_data[trip_name] = {
                "records": opt_records,
                "segments": opt_segments,
                "dist": round(opt_dist, 2),
            }

            diff = orig_dist - opt_dist
            pct = (diff / orig_dist * 100) if orig_dist > 0 else 0.0

            swapped_count = 0
            for idx, opt_item in enumerate(opt_records):
                orig_idx = next(
                    i
                    for i, o in enumerate(orig_records)
                    if o["cust_id"] == opt_item["cust_id"]
                )
                if idx != orig_idx:
                    swapped_count += 1
                    mapping_details.append({
                        "เที่ยวส่ง": trip_name,
                        "รหัสลูกค้า": opt_item["cust_id"],
                        "ลำดับเดิม (ตามเวลา)": orig_idx + 1,
                        "ลำดับใหม่ (Optimized)": idx + 1,
                        "สถานะการสลับ": "มีการสลับลำดับ",
                    })
                else:
                    mapping_details.append({
                        "เที่ยวส่ง": trip_name,
                        "รหัสลูกค้า": opt_item["cust_id"],
                        "ลำดับเดิม (ตามเวลา)": orig_idx + 1,
                        "ลำดับใหม่ (Optimized)": idx + 1,
                        "สถานะการสลับ": "ตำแหน่งเดิม",
                    })

            comparison_table_rows.append({
                "เที่ยวการส่ง": trip_name,
                "จำนวนจุดส่ง": len(orig_records),
                "ระยะทางเดิม (กม.)": round(orig_dist, 2),
                "ระยะทาง Optimized (กม.)": round(opt_dist, 2),
                "ระยะทางที่ลดลง (กม.)": round(diff, 2),
                "ประหยัดได้ (%)": f"{pct:.2f}%",
                "จุดที่ถูกสลับ": f"{swapped_count} จุด",
            })

        total_diff_all = total_orig_dist_all - total_opt_dist_all
        total_pct_all = (
            (total_diff_all / total_orig_dist_all * 100)
            if total_orig_dist_all > 0
            else 0.0
        )

        # รวบรวม segments และ points ทั้งหมดของแบบที่ 2 สำหรับส่งให้ Map 2
        all_opt_segments = []
        all_opt_records_flatten = []
        for t_name, data in optimized_trip_data.items():
            for seg in data["segments"]:
                all_opt_segments.append(seg)
            for rec in data["records"]:
                all_opt_records_flatten.append(rec)

        # --- TAB 2: แบบไม่เรียงตามเวลา (Optimized) ---
        with tab2:
            st.subheader("🚀 แผนที่และเส้นทางรูปแบบการส่งโดยไม่ยึดถึงลำดับเวลา")
            st.markdown(
                "จัดเรียงลำดับจุดส่งใหม่ด้วยวิธี Nearest Neighbor เพื่อให้รถวิ่งเป็นเส้นทางต่อเนื่องสั้นที่สุด"
            )

            col_b1, col_b2, col_b3 = st.columns(3)
            col_b1.metric(
                "ระยะทางเดิมรวม (แบบที่ 1)", f"{total_orig_dist_all:.2f} กม."
            )
            col_b2.metric(
                "ระยะทาง Optimized (แบบที่ 2)",
                f"{total_opt_dist_all:.2f} กม.",
                delta=f"-{total_diff_all:.2f} กม.",
                delta_color="inverse",
            )
            col_b3.metric("ประสิทธิภาพการประหยัด", f"{total_pct_all:.2f}%")

            points_json_2 = json.dumps(
                all_opt_records_flatten, ensure_ascii=False
            )
            segments_json_2 = json.dumps(all_opt_segments, ensure_ascii=False)

            map_html_2 = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
                <style>
                    #map2 {{ width: 100%; height: 540px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
                    #top-banner2 {{ background: linear-gradient(135deg, #2c3e50, #27ae60); color: white; padding: 12px 18px; border-radius: 8px; margin-bottom: 12px; font-family: sans-serif; }}
                    .controls {{ margin-bottom: 10px; font-family: sans-serif; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
                    button {{ padding: 8px 16px; background-color: #27ae60; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: bold; }}
                    button:hover {{ background-color: #219653; }}
                    .timeline-container {{ width: 100%; display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-family: sans-serif; background: #eef2f5; padding: 8px 12px; border-radius: 6px; box-sizing: border-box; }}
                    .timeline-slider {{ flex-grow: 1; height: 8px; cursor: pointer; accent-color: #27ae60; }}
                    #info-box2 {{ margin-top: 10px; padding: 12px 16px; background: #f8f9fa; border-left: 6px solid #27ae60; font-family: sans-serif; border-radius: 4px; font-size: 14px; line-height: 1.6; color: #333; }}
                    .number-icon {{ color: #FFFFFF !important; border: 2px solid #FFFFFF !important; border-radius: 50% !important; text-align: center !important; font-weight: bold !important; font-size: 11px !important; line-height: 22px !important; width: 26px !important; height: 26px !important; display: flex !important; align-items: center !important; justify-content: center !important; box-sizing: border-box !important; box-shadow: 0 2px 6px rgba(0,0,0,0.6); }}
                </style>
            </head>
            <body>
                <div id="top-banner2">
                    <div style="font-size: 12px; color: #ffeb3b; font-weight: bold; margin-bottom: 3px;">📍 พิกัดกำลังเดินทาง (เส้นทาง Optimized):</div>
                    <div id="banner-content2" style="font-size: 14px; font-weight: bold;">กำลังโหลด...</div>
                </div>
                <div class="controls">
                    <button onclick="startAnim2()">▶️ เล่น (Play)</button>
                    <button onclick="pauseAnim2()">⏸️ หยุด (Pause)</button>
                    <button onclick="resetAnim2()">🔄 รีเซ็ต (Reset)</button>
                    <span id="status-text2" style="font-weight: bold; font-family: sans-serif; color: #2c3e50;">พร้อมจำลองเส้นทาง Optimized...</span>
                </div>
                <div class="timeline-container">
                    <span style="font-weight:bold; font-size:13px;">⏱️ ลำดับ Optimized:</span>
                    <input type="range" id="slider2" class="timeline-slider" min="0" max="{max(len(all_opt_segments)-1, 0)}" value="0" oninput="onSlide2(this.value)">
                    <span id="slider-label2" style="font-weight:bold; font-size:12px; background:#fff; padding:4px 10px; border-radius:4px; border:1px solid #ccc;">จุดที่ 1</span>
                </div>
                <div id="map2"></div>
                <div id="info-box2">รายละเอียดจุดส่ง Optimized</div>
                <script>
                    const pts2 = {points_json_2};
                    const segs2 = {segments_json_2};
                    const wh2 = {wh_json};
                    let curStep2 = 0, timer2 = null, isPlay2 = false;

                    const map2 = L.map('map2').setView([wh2[0], wh2[1]], 13);
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: '© OpenStreetMap' }}).addTo(map2);
                    L.marker(wh2).addTo(map2).bindTooltip("🏢 คลังสินค้าหลัก");

                    let activePolylines2 = [], stepMarkers2 = [];

                    function createMkIcon2(num, col) {{
                        return L.divIcon({{ className: '', html: `<div class="number-icon" style="background-color: ${{col}};">${{num}}</div>`, iconSize: [26,26], iconAnchor: [13,13] }});
                    }}

                    function updateStep2(idx) {{
                        if(idx < 0 || idx >= segs2.length) return;
                        curStep2 = idx;
                        let seg = segs2[curStep2];
                        let info = seg.info;
                        document.getElementById('slider2').value = curStep2;

                        document.getElementById('banner-content2').innerHTML = `ลำดับใหม่ที่ ${{curStep2+1}} (${{seg.trip}}) | รหัสลูกค้า: <span style="color:#64ffda;">${{info.cust_id}}</span> | ยอดส่ง: ${{info.qty}} ถัง`;
                        document.getElementById('slider-label2').innerText = `ลำดับที่ ${{curStep2+1}} (${{info.cust_id}})`;

                        activePolylines2.forEach(p => map2.removeLayer(p));
                        activePolylines2 = [];
                        stepMarkers2.forEach(m => {{ if(m) map2.removeLayer(m); }});
                        stepMarkers2 = [];

                        let accDist = 0;
                        for(let i=0; i<=curStep2; i++) {{
                            let s = segs2[i];
                            accDist += s.dist_km;
                            let pl = L.polyline(s.path, {{ color: s.color, weight: 5, opacity: 0.85 }}).addTo(map2);
                            activePolylines2.push(pl);
                            if(s.info && s.info.lat && s.info.lng) {{
                                let mk = L.marker([s.info.lat, s.info.lng], {{ icon: createMkIcon2(i+1, s.color) }}).addTo(map2);
                                stepMarkers2[i] = mk;
                            }}
                        }}

                        document.getElementById('info-box2').innerHTML = `<b>🚀 ${{seg.trip}} | ลำดับการวิ่งใหม่ที่ ${{curStep2+1}}</b><br>👤 รหัสลูกค้า: <b>${{info.cust_id}}</b> | 📦 ยอดส่ง: <b>${{info.qty}} ถัง</b><br>📏 ระยะทางช่วงนี้: <b>${{seg.dist_km}} กม.</b> | 🛣️ ระยะทางสะสม (Optimized): <b>${{accDist.toFixed(2)}} กม.</b>`;
                        if(seg.path.length > 0) map2.panTo(seg.path[seg.path.length - 1]);
                    }}

                    function nextStep2() {{
                        if(curStep2 < segs2.length - 1) {{ curStep2++; updateStep2(curStep2); }}
                        else {{ pauseAnim2(); document.getElementById('status-text2').innerText = "🏁 จบการจำลอง Optimized"; }}
                    }}
                    function startAnim2() {{ if(isPlay2) return; isPlay2=true; document.getElementById('status-text2').innerText="▶️ กำลังเล่น Optimized..."; timer2=setInterval(nextStep2, {anim_speed_ms}); }}
                    function pauseAnim2() {{ isPlay2=false; if(timer2) clearInterval(timer2); document.getElementById('status-text2').innerText="⏸️ หยุดพัก"; }}
                    function resetAnim2() {{ pauseAnim2(); curStep2=0; updateStep2(0); document.getElementById('status-text2').innerText="🔄 รีเซ็ตแล้ว"; }}
                    function onSlide2(v) {{ pauseAnim2(); updateStep2(parseInt(v)); }}

                    if(segs2.length > 0) updateStep2(0);
                </script>
            </body>
            </html>
            """
            st.components.v1.html(map_html_2, height=800, scrolling=False)

        # --- TAB 3: สรุปเปรียบเทียบระยะทางและลำดับ ---
        with tab3:
            st.subheader(
                "📋 3. สรุปเปรียบเทียบระยะทางและสรุปลำดับของแบบที่ 2 เทียบกับแบบที่ 1"
            )
            st.markdown(
                "ส่วนนี้แสดงตารางเปรียบเทียบระยะทางรวม และรายละเอียดการเปลี่ยนแปลงลำดับจุดส่งของแต่ละลูกค้า"
            )

            st.markdown("### 📊 ตารางสรุปเปรียบเทียบระยะทาง (แบบที่ 1 vs แบบที่ 2)")
            comp_df = pd.DataFrame(comparison_table_rows)

            # เพิ่มแถวรวมทั้งหมด
            total_row = pd.DataFrame([{
                "เที่ยวการส่ง": "รวมทั้งหมดประจำวัน",
                "จำนวนจุดส่ง": len(df),
                "ระยะทางเดิม (กม.)": round(total_orig_dist_all, 2),
                "ระยะทาง Optimized (กม.)": round(total_opt_dist_all, 2),
                "ระยะทางที่ลดลง (กม.)": round(total_diff_all, 2),
                "ประหยัดได้ (%)": f"{total_pct_all:.2f}%",
                "จุดที่ถูกสลับ": f"{sum([int(r['จุดที่ถูกสลับ'].split()[0]) for r in comparison_table_rows])} จุด",
            }])
            comp_df = pd.concat([comp_df, total_row], ignore_index=True)
            st.table(comp_df)

            st.divider()

            st.markdown(
                "### 🔄 ตารางสรุปลำดับการจัดส่ง (เปรียบเทียบลำดับเดิม vs"
                " ลำดับใหม่ Optimized)"
            )
            mapping_df = pd.DataFrame(mapping_details)
            st.dataframe(mapping_df, use_container_width=True, hide_index=True)

            st.success(
                f"💡 **ข้อสังเกต:** การปรับเปลี่ยนเส้นทางแบบ Optimized"
                " สามารถช่วยลดระยะทางวิ่งรวมของรถส่งน้ำได้ถึง"
                f" **{total_diff_all:.2f} กม. ({total_pct_all:.2f}%)**"
                " ซึ่งช่วยประหยัดเวลาและค่าน้ำมันได้อย่างมีประสิทธิภาพ"
            )

import json
import re
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
    "🚚 ระบบวิเคราะห์และติดตามเส้นทางส่งสินค้า (Sprinkle Delivery Inspector)"
)
st.markdown(
    "ดึงข้อมูลใบเบิก (DW), ใบคืน (RE) จากคอลัมน์ A และตรวจสอบรายการจัดส่งตามจริง"
    " พร้อมคำนวณเส้นทางและระยะทางผ่าน OSRM"
)

# --- SIDEBAR: ตั้งค่าคลังสินค้าและการจัดการข้อมูล ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")


def geocode_location(location_str):
    if not location_str or not location_str.strip():
        return None, None

    clean_str = location_str.strip()
    coord_match = re.match(r"^(-?\d+\.\d+)\s*[\s,]\s*(-?\d+\.\d+)$", clean_str)
    if coord_match:
        lat, lng = float(coord_match.group(1)), float(coord_match.group(2))
        return (lat, lng), f"พิกัดแบบระบุเอง ({lat:.5f}, {lng:.5f})"

    headers = {
        "User-Agent": (
            "SprinkleDeliveryApp/3.1 (Contact: delivery_admin@sprinkle.co.th)"
        ),
        "Accept-Language": "th,en;q=0.9",
    }

    search_queries = [
        clean_str,
        f"{clean_str} ประเทศไทย",
        f"{clean_str} Thailand",
    ]

    for query in search_queries:
        url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(query)}&format=json&limit=1&countrycodes=th"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    display_name = data[0].get("display_name", clean_str)
                    return (lat, lon), display_name
        except Exception:
            continue

    return None, None


wh_input = st.sidebar.text_input(
    "กรอกชื่อสถานที่ หรือ พิกัด (Lat, Lng):",
    value="",
    placeholder="ตัวอย่าง: คลังสินค้า บางนา, บางนา, หรือ 13.66800, 100.61000",
    help="สามารถพิมพ์ชื่อสถานที่ ภาษาไทย ภาษาอังกฤษ หรือพิกัด Lat, Lng ได้โดยตรง",
)

DEFAULT_WAREHOUSE = (13.66800, 100.61000)

if wh_input.strip():
    warehouse_coord, location_display_name = geocode_location(wh_input)
    if warehouse_coord:
        st.sidebar.success(
            f"📍 พบพิกัด: {warehouse_coord[0]:.5f}, {warehouse_coord[1]:.5f}"
        )
        if location_display_name:
            st.sidebar.caption(
                f"🏢 **สถานที่:** {location_display_name[:60]}..."
            )
    else:
        st.sidebar.warning(
            "⚠️ ไม่พบพิกัดจากชื่อสถานที่นี้ (ใช้พิกัดเริ่มต้นสำรอง บางนา)"
        )
        warehouse_coord = DEFAULT_WAREHOUSE
else:
    st.sidebar.info("ℹ️ ใช้พิกัดคลังสินค้าเริ่มต้น (13.66800, 100.61000)")
    warehouse_coord = DEFAULT_WAREHOUSE

st.sidebar.divider()

st.sidebar.header("🔄 จัดการข้อมูล")
if st.sidebar.button(
    "🗑️ ล้างข้อมูล / นำเข้าไฟล์ใหม่", use_container_width=True
):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

st.sidebar.header("🎬 การตั้งค่าการจำลองเส้นทาง")
play_mode = st.sidebar.radio(
    "รูปแบบการแสดงผลบนแผนที่:",
    (
        "แบบที่ 1: แสดงหมุดครบทั้งหมดล่วงหน้า (เส้นทางวิ่งตามเวลา)",
        "แบบที่ 2: ปรากฏหมุดและเส้นทางเฉพาะจุดล่าสุดทีละจุดตามลำดับเวลา",
    ),
)

anim_speed_ms = st.sidebar.slider(
    "ความเร็วการจำลอง (มิลลิวินาที/จุด)",
    min_value=100,
    max_value=3000,
    value=600,
    step=100,
)


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
                distance_km = route["distance"] / 1000.0  # แปลงเมตรเป็นกิโลเมตร
                return [[pt[1], pt[0]] for pt in coords], distance_km
    except Exception:
        pass

    from math import asin, cos, radians, sin, sqrt

    def haversine(lat1, lon1, lat2, lon2):
        r = 6371
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = (
            sin(dlat / 2) ** 2
            + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        )
        return 2 * r * asin(sqrt(a))

    dist = haversine(p1_lat, p1_lng, p2_lat, p2_lng)
    return [[p1_lat, p1_lng], [p2_lat, p2_lng]], dist


# --- PARSER: Sprinkle Excel Data Extraction (ตามเงื่อนไขใหม่ คอลัมน์ A, D, E) ---
def parse_excel_data(excel_file):
    header_info = {"date": "ไม่ระบุ", "truck_no": "ไม่ระบุ", "driver": "ไม่ระบุ"}
    raw_df = pd.read_excel(excel_file, header=None)

    # 1. ดึงข้อมูลหัวกระดาษ (Header Info)
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

    # 2. ค้นหาใบเบิก (DW) และใบคืน (RE) จากคอลัมน์ A พร้อมจำนวนจากคอลัมน์ D
    dw_records = []  # เก็บ (sort_key, qty)
    re_records = []  # เก็บ (sort_key, qty)

    for idx in range(len(raw_df)):
        row = raw_df.iloc[idx]
        col_a = str(row.iloc[0]).strip() if 0 < len(row) and pd.notna(row.iloc[0]) else ""
        col_d = row.iloc[3] if 3 < len(row) and pd.notna(row.iloc[3]) else 0

        try:
            qty_val = int(float(col_d))
        except Exception:
            qty_val = 0

        # ตรวจสอบรูปแบบ DW (เช่น DW-----/--XXX หรือขึ้นต้นด้วย DW)
        if "DW" in col_a.upper():
            # พยายามดึงตัวเลข 3 หลักสุดท้ายหรือตัวเลขท้ายสุดมาเป็นเกณฑ์เรียงลำดับ
            num_match = re.search(r"(\d+)$", col_a)
            sort_key = int(num_match.group(1)) if num_match else idx
            dw_records.append({"sort_key": sort_key, "qty": qty_val, "raw_text": col_a})

        # ตรวจสอบรูปแบบ RE (เช่น RE-----/--XX หรือขึ้นต้นด้วย RE)
        elif "RE" in col_a.upper():
            num_match = re.search(r"(\d+)$", col_a)
            sort_key = int(num_match.group(1)) if num_match else idx
            re_records.append({"sort_key": sort_key, "qty": qty_val, "raw_text": col_a})

    # จัดเรียงตามค่าเลขท้าย (XXX) จากน้อยไปมาก เพื่อกำหนดเป็นเที่ยวที่ 1, 2, 3...
    dw_records = sorted(dw_records, key=lambda x: x["sort_key"])
    re_records = sorted(re_records, key=lambda x: x["sort_key"])

    # สร้างรายการโควตารายเที่ยว (Net Quantity = เบิก - คืน)
    trip_quotas = []
    for i, dw in enumerate(dw_records):
        dw_q = dw["qty"]
        # ค้นหาใบคืน (RE) ในเที่ยวลำดับเดียวกัน ถ้าไม่มีให้ถือว่าคืน 0
        re_q = re_records[i]["qty"] if i < len(re_records) else 0
        net_qty = max(0, dw_q - re_q)
        trip_quotas.append({
            "trip_no": i + 1,
            "dws_qty": dw_q,
            "res_qty": re_q,
            "net_qty": net_qty,
            "dw_text": dw["raw_text"],
        })

    # หากไม่พบข้อมูล DW ในเอกสารเลย ให้กำหนดค่าสำรองเริ่มต้น 1 เที่ยว
    if not trip_quotas:
        trip_quotas = [{"trip_no": 1, "dws_qty": 80, "res_qty": 0, "net_qty": 80, "dw_text": "DEFAULT"}]

    # 3. แยกแยะข้อมูลลูกค้ารายตัว (ตรวจสอบคอลัมน์ A รหัสลูกค้า, คอลัมน์ E พิกัด GPS, คอลัมน์ D เวลาส่ง)
    records = []
    for idx in range(len(raw_df)):
        row = raw_df.iloc[idx]

        col_a = row.iloc[0] if 0 < len(row) else None
        col_c = row.iloc[2] if 2 < len(row) else None
        col_d = row.iloc[3] if 3 < len(row) else None
        col_e = row.iloc[4] if 4 < len(row) else None

        if pd.isna(col_e):
            continue

        str_e = str(col_e).strip()

        # ตรวจสอบรูปแบบพิกัด GPS ในคอลัมน์ E (รองรับทั้งแบบ Lat, Lng และค่าความต่าง)
        gps_match = re.search(
            r"([1-9]\d*\.\d+)\s*,\s*([1-9]\d*\.\d+)(?:\s+([\d\.]+))?", str_e
        )
        if not gps_match:
            continue

        lat = float(gps_match.group(1))
        lng = float(gps_match.group(2))

        # กรองเฉพาะพิกัดในประเทศไทย
        if not (5.0 <= lat <= 21.0 and 97.0 <= lng <= 106.0):
            continue

        gps_diff_val = float(gps_match.group(3)) if gps_match.group(3) else 0.0
        gps_diff_str = f"{gps_diff_val:.2f}"

        # รหัสลูกค้าในคอลัมน์ A (อาจเป็นตัวเลขหรือข้อความ ข้ามหัวเรื่องหรือค่าว่าง)
        cust_id = str(col_a).strip() if pd.notna(col_a) else "N/A"
        if cust_id in ["รหัสลูกค้า", "รวม", "N/A", "nan", "None"] or "DW" in cust_id.upper() or "RE" in cust_id.upper():
            continue

        # จำนวนถังส่งในคอลัมน์ C (หรือถ้าคอลัมน์ C ว่างให้ดูคอลัมน์ D)
        try:
            qty = int(float(col_c)) if pd.notna(col_c) else 1
        except Exception:
            try:
                qty = int(float(col_d)) if pd.notna(col_d) else 1
            except Exception:
                qty = 1

        # เวลาส่งและสถานะจากคอลัมน์ D
        str_d = str(col_d).strip() if pd.notna(col_d) else ""
        time_match = re.search(r"(\d{1,2}:\d{2})", str_d)
        delivery_time = (
            time_match.group(1) + " น." if time_match else "ไม่ระบุเวลา"
        )
        time_sort_key = time_match.group(1) if time_match else f"99:{idx:02d}"

        if "จัดส่งตรงเวลา" in str_d:
            status = "จัดส่งตรงเวลา"
        elif "ไม่ตรงเวลา" in str_d:
            status = "จัดส่งไม่ตรงเวลา"
        elif "สมาชิกใหม่" in str_d:
            status = "สมาชิกใหม่"
        elif "ย้าย" in str_d:
            status = "ย้ายรอบ"
        else:
            status_clean = re.sub(r"^\d{1,2}:\d{2}\s*(น\.)?\s*", "", str_d)
            status = status_clean if status_clean else "จัดส่งตรงเวลา"

        records.append({
            "excel_idx": idx,
            "cust_id": cust_id,
            "qty": qty,
            "lat": lat,
            "lng": lng,
            "gps_diff": gps_diff_str,
            "gps_diff_num": gps_diff_val,
            "time": delivery_time,
            "time_key": time_sort_key,
            "status": status,
        })

    df = pd.DataFrame(records)
    if not df.empty:
        # เรียงลำดับตามเวลาส่งจริง
        df = df.sort_values(by=["time_key", "excel_idx"]).reset_index(drop=True)

        # ตัดรอบตามโควตาสุทธิของแต่ละเที่ยว (Net Quantity)
        trips = []
        acc_qty_list = []

        curr_trip_idx = 0
        curr_trip_qty = 0
        total_acc = 0

        for idx, row in df.iterrows():
            q = row["qty"]
            # ดึงโควตาเป้าหมายของเที่ยวปัจจุบัน
            target_limit = (
                trip_quotas[curr_trip_idx]["net_qty"]
                if curr_trip_idx < len(trip_quotas)
                else trip_quotas[-1]["net_qty"]
            )

            curr_trip_qty += q
            total_acc += q

            trips.append(f"เที่ยวที่ {curr_trip_idx + 1}")
            acc_qty_list.append(total_acc)

            # หากยอดสะสมในเที่ยวปัจจุบันครบโควตา และยังมีเที่ยวถัดไปรองรับ ให้ตัดรอบใหม่
            if (curr_trip_qty >= target_limit) and (
                curr_trip_idx + 1 < len(trip_quotas)
            ):
                curr_trip_idx += 1
                curr_trip_qty = 0

        df["trip"] = trips
        df["acc_qty"] = acc_qty_list

    # แปลงโครงสร้าง trip_quotas ให้เข้ากันกับตัวแปรเดิม (dw_list, re_list)
    dw_list = [t["dws_qty"] for t in trip_quotas]
    re_list = [t["res_qty"] for t in trip_quotas]

    return df, dw_list, re_list, header_info, trip_quotas


# --- MAIN APP INTERFACE ---
uploaded_file = st.file_uploader(
    "📂 กรุณาอัปโหลดไฟล์ Excel รายงานการจัดส่ง (REP115_XXXXX.xlsx)",
    type=["xlsx", "xls"],
)

if uploaded_file:
    with st.spinner("กำลังอ่านและประมวลผลข้อมูลจากเอกสาร Excel ตามเงื่อนไขใบเบิก/ใบคืน..."):
        df, dw_list, re_list, header_info, trip_quotas = parse_excel_data(uploaded_file)

    if df.empty:
        st.error(
            "❌ ไม่พบข้อมูลรายการจัดส่งในไฟล์ Excel"
            " กรุณาตรวจสอบรูปแบบคอลัมน์ A, D และ E อีกครั้ง"
        )
    else:
        st.success(
            f"✅ ประมวลผลสำเร็จ! ดึงข้อมูลได้ทั้งหมด {len(df)} รายการ |"
            f" ยอดจัดส่งรวม {df['qty'].sum()} ถัง | จำนวนเที่ยวการส่ง"
            f" {len(trip_quotas)} เที่ยว"
        )

        st.subheader("📌 ข้อมูลสรุปการปฏิบัติงาน")
        c1, c2, c3, c4 = st.columns(4)
        c1.info(f"📅 **ประจำวันที่:** {header_info['date']}")
        c2.info(f"🚛 **รหัสรถส่ง:** {header_info['truck_no']}")
        c3.info(f"👨‍✈️ **พนักงานขับรถ:** {header_info['driver']}")

        st.subheader("📋 ตารางรายการจัดส่งสินค้าประจำวัน (เรียงตามลำดับเวลาส่งจริง)")
        disp_df = df[[
            "time",
            "trip",
            "cust_id",
            "qty",
            "acc_qty",
            "status",
            "lat",
            "lng",
            "gps_diff",
        ]].copy()
        disp_df.columns = [
            "เวลาส่ง",
            "เที่ยวส่ง",
            "รหัสสมาชิก",
            "ยอดส่ง (ถัง)",
            "ยอดส่งสะสม",
            "สถานะการส่ง",
            "Latitude",
            "Longitude",
            "ค่าความต่าง GPS",
        ]
        st.dataframe(disp_df, use_container_width=True, height=350)

        st.divider()

        st.subheader("🗺️ แผนที่จำลองการวิ่งจัดส่งตามเส้นทางจริง (OSRM Map)")

        trip_colors = {
            "เที่ยวที่ 1": "#0055FF",
            "เที่ยวที่ 2": "#FF0055",
            "เที่ยวที่ 3": "#00AA44",
            "เที่ยวที่ 4": "#AA00FF",
        }

        with st.spinner(
            "กำลังคำนวณเส้นทางถนนจริงและระยะทางรวม (OSRM Routing)..."
        ):
            segments_data = []
            grouped = df.groupby("trip", sort=False)

            trip_distances = {}
            point_counter = 0

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

                    segments_data.append({
                        "trip": trip_name,
                        "color": trip_colors.get(trip_name, "#0055FF"),
                        "path": road_path,
                        "info": info,
                        "dist_km": round(dist_km, 2),
                    })

                trip_distances[trip_name] = round(total_trip_dist, 2)

            total_day_distance = round(sum(trip_distances.values()), 2)

        c4.success(f"📏 **ระยะทางวิ่งรวมทั้งหมด:** {total_day_distance:.2f} กม.")

        st.subheader("📊 สรุปภาพรวมแบ่งตามเที่ยวการส่ง (Trip Summary)")
        summaries = []
        for idx, t_info in enumerate(trip_quotas):
            trip_name = f"เที่ยวที่ {t_info['trip_no']}"
            group = df[df["trip"] == trip_name] if trip_name in df["trip"].values else pd.DataFrame()
            t_dist = trip_distances.get(trip_name, 0.0)

            actual_qty = group["qty"].sum() if not group.empty else 0
            point_count = len(group)
            ontime_count = len(group[group["status"] == "จัดส่งตรงเวลา"]) if not group.empty else 0
            late_count = len(group[group["status"] != "จัดส่งตรงเวลา"]) if not group.empty else 0
            gps_err_count = len(group[group["gps_diff_num"] > 100]) if not group.empty else 0

            summaries.append({
                "เที่ยวการส่ง": trip_name,
                "ใบเบิก (DW)": t_info["dw_text"],
                "ยอดเบิก (ถัง)": t_info["dws_qty"],
                "ยอดคืน (ถัง)": t_info["res_qty"],
                "ยอดส่งสุทธิ (เป้าหมาย)": t_info["net_qty"],
                "ยอดจัดส่งจริง (ถัง)": actual_qty,
                "จำนวนจุดส่ง (จุด)": point_count,
                "ระยะทางวิ่งรวม (กม.)": f"{t_dist:.2f}",
                "จัดส่งตรงเวลา (จุด)": ontime_count,
                "จัดส่งไม่ตรงเวลา (จุด)": late_count,
                "GPS คลาดเคลื่อน >100m (จุด)": gps_err_count,
            })

        # แถวสรุประดับวันรวมทั้งหมด
        total_dws = sum([t["dws_qty"] for t in trip_quotas])
        total_res = sum([t["res_qty"] for t in trip_quotas])
        total_net = sum([t["net_qty"] for t in trip_quotas])

        summaries.append({
            "เที่ยวการส่ง": "รวมทั้งหมดประจำวัน",
            "ใบเบิก (DW)": "-",
            "ยอดเบิก (ถัง)": total_dws,
            "ยอดคืน (ถัง)": total_res,
            "ยอดส่งสุทธิ (เป้าหมาย)": total_net,
            "ยอดจัดส่งจริง (ถัง)": df["qty"].sum(),
            "จำนวนจุดส่ง (จุด)": len(df),
            "ระยะทางวิ่งรวม (กม.)": f"{total_day_distance:.2f}",
            "จัดส่งตรงเวลา (จุด)": len(df[df["status"] == "จัดส่งตรงเวลา"]),
            "จัดส่งไม่ตรงเวลา (จุด)": len(df[df["status"] != "จัดส่งตรงเวลา"]),
            "GPS คลาดเคลื่อน >100m (จุด)": len(df[df["gps_diff_num"] > 100]),
        })

        st.table(pd.DataFrame(summaries))

        df_records = df.to_dict("records")
        for idx, r in enumerate(df_records):
            r["color"] = trip_colors.get(r.get("trip"), "#0055FF")
            r["point_idx"] = idx

        points_json = json.dumps(df_records, ensure_ascii=False)
        segments_json = json.dumps(segments_data, ensure_ascii=False)
        wh_json = json.dumps(warehouse_coord)
        is_mode_1 = "แบบที่ 1" in play_mode

        map_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map {{ width: 100%; height: 560px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
                .controls {{ margin-bottom: 10px; font-family: sans-serif; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
                button {{ padding: 8px 16px; background-color: #008CBA; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: bold; transition: 0.2s; }}
                button:hover {{ background-color: #005f73; transform: scale(1.02); }}
                
                .timeline-container {{ width: 100%; display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-family: sans-serif; background: #eef2f5; padding: 8px 12px; border-radius: 6px; box-sizing: border-box; }}
                .timeline-slider {{ flex-grow: 1; height: 6px; cursor: pointer; }}
                
                #info-box {{ margin-top: 10px; padding: 12px 16px; background: #f8f9fa; border-left: 6px solid #008CBA; font-family: sans-serif; border-radius: 4px; font-size: 14px; line-height: 1.6; color: #333; }}
                .legend {{ display: flex; gap: 15px; margin-bottom: 8px; font-family: sans-serif; font-size: 13px; font-weight: bold; flex-wrap: wrap; align-items: center; }}
                .legend-item {{ display: flex; align-items: center; gap: 5px; }}
                .color-box {{ width: 14px; height: 14px; border-radius: 3px; display: inline-block; }}
                
                .leaflet-div-icon {{ background: transparent !important; border: none !important; }}
                .marker-container {{ position: relative; width: 26px; height: 26px; }}

                .number-icon {{
                    color: #FFFFFF !important;
                    border: 2px solid #FFFFFF !important;
                    border-radius: 50% !important;
                    text-align: center !important;
                    font-weight: bold !important;
                    font-size: 11px !important;
                    line-height: 22px !important;
                    width: 26px !important;
                    height: 26px !important;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.6) !important;
                    transition: transform 0.2s ease, box-shadow 0.2s ease !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    box-sizing: border-box !important;
                }}

                .number-icon-active {{
                    transform: scale(1.6) !important;
                    z-index: 1000 !important;
                    border: 2px solid #FFFFFF !important;
                    box-shadow: 0 0 14px #FFD700, 0 4px 10px rgba(0,0,0,0.8) !important;
                }}

                .marker-badge-late {{
                    position: absolute; top: -6px; right: -6px;
                    background-color: #D32F2F; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 10;
                }}

                .marker-badge-gps {{
                    position: absolute; top: -6px; left: -6px;
                    background-color: #FF9800; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 10;
                }}

                .alert-badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; color: white; margin-left: 4px; }}
                .badge-late {{ background-color: #d9534f; }}
                .badge-gps {{ background-color: #f0ad4e; color: #000; }}
            </style>
        </head>
        <body>
            <div class="legend">
                <div class="legend-item"><span class="color-box" style="background:#0055FF;"></span> เที่ยวที่ 1</div>
                <div class="legend-item"><span class="color-box" style="background:#FF0055;"></span> เที่ยวที่ 2</div>
                <div class="legend-item"><span class="color-box" style="background:#00AA44;"></span> เที่ยวที่ 3</div>
                <div class="legend-item"><span class="color-box" style="background:#AA00FF;"></span> เที่ยวที่ 4</div>
                <div style="border-left:2px solid #ccc; height:16px; margin:0 5px;"></div>
                <div class="legend-item"><span>⏰ = ส่งไม่ตรงเวลา</span></div>
                <div class="legend-item"><span>📡 = GPS ต่าง >100m</span></div>
                <div style="border-left:2px solid #ccc; height:16px; margin:0 5px;"></div>
                <div class="legend-item" style="color:#008CBA;"><span>🏁 ระยะทางรวมทั้งหมด: {total_day_distance:.2f} กม.</span></div>
            </div>

            <div class="controls">
                <button onclick="startAnimation()">▶️ เริ่มเล่น (Play)</button>
                <button onclick="pauseAnimation()">⏸️ หยุดพัก (Pause)</button>
                <button onclick="resetAnimation()">🔄 รีเซ็ต (Reset)</button>
                <span id="status-text" style="font-weight: bold; font-family: sans-serif; color: #2c3e50;">พร้อมสำหรับการจำลองเส้นทาง...</span>
            </div>

            <div class="timeline-container">
                <span style="font-weight:bold; font-size:13px;">⏱️ เลื่อนช่วงเวลา:</span>
                <input type="range" id="timeSlider" class="timeline-slider" min="0" max="{max(len(segments_data)-1, 0)}" value="0" oninput="onSliderChange(this.value)">
                <span id="slider-label" style="font-weight:bold; font-size:13px; min-width:80px; text-align:right;">จุดที่ 0 / {len(segments_data)}</span>
            </div>

            <div id="map"></div>
            <div id="info-box">📍 <b>สถานะพิกัด</b>: กดปุ่ม "เริ่มเล่น" หรือลากแถบเพื่อดูรายละเอียดระยะทางและสถานะส่ง</div>

            <script>
                const points = {points_json};
                const segments = {segments_json};
                const warehouse = {wh_json};
                const isMode1 = {str(is_mode_1).lower()};
                let currentSpeedMs = {anim_speed_ms};

                const map = L.map('map').setView([warehouse[0], warehouse[1]], 13);
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap contributors'
                }}).addTo(map);

                L.marker(warehouse).addTo(map)
                    .bindTooltip("🏢 คลังสินค้าหลัก", {{permanent: false, direction: 'top'}});

                let allMarkers = [];
                let activePolylines = [];
                let stepMarkers = [];
                let currentStep = 0;
                let animTimer = null;
                let isPlaying = false;
                let activeMarkerRef = null;

                function createTooltipHtml(info, seqNum) {{
                    let isLate = info.status && info.status.includes("ไม่ตรงเวลา");
                    let isGpsDiff = (info.gps_diff_num || parseFloat(info.gps_diff || 0)) > 100;
                    let lateBadge = isLate ? `<span class="alert-badge badge-late">⏰ ส่งไม่ตรงเวลา</span>` : '';
                    let gpsBadge = isGpsDiff ? `<span class="alert-badge badge-gps">📡 GPS ห่าง >100m</span>` : '';

                    return `
                        <div style="font-family: sans-serif; font-size: 12px; line-height: 1.4;">
                            <b>📍 จุดที่ ${{seqNum || '-'}} (${{info.trip || 'ไม่ระบุ'}})</b> ${{lateBadge}}${{gpsBadge}}<br>
                            <b>เวลา:</b> ${{info.time || '-'}}<br>
                            <b>สมาชิก:</b> <span style="color:#0055FF; font-weight:bold;">${{info.cust_id}}</span><br>
                            <b>ยอดส่ง:</b> <span style="color:#D32F2F; font-weight:bold;">${{info.qty || 0}} ถัง</span><br>
                            <b>สถานะ:</b> ${{info.status}}<br>
                            <b>ต่าง GPS:</b> ${{info.gps_diff || '0.00'}} m
                        </div>
                    `;
                }}

                function createMarkerIcon(seqNum, color, ptInfo) {{
                    let isLate = ptInfo && ptInfo.status && ptInfo.status.includes("ไม่ตรงเวลา");
                    let isGpsDiff = ptInfo && ((ptInfo.gps_diff_num || parseFloat(ptInfo.gps_diff || 0)) > 100);
                    let lateBadgeHtml = isLate ? `<div class="marker-badge-late" title="ส่งไม่ตรงเวลา">⏰</div>` : '';
                    let gpsBadgeHtml = isGpsDiff ? `<div class="marker-badge-gps" title="GPS คลาดเคลื่อน >100m">📡</div>` : '';

                    return L.divIcon({{
                        className: '',
                        html: `<div class="marker-container">${{lateBadgeHtml}}${{gpsBadgeHtml}}<div class="number-icon" style="background-color: ${{color || '#008CBA'}} !important;">${{seqNum}}</div></div>`,
                        iconSize: [26, 26],
                        iconAnchor: [13, 13]
                    }});
                }}

                if (isMode1) {{
                    points.forEach((pt, idx) => {{
                        let seqNumber = idx + 1;
                        let customIcon = createMarkerIcon(seqNumber, pt.color, pt);
                        let marker = L.marker([pt.lat, pt.lng], {{ icon: customIcon }}).addTo(map);
                        marker.bindTooltip(createTooltipHtml(pt, seqNumber), {{ direction: 'top', opacity: 0.95 }});
                        allMarkers.push(marker);
                    }});
                }}

                function highlightMarkerByInfo(info) {{
                    if (activeMarkerRef && activeMarkerRef._icon) {{
                        let innerDiv = activeMarkerRef._icon.querySelector('.number-icon');
                        if (innerDiv) innerDiv.classList.remove('number-icon-active');
                    }}
                    activeMarkerRef = null;

                    if (!info || info.point_idx === undefined || info.point_idx === null) return;
                    let target = isMode1 ? allMarkers[info.point_idx] : stepMarkers[info.point_idx];
                    if (target && target._icon) {{
                        let innerDiv = target._icon.querySelector('.number-icon');
                        if (innerDiv) innerDiv.classList.add('number-icon-active');
                        activeMarkerRef = target;
                    }}
                }}

                function updateStep(stepIndex) {{
                    if (stepIndex < 0 || stepIndex >= segments.length) return;

                    currentStep = stepIndex;
                    document.getElementById('timeSlider').value = currentStep;
                    document.getElementById('slider-label').innerText = `จุดที่ ${{currentStep + 1}} / ${{segments.length}}`;

                    activePolylines.forEach(p => map.removeLayer(p));
                    activePolylines = [];

                    if (!isMode1) {{
                        stepMarkers.forEach(m => {{ if (m) map.removeLayer(m); }});
                        stepMarkers = [];
                    }}

                    let accumulatedDistance = 0.0;
                    for (let i = 0; i <= currentStep; i++) {{
                        let seg = segments[i];
                        accumulatedDistance += (seg.dist_km || 0.0);

                        let polyline = L.polyline(seg.path, {{ color: seg.color, weight: 5, opacity: 0.85 }}).addTo(map);
                        activePolylines.push(polyline);

                        if (!isMode1 && seg.info && seg.info.point_idx !== null && seg.info.point_idx !== undefined) {{
                            let pIdx = seg.info.point_idx;
                            let ptInfo = points[pIdx];
                            if (ptInfo && !stepMarkers[pIdx]) {{
                                let seqNumber = pIdx + 1;
                                let customIcon = createMarkerIcon(seqNumber, ptInfo.color, ptInfo);
                                let marker = L.marker([ptInfo.lat, ptInfo.lng], {{ icon: customIcon }}).addTo(map);
                                marker.bindTooltip(createTooltipHtml(ptInfo, seqNumber), {{ direction: 'top', opacity: 0.95 }});
                                stepMarkers[pIdx] = marker;
                            }}
                        }}
                    }}

                    let currentSeg = segments[currentStep];
                    let info = currentSeg.info;
                    highlightMarkerByInfo(info);

                    let infoBox = document.getElementById('info-box');
                    infoBox.innerHTML = `
                        <b>🚛 ${{currentSeg.trip}} | จุดที่ ${{currentStep + 1}} จาก ${{segments.length}}</b><br>
                        <b>🕒 เวลาส่ง:</b> ${{info.time}} | <b>👤 ลูกค้า:</b> <span style="color:#0055FF; font-weight:bold;">${{info.cust_id}}</span> | <b>📦 ยอดส่ง:</b> <span style="color:#D32F2F; font-weight:bold;">${{info.qty}} ถัง</span><br>
                        <b>🚗 ระยะทางช่วงนี้:</b> <span style="color:#2E7D32; font-weight:bold;">${{currentSeg.dist_km}} กม.</span> | <b>🛣️ ระยะทางสะสมถึงจุดนี้:</b> <span style="color:#2E7D32; font-weight:bold;">${{accumulatedDistance.toFixed(2)}} กม.</span> | <b>📌 สถานะ:</b> ${{info.status}}
                    `;

                    let lastPt = currentSeg.path[currentSeg.path.length - 1];
                    if (lastPt) {{ map.panTo(lastPt); }}
                }}

                function nextStep() {{
                    if (currentStep < segments.length - 1) {{
                        currentStep++;
                        updateStep(currentStep);
                    }} else {{
                        pauseAnimation();
                        document.getElementById('status-text').innerText = "🏁 จำลองเส้นทางเสร็จสิ้น!";
                    }}
                }}

                function startAnimation() {{
                    if (isPlaying) return;
                    isPlaying = true;
                    document.getElementById('status-text').innerText = "▶️ กำลังวิ่งจำลองเส้นทาง...";
                    if (currentStep >= segments.length - 1) {{ currentStep = 0; }}
                    updateStep(currentStep);
                    animTimer = setInterval(nextStep, currentSpeedMs);
                }}

                function pauseAnimation() {{
                    isPlaying = false;
                    if (animTimer) {{ clearInterval(animTimer); animTimer = null; }}
                    document.getElementById('status-text').innerText = "⏸️ หยุดพักการจำลอง";
                }}

                function resetAnimation() {{
                    pauseAnimation();
                    currentStep = 0;
                    updateStep(0);
                    document.getElementById('status-text').innerText = "🔄 รีเซ็ตเส้นทางเรียบร้อย";
                }}

                function onSliderChange(val) {{
                    pauseAnimation();
                    updateStep(parseInt(val));
                }}

                if (segments.length > 0) {{ updateStep(0); }}
            </script>
        </body>
        </html>
        """

        st.components.v1.html(map_html, height=750, scrolling=False)

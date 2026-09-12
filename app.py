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
                distance_km = route["distance"] / 1000.0
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

        st.subheader("📌 ข้อมูลสรุปการปฏิบัติงาน")
        c1, c2, c3, c4 = st.columns(4)
        c1.info(f"📅 **ประจำวันที่:** {header_info['date']}")
        c2.info(f"🚛 **รหัสรถส่ง:** {header_info['truck_no']}")
        c3.info(f"👨‍✈️ **พนักงานขับรถ:** {header_info['driver']}")

        st.subheader("📋 ตารางรายการจัดส่งสินค้าประจำวัน")


        def get_notification_badge(row):
            notices = []
            is_special = (
                row.get("is_extra_trip")
                or row.get("is_cannot_calc")
                or row.get("is_moved_trip")
            )
            if "ไม่ตรงเวลา" in str(row["status"]):
                notices.append("จัดส่งไม่ตรงเวลา")
            elif not is_special:
                notices.append("จัดส่งตรงเวลา")

            if row["gps_diff_num"] > 100:
                notices.append(f"GPS ห่าง {row['gps_diff']}m")
            if row.get("is_extra_trip"):
                notices.append("รอบเสริม")
            if row.get("is_cannot_calc"):
                notices.append("ไม่สามารถคำนวณได้")
            if row.get("is_new_member"):
                notices.append("สมาชิกใหม่")
            if row.get("is_moved_trip"):
                notices.append("ย้ายรอบ")
            return " | ".join(notices)


        disp_df = df[[
            "time",
            "trip",
            "cust_id",
            "qty",
            "acc_qty",
            "status",
            "lat_display",
            "lng_display",
            "gps_diff",
        ]].copy()

        disp_df["การแจ้งเตือน"] = df.apply(get_notification_badge, axis=1)

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
            "สรุปการแจ้งเตือน",
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

        with st.spinner("กำลังคำนวณเส้นทางถนนจริงและระยะทางรวม..."):
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

        st.subheader("📊 สรุปภาพรวมแบ่งตามเที่ยวการส่ง")
        summaries = []
        for idx, t_info in enumerate(trip_quotas):
            trip_name = f"เที่ยวที่ {t_info['trip_no']}"
            group = (
                df[df["trip"] == trip_name]
                if trip_name in df["trip"].values
                else pd.DataFrame()
            )
            t_dist = trip_distances.get(trip_name, 0.0)

            actual_qty = group["qty"].sum() if not group.empty else 0
            point_count = len(group)
            ontime_count = (
                len(
                    group[
                        ~group["status"].str.contains("ไม่ตรงเวลา", na=False)
                    ]
                )
                if not group.empty
                else 0
            )
            late_count = (
                len(group[group["status"].str.contains("ไม่ตรงเวลา", na=False)])
                if not group.empty
                else 0
            )
            gps_err_count = (
                len(group[group["gps_diff_num"] > 100])
                if not group.empty
                else 0
            )

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
            "จัดส่งตรงเวลา (จุด)": len(
                df[~df["status"].str.contains("ไม่ตรงเวลา", na=False)]
            ),
            "จัดส่งไม่ตรงเวลา (จุด)": len(
                df[df["status"].str.contains("ไม่ตรงเวลา", na=False)]
            ),
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
                
                .filter-bar {{ margin-bottom: 10px; font-family: sans-serif; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; background: #f1f4f9; padding: 8px 12px; border-radius: 6px; }}
                .filter-btn {{ padding: 5px 12px; background-color: #e0e0e0; color: #333; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: bold; transition: 0.2s; }}
                .filter-btn.active {{ background-color: #2c3e50; color: white; }}

                .timeline-container {{ width: 100%; display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-family: sans-serif; background: #eef2f5; padding: 8px 12px; border-radius: 6px; box-sizing: border-box; }}
                .timeline-slider {{ flex-grow: 1; height: 8px; cursor: pointer; accent-color: #0055FF; transition: accent-color 0.3s ease; }}
                
                #info-box {{ margin-top: 10px; padding: 12px 16px; background: #f8f9fa; border-left: 6px solid #008CBA; font-family: sans-serif; border-radius: 4px; font-size: 14px; line-height: 1.6; color: #333; }}
                .legend {{ display: flex; gap: 12px; margin-bottom: 8px; font-family: sans-serif; font-size: 12px; font-weight: bold; flex-wrap: wrap; align-items: center; }}
                .legend-item {{ display: flex; align-items: center; gap: 4px; }}
                .color-box {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
                
                .leaflet-div-icon {{ background: transparent !important; border: none !important; }}
                .marker-container {{ position: relative; width: 28px; height: 28px; }}

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
                    position: absolute; top: -6px; right: -8px;
                    background-color: #D32F2F; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 20;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                }}

                .marker-badge-gps {{
                    position: absolute; top: -6px; left: -8px;
                    background-color: #FF9800; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 20;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                }}

                .marker-badge-extra {{
                    position: absolute; bottom: -6px; left: -8px;
                    background-color: #8E44AD; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 20;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                }}

                .marker-badge-calc {{
                    position: absolute; bottom: -6px; right: -8px;
                    background-color: #34495E; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 20;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                }}

                .marker-badge-new {{
                    position: absolute; top: 50%; left: -10px; transform: translateY(-50%);
                    background-color: #27AE60; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 20;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                }}

                .marker-badge-moved {{
                    position: absolute; top: 50%; right: -10px; transform: translateY(-50%);
                    background-color: #2980B9; color: white; border: 1.5px solid white;
                    border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                    display: flex; align-items: center; justify-content: center; z-index: 20;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                }}

                .alert-badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; color: white; margin-left: 4px; }}
            </style>
        </head>
        <body>
            <div class="legend">
                <div class="legend-item"><span class="color-box" style="background:#0055FF;"></span> เที่ยว 1</div>
                <div class="legend-item"><span class="color-box" style="background:#FF0055;"></span> เที่ยว 2</div>
                <div class="legend-item"><span class="color-box" style="background:#00AA44;"></span> เที่ยว 3</div>
                <div style="border-left:2px solid #ccc; height:14px; margin:0 2px;"></div>
                <div class="legend-item"><span style="background:#D32F2F; color:#fff; border-radius:50%; width:14px; height:14px; display:inline-flex; align-items:center; justify-content:center; font-size:9px;">!</span> ไม่ตรงเวลา</div>
                <div class="legend-item"><span style="background:#FF9800; color:#fff; border-radius:50%; width:14px; height:14px; display:inline-flex; align-items:center; justify-content:center; font-size:9px;">G</span> GPS>100m</div>
                <div class="legend-item"><span style="background:#8E44AD; color:#fff; border-radius:50%; width:14px; height:14px; display:inline-flex; align-items:center; justify-content:center; font-size:9px;">ร</span> รอบเสริม</div>
                <div class="legend-item"><span style="background:#34495E; color:#fff; border-radius:50%; width:14px; height:14px; display:inline-flex; align-items:center; justify-content:center; font-size:9px;">X</span> คำนวณไม่ได้</div>
                <div class="legend-item"><span style="background:#27AE60; color:#fff; border-radius:50%; width:14px; height:14px; display:inline-flex; align-items:center; justify-content:center; font-size:9px;">N</span> สมาชิกใหม่</div>
                <div class="legend-item"><span style="background:#2980B9; color:#fff; border-radius:50%; width:14px; height:14px; display:inline-flex; align-items:center; justify-content:center; font-size:9px;">ย</span> ย้ายรอบ</div>
            </div>

            <div class="filter-bar">
                <span style="font-weight:bold; font-size:13px;">🔍 ตัวกรองการแสดงผลแผนที่:</span>
                <button class="filter-btn active" id="btn-all" onclick="setTripFilter('ALL')">แสดงทั้งหมด</button>
                <button class="filter-btn" id="btn-trip1" onclick="setTripFilter('เที่ยวที่ 1')">เที่ยวที่ 1</button>
                <button class="filter-btn" id="btn-trip2" onclick="setTripFilter('เที่ยวที่ 2')">เที่ยวที่ 2</button>
                <button class="filter-btn" id="btn-trip3" onclick="setTripFilter('เที่ยวที่ 3')">เที่ยวที่ 3</button>
            </div>

            <div class="controls">
                <button onclick="startAnimation()">▶️ เริ่มเล่น (Play)</button>
                <button onclick="pauseAnimation()">⏸️ หยุดพัก (Pause)</button>
                <button onclick="resetAnimation()">🔄 รีเซ็ต (Reset)</button>
                <span id="status-text" style="font-weight: bold; font-family: sans-serif; color: #2c3e50;">พร้อมสำหรับการจำลองเส้นทาง...</span>
            </div>

            <div class="timeline-container">
                <span style="font-weight:bold; font-size:13px;">⏱️ ช่วงเวลา:</span>
                <input type="range" id="timeSlider" class="timeline-slider" min="0" max="{max(len(segments_data)-1, 0)}" value="0" oninput="onSliderChange(this.value)">
                <span id="slider-label" style="font-weight:bold; font-size:13px; min-width:280px; text-align:right; background:#fff; padding:3px 8px; border-radius:4px; border:1px solid #ccc;">09:00 - รหัส (จุด 1)</span>
            </div>

            <div id="map"></div>
            <div id="info-box">📍 <b>สถานะพิกัด</b>: กดปุ่ม "เริ่มเล่น" หรือลากแถบเพื่อดูรายละเอียดระยะทางและสถานะส่ง</div>

            <script>
                const points = {points_json};
                const segments = {segments_json};
                const warehouse = {wh_json};
                const isMode1 = {str(is_mode_1).lower()};
                let currentSpeedMs = {anim_speed_ms};

                let currentFilter = 'ALL';

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
                    
                    let badgesHtml = [];
                    if (isLate) badgesHtml.push(`<span class="alert-badge" style="background:#D32F2F;">${{info.status}}</span>`);
                    else if (!info.is_extra_trip && !info.is_cannot_calc && !info.is_moved_trip) badgesHtml.push(`<span class="alert-badge" style="background:#4CAF50;">จัดส่งตรงเวลา</span>`);

                    if (isGpsDiff) badgesHtml.push(`<span class="alert-badge" style="background:#FF9800; color:#000;">GPS ห่าง >100m (${{info.gps_diff}}m)</span>`);
                    if (info.is_extra_trip) badgesHtml.push(`<span class="alert-badge" style="background:#8E44AD;">รอบเสริม</span>`);
                    if (info.is_cannot_calc) badgesHtml.push(`<span class="alert-badge" style="background:#34495E;">ไม่สามารถคำนวณได้</span>`);
                    if (info.is_new_member) badgesHtml.push(`<span class="alert-badge" style="background:#27AE60;">สมาชิกใหม่</span>`);
                    if (info.is_moved_trip) badgesHtml.push(`<span class="alert-badge" style="background:#2980B9;">ย้ายรอบ</span>`);

                    return `
                        <div style="font-family: sans-serif; font-size: 12px; line-height: 1.4;">
                            <b>📍 จุดที่ ${{seqNum || '-'}} (${{info.trip || 'ไม่ระบุ'}})</b><br>
                            ${{badgesHtml.join(' ')}}<br>
                            <b>เวลา:</b> ${{info.time || '-'}}<br>
                            <b>รหัสสมาชิก:</b> <span style="color:#0055FF; font-weight:bold;">${{info.cust_id}}</span><br>
                            <b>ยอดส่ง:</b> <span style="color:#D32F2F; font-weight:bold;">${{info.qty || 0}} ถัง</span><br>
                            <b>พิกัด:</b> ${{info.lat_display}}, ${{info.lng_display}}<br>
                            <b>ค่าความต่าง GPS:</b> <b>${{info.gps_diff || '0.00'}} ม.</b>
                        </div>
                    `;
                }}

                function createMarkerIcon(seqNum, color, ptInfo) {{
                    let isLate = ptInfo && ptInfo.status && ptInfo.status.includes("ไม่ตรงเวลา");
                    let isGpsDiff = ptInfo && ((ptInfo.gps_diff_num || parseFloat(ptInfo.gps_diff || 0)) > 100);
                    
                    let lateBadgeHtml = isLate ? `<div class="marker-badge-late" title="จัดส่งไม่ตรงเวลา">!</div>` : '';
                    let gpsBadgeHtml = isGpsDiff ? `<div class="marker-badge-gps" title="GPS คลาดเคลื่อน >100m">G</div>` : '';
                    let extraBadgeHtml = ptInfo && ptInfo.is_extra_trip ? `<div class="marker-badge-extra" title="รอบเสริม">ร</div>` : '';
                    let calcBadgeHtml = ptInfo && ptInfo.is_cannot_calc ? `<div class="marker-badge-calc" title="ไม่สามารถคำนวณได้">X</div>` : '';
                    let newBadgeHtml = ptInfo && ptInfo.is_new_member ? `<div class="marker-badge-new" title="สมาชิกใหม่">N</div>` : '';
                    let movedBadgeHtml = ptInfo && ptInfo.is_moved_trip ? `<div class="marker-badge-moved" title="ย้ายรอบ">ย</div>` : '';

                    let innerHtml = `<div class="marker-container">${{lateBadgeHtml}}${{gpsBadgeHtml}}${{extraBadgeHtml}}${{calcBadgeHtml}}${{newBadgeHtml}}${{movedBadgeHtml}}<div class="number-icon" style="background-color: ${{color || '#008CBA'}} !important;">${{seqNum}}</div></div>`;

                    return L.divIcon({{
                        className: '',
                        html: innerHtml,
                        iconSize: [28, 28],
                        iconAnchor: [14, 14]
                    }});
                }}

                function initMarkers() {{
                    allMarkers.forEach(m => map.removeLayer(m));
                    allMarkers = [];

                    if (isMode1) {{
                        points.forEach((pt, idx) => {{
                            if (currentFilter === 'ALL' || pt.trip === currentFilter) {{
                                let seqNumber = idx + 1;
                                let customIcon = createMarkerIcon(seqNumber, pt.color, pt);
                                let marker = L.marker([pt.lat, pt.lng], {{ icon: customIcon }}).addTo(map);
                                marker.bindTooltip(createTooltipHtml(pt, seqNumber), {{ direction: 'top', opacity: 0.95 }});
                                allMarkers[idx] = marker;
                            }}
                        }});
                    }}
                }}

                initMarkers();

                function setTripFilter(filterName) {{
                    pauseAnimation();
                    currentFilter = filterName;

                    ['btn-all', 'btn-trip1', 'btn-trip2', 'btn-trip3'].forEach(id => {{
                        let el = document.getElementById(id);
                        if (el) el.classList.remove('active');
                    }});

                    if (filterName === 'ALL') document.getElementById('btn-all').classList.add('active');
                    else if (filterName === 'เที่ยวที่ 1') document.getElementById('btn-trip1').classList.add('active');
                    else if (filterName === 'เที่ยวที่ 2') document.getElementById('btn-trip2').classList.add('active');
                    else if (filterName === 'เที่ยวที่ 3') document.getElementById('btn-trip3').classList.add('active');

                    initMarkers();

                    let firstMatchIdx = segments.findIndex(seg => currentFilter === 'ALL' || seg.trip === currentFilter);
                    if (firstMatchIdx !== -1) {{
                        currentStep = firstMatchIdx;
                        updateStep(currentStep);
                    }}
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
                    let currentSeg = segments[currentStep];

                    if (currentFilter !== 'ALL' && currentSeg.trip !== currentFilter) {{
                        let nextValid = segments.findIndex((seg, idx) => idx >= currentStep && (currentFilter === 'ALL' || seg.trip === currentFilter));
                        if (nextValid !== -1) {{
                            currentStep = nextValid;
                            currentSeg = segments[currentStep];
                        }} else {{
                            let prevValid = segments.map((s, i) => i).reverse().find(i => currentFilter === 'ALL' || segments[i].trip === currentFilter);
                            if (prevValid !== undefined) {{
                                currentStep = prevValid;
                                currentSeg = segments[currentStep];
                            }}
                        }}
                    }}

                    let info = currentSeg.info;

                    let slider = document.getElementById('timeSlider');
                    slider.value = currentStep;
                    slider.style.accentColor = currentSeg.color;

                    let timeLabel = info.time || '-';
                    let custIdLabel = info.cust_id || '-';
                    
                    document.getElementById('slider-label').innerHTML = `<span style="color:${{currentSeg.color}}; font-weight:bold;">${{timeLabel}}</span> - <span style="color:#0055FF;">รหัส: ${{custIdLabel}}</span> (จุด ${{currentStep + 1}})`;

                    activePolylines.forEach(p => map.removeLayer(p));
                    activePolylines = [];

                    if (!isMode1) {{
                        stepMarkers.forEach(m => {{ if (m) map.removeLayer(m); }});
                        stepMarkers = [];
                    }}

                    let accumulatedDistance = 0.0;
                    for (let i = 0; i <= currentStep; i++) {{
                        let seg = segments[i];
                        if (currentFilter !== 'ALL' && seg.trip !== currentFilter) continue;

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

                    highlightMarkerByInfo(info);

                    let infoBox = document.getElementById('info-box');
                    infoBox.innerHTML = `
                        <b>🚛 ${{currentSeg.trip}} | จุดที่ ${{currentStep + 1}} จาก ${{segments.length}}</b><br>
                        <b>🕒 เวลาส่ง:</b> ${{info.time}} | <b>👤 รหัสสมาชิก:</b> <span style="color:#0055FF; font-weight:bold;">${{info.cust_id}}</span> | <b>📦 ยอดส่ง:</b> <span style="color:#D32F2F; font-weight:bold;">${{info.qty}} ถัง</span><br>
                        <b>📍 พิกัด:</b> ${{info.lat_display}}, ${{info.lng_display}} | <b>📏 ต่าง GPS:</b> <span style="color:#FF9800; font-weight:bold;">${{info.gps_diff || '0.00'}} ม.</span><br>
                        <b>🚗 ระยะทางช่วงนี้:</b> <span style="color:#2E7D32; font-weight:bold;">${{currentSeg.dist_km}} กม.</span> | <b>🛣️ ระยะทางสะสม:</b> <span style="color:#2E7D32; font-weight:bold;">${{accumulatedDistance.toFixed(2)}} กม.</span> | <b>📌 สถานะ:</b> ${{info.status}}
                    `;

                    let lastPt = currentSeg.path[currentSeg.path.length - 1];
                    if (lastPt) {{ map.panTo(lastPt); }}
                }}

                function nextStep() {{
                    let nextIdx = currentStep + 1;
                    while (nextIdx < segments.length) {{
                        if (currentFilter === 'ALL' || segments[nextIdx].trip === currentFilter) break;
                        nextIdx++;
                    }}

                    if (nextIdx < segments.length) {{
                        currentStep = nextIdx;
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
                    let firstMatchIdx = segments.findIndex(seg => currentFilter === 'ALL' || seg.trip === currentFilter);
                    currentStep = firstMatchIdx !== -1 ? firstMatchIdx : 0;
                    updateStep(currentStep);
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

        st.components.v1.html(map_html, height=800, scrolling=False)

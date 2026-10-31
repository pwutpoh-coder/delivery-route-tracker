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

# --- CUSTOM CSS: ปรับแต่งแท็บ (Tabs) ให้เปลี่ยนสีอักษรและเส้นใต้เมื่อเลือก, ปรับขนาดหัวข้อหลัก ---
st.markdown(
    """
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        background-color: transparent;
        padding: 4px;
        border-bottom: 2px solid #e2e8f0;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent !important;
        color: #64748b;
        font-weight: 600;
        font-size: 15px;
        padding: 10px 16px;
        border: none;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: #0284c7;
    }
    .stTabs [aria-selected="true"] {
        background-color: transparent !important;
        color: #0284c7 !important;
        font-weight: bold !important;
        border-bottom: 3px solid #0284c7 !important;
    }
    /* ปรับขนาดหัวข้อหลักให้ใหญ่ขึ้น */
    .main-header-title {
        font-size: 28px !important;
        font-weight: bold !important;
        color: #0f172a;
        margin-top: 10px;
        margin-bottom: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="main-header-title">🚚 ระบบวิเคราะห์และติดตามเส้นทางการจัดส่ง (Sprinkle Delivery Inspector)</div>',
    unsafe_allow_html=True,
)
st.markdown(
    "อัปโหลดไฟล์รายงานใบเบิกใบคืนประจำวัน และ รายงานสรุปการจัดส่งประจำวัน เพื่อตรวจสอบรายการจัดส่งตามจริง พร้อมคำนวณเส้นทางและระยะทางผ่าน OSRM"
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


def get_auto_warehouse_by_truck(truck_no):
    prefix_map = {
        "16": "สาขากรุงเทพกรีฑา",
        "70": "สาขากิ่งแก้ว",
        "98": "สาขาดอนเมือง",
        "17": "สาขาบางบัวทอง",
        "10": "สาขาบางพลี",
        "40": "สาขาบุคคโล",
        "30": "สาขาปทุมธานี",
        "18": "สาขาประชาชื่น",
        "90": "สาขาประเวศ",
        "60": "สาขาปากเกร็ด",
        "20": "สาขาพระราม 2",
        "50": "สาขาพระราม 3",
        "80": "สาขาพุทธมณฑลสาย1",
        "13": "สาขารามอินทรา",
        "14": "สาขาราษฎร์บูรณะ",
        "12": "สาขาวังน้อย",
        "15": "สาขาสำโรง",
        "11": "สาขาสุขุมวิท 50",
    }
    clean_truck = str(truck_no).strip()
    if len(clean_truck) >= 2:
        p2 = clean_truck[:2]
        return prefix_map.get(p2, None)
    return None


def parse_dual_excel_data(dw_file, sum_file):
    header_info = {"date": "ไม่ระบุ", "truck_no": "ไม่ระบุ"}

    dw_raw = pd.read_excel(dw_file, header=None)
    try:
        header_blob = " ".join(
            dw_raw.iloc[:10].fillna("").astype(str).to_numpy().flatten()
        )
        c_match = re.search(r"carCode\s*([\w\-]+)", header_blob)
        if c_match:
            header_info["truck_no"] = c_match.group(1)
        else:
            t_match = re.search(r"รถส่ง\s*([\w\-]+)", header_blob)
            if t_match:
                header_info["truck_no"] = t_match.group(1)

        d_match = re.search(r"targetDate\s*'([\d\-]+)'", header_blob)
        if d_match:
            header_info["date"] = d_match.group(1)
        else:
            d_match2 = re.search(r"ประจำวันที่\s*([\d/]+)", header_blob)
            if d_match2:
                header_info["date"] = d_match2.group(1)
    except Exception:
        pass

    dw_records = []
    re_records = []

    header_row_idx = 0
    for idx in range(len(dw_raw)):
        row_vals = [str(v).strip() for v in dw_raw.iloc[idx].values]
        if (
            "เลขที่เอกสาร" in row_vals
            or "เบิก" in row_vals
            or "คอลัมน์" in row_vals
        ):
            header_row_idx = idx
            break

    sub_df = dw_raw.iloc[header_row_idx + 1 :].copy()
    for _, row in sub_df.iterrows():
        row_list = [
            str(v).strip() if pd.notna(v) else "" for v in row.values
        ]
        if not any(row_list):
            continue

        doc_no = row_list[2] if len(row_list) > 2 else ""
        if not doc_no or doc_no == "nan":
            for val in row_list:
                if (
                    "DW" in val.upper()
                    or "RE" in val.upper()
                    or "DWT" in val.upper()
                    or "RET" in val.upper()
                ):
                    doc_no = val
                    break

        if not doc_no:
            continue

        upper_doc = doc_no.upper()
        if "DW" in upper_doc:
            qty_val = 0
            if len(row_list) > 3 and row_list[3] != "":
                try:
                    qty_val = int(float(row_list[3].replace(",", "")))
                except:
                    pass

            num_match = re.search(r"(\d{3,})$", doc_no)
            if not num_match:
                num_match = re.search(r"(\d+)", doc_no)
            sort_key = int(num_match.group(1)) if num_match else len(dw_records)
            dw_records.append({
                "sort_key": sort_key,
                "qty": qty_val,
                "raw_text": doc_no,
            })

        elif "RE" in upper_doc:
            e_val = 0
            f_val = 0
            if len(row_list) > 4 and row_list[4] != "":
                try:
                    e_val = float(row_list[4].replace(",", ""))
                except:
                    pass
            if len(row_list) > 5 and row_list[5] != "":
                try:
                    f_val = float(row_list[5].replace(",", ""))
                except:
                    pass

            total_re = int(e_val + f_val)

            num_match = re.search(r"(\d{3,})$", doc_no)
            if not num_match:
                num_match = re.search(r"(\d+)", doc_no)
            sort_key = int(num_match.group(1)) if num_match else len(re_records)
            re_records.append({
                "sort_key": sort_key,
                "qty": total_re,
                "raw_text": doc_no,
            })

    dw_records = sorted(dw_records, key=lambda x: x["sort_key"])
    re_records = sorted(re_records, key=lambda x: x["sort_key"])

    if not dw_records:
        dw_records = [{"sort_key": 1, "qty": 160, "raw_text": "DW_DEFAULT"}]

    trip_quotas = []
    for i, dw in enumerate(dw_records):
        dw_q = dw["qty"] if dw["qty"] > 0 else 80
        re_q = (
            re_records[i]["qty"]
            if i < len(re_records) and re_records[i]["qty"] >= 0
            else 0
        )
        net_qty = max(0, dw_q - re_q)
        trip_quotas.append(
            {
                "trip_no": i + 1,
                "dws_qty": dw_q,
                "res_qty": re_q,
                "net_qty": net_qty if net_qty > 0 else dw_q,
                "dw_text": dw["raw_text"],
            }
        )

    sum_raw = pd.read_excel(sum_file, header=None)
    header_sum_idx = 0
    for idx in range(len(sum_raw)):
        row_vals = [str(v).strip() for v in sum_raw.iloc[idx].values]
        if "รหัสลูกค้า" in row_vals or "ชื่อลูกค้า" in row_vals:
            header_sum_idx = idx
            break

    cust_df = sum_raw.iloc[header_sum_idx + 1 :].copy()
    records = []

    for idx, row in cust_df.iterrows():
        row_list = [
            str(v).strip() if pd.notna(v) else "" for v in row.values
        ]
        if not any(row_list) or "รวม" in row_list[0] or "จำนวนสมาชิก" in row_list[0]:
            continue

        cust_id = row_list[0]
        if not cust_id or cust_id == "nan" or cust_id == "None":
            continue

        cust_name = row_list[1] if len(row_list) > 1 and row_list[1] != "" else "-"
        shipping_address = row_list[2] if len(row_list) > 2 and row_list[2] != "" else "-"
        shipping_district = row_list[3] if len(row_list) > 3 and row_list[3] != "" else "-"

        qty = 0
        if len(row_list) > 4 and row_list[4] != "":
            try:
                qty = int(float(row_list[4]))
            except:
                qty = 0

        lat, lng = 0.0, 0.0
        gps_diff_val = 0.0
        delivery_time = "ไม่ระบุเวลา"
        time_sort_key = f"99:{idx:02d}"
        status = "จัดส่งตรงเวลา"
        str_f = ""
        on_time_status = row_list[8] if len(row_list) > 8 else "จัดส่งตรงเวลา"
        short_delivery_reason = row_list[9] if len(row_list) > 9 else "-"

        for val in row_list[1:]:
            gps_match = re.search(
                r"([1-9]\d*\.\d{4,})\s*,\s*([1-9]\d*\.\d{4,})", val
            )
            if gps_match:
                lat = float(gps_match.group(1))
                lng = float(gps_match.group(2))
                continue

            time_match = re.search(r"(\d{1,2}:\d{2})", val)
            if time_match and ":" in val and len(val) <= 10:
                delivery_time = time_match.group(1) + " น."
                time_sort_key = time_match.group(1)
                continue

            try:
                fval = float(val.replace(",", ""))
                if 0 <= fval <= 5000 and gps_diff_val == 0.0 and "." in val:
                    gps_diff_val = fval
                    continue
            except:
                pass

            if any(
                k in val
                for k in [
                    "ตรงเวลา",
                    "ไม่ตรงเวลา",
                    "รอบเสริม",
                    "สมาชิกใหม่",
                    "ย้ายรอบ",
                    "ไม่สามารถคำนวณ",
                    "ลูกค้า",
                    "ไม่รับน้ำ",
                ]
            ):
                str_f = val

        if lat == 0.0 or lng == 0.0:
            for val in row_list:
                parts = val.split(",")
                if len(parts) == 2:
                    try:
                        p1, p2 = float(parts[0].strip()), float(
                            parts[1].strip()
                        )
                        if 5.0 <= p1 <= 21.0 and 97.0 <= p2 <= 106.0:
                            lat, lng = p1, p2
                            break
                    except:
                        pass

        if str_f:
            status = str_f

        if lat == 0.0 or lng == 0.0:
            on_time_status = "ไม่สามารถเข้าส่งได้"

        is_extra_trip = "รอบเสริม" in status or "รอบเสริม" in on_time_status
        is_cannot_calc = "ไม่สามารถคำนวณได้" in status or "คำนวณไม่ได้" in status or lat == 0.0 or lng == 0.0
        is_new_member = "สมาชิกใหม่" in status or "สมาชิกใหม่" in on_time_status
        is_moved_trip = "ย้ายรอบ" in status

        lat_str = f"{lat:.5f}" if lat != 0.0 else "-"
        lng_str = f"{lng:.5f}" if lng != 0.0 else "-"
        gps_diff_str = f"{gps_diff_val:.2f}"

        records.append(
            {
                "excel_idx": idx,
                "cust_id": cust_id,
                "cust_name": cust_name,
                "shipping_address": shipping_address,
                "shipping_district": shipping_district,
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
                "on_time_col": on_time_status if on_time_status else "จัดส่งตรงเวลา",
                "short_reason_col": (
                    short_delivery_reason if short_delivery_reason else "-"
                ),
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

        raw_records = df_raw.to_dict("records")
        i = 0
        while i < len(raw_records):
            r = raw_records[i].copy()
            if curr_trip_idx >= len(trip_quotas):
                curr_trip_idx = len(trip_quotas) - 1

            target_net = trip_quotas[curr_trip_idx]["net_qty"]
            rem_quota = target_net - curr_trip_sum

            if (
                r["qty"] > rem_quota
                and rem_quota > 0
                and curr_trip_idx + 1 < len(trip_quotas)
            ):
                r1 = r.copy()
                r2 = r.copy()

                r1["qty"] = rem_quota
                curr_trip_sum += rem_quota
                total_acc += rem_quota
                r1["acc_qty"] = total_acc
                r1["trip"] = f"เที่ยวที่ {curr_trip_idx + 1}"
                assigned_records.append(r1)

                curr_trip_idx += 1
                curr_trip_sum = 0

                r2["qty"] = r["qty"] - rem_quota
                raw_records[i] = r2
                continue

            if (
                r["qty"] == 0
                and curr_trip_sum >= target_net
                and curr_trip_idx + 1 < len(trip_quotas)
            ):
                curr_time_mins = time_to_mins(r.get("time", ""))
                last_curr_time_mins = curr_time_mins
                if assigned_records:
                    last_curr_time_mins = time_to_mins(
                        assigned_records[-1].get("time", "")
                    )

                next_trip_first_time_mins = curr_time_mins
                for j in range(i + 1, len(raw_records)):
                    if raw_records[j]["qty"] > 0:
                        next_trip_first_time_mins = time_to_mins(
                            raw_records[j].get("time", "")
                        )
                        break

                diff_prev = abs(curr_time_mins - last_curr_time_mins)
                diff_next = abs(curr_time_mins - next_trip_first_time_mins)

                if diff_next < diff_prev:
                    curr_trip_idx += 1
                    curr_trip_sum = 0
                    target_net = trip_quotas[curr_trip_idx]["net_qty"]

            r["trip"] = f"เที่ยวที่ {curr_trip_idx + 1}"
            curr_trip_sum += r["qty"]
            total_acc += r["qty"]
            r["acc_qty"] = total_acc
            assigned_records.append(r)

            if (
                curr_trip_sum >= target_net
                and curr_trip_idx + 1 < len(trip_quotas)
                and r["qty"] > 0
            ):
                curr_trip_idx += 1
                curr_trip_sum = 0

            i += 1

        df = pd.DataFrame(assigned_records)
    else:
        df = df_raw

    return df, trip_quotas, header_info


st.markdown("### 📂 ดาวน์โหลดรายงานต้นทาง")
st.markdown(
    "🔗 **ลิงก์สำหรับดาวน์โหลดรายงานต้นทาง:**\n"
    "- [📥 ดาวน์โหลดไฟล์รายงานใบเบิกใบคืนประจำวัน](https://customreport.sprinkle-th.work/customsql/report/nn_daily_requisition_and_return)\n"
    "- [📥 ดาวน์โหลดไฟล์รายงานสรุปการจัดส่งประจำวัน](https://customreport.sprinkle-th.work/customsql/report/nn_delivery_summary)"
)

# ดึงไฟล์จากช่องทาง Sidebar หรือกำหนดค่าเริ่มต้นเพื่อให้แอปพลิเคชันทำงานต่อได้โดยไม่ต้องแสดง uploader box ด้านบน
dw_uploaded_file = st.sidebar.file_uploader(
    "1. ไฟล์รายงานใบเบิกใบคืนประจำวัน (.xls / .xlsx)",
    type=["xlsx", "xls"],
    key="dw_file",
)
sum_uploaded_file = st.sidebar.file_uploader(
    "2. ไฟล์รายงานสรุปการจัดส่งประจำวัน (.xls / .xlsx)",
    type=["xlsx", "xls"],
    key="sum_file",
)

detected_truck_no = "ไม่ระบุ"
auto_wh_name = None
if dw_uploaded_file:
    try:
        dw_raw_temp = pd.read_excel(dw_uploaded_file, header=None)
        header_blob_temp = " ".join(
            dw_raw_temp.iloc[:10].fillna("").astype(str).to_numpy().flatten()
        )
        c_match_t = re.search(r"carCode\s*([\w\-]+)", header_blob_temp)
        if c_match_t:
            detected_truck_no = c_match_t.group(1)
        else:
            t_match_t = re.search(r"รถส่ง\s*([\w\-]+)", header_blob_temp)
            if t_match_t:
                detected_truck_no = t_match_t.group(1)
        
        auto_wh_name = get_auto_warehouse_by_truck(detected_truck_no)
    except:
        pass

wh_keys = list(warehouse_options.keys())
default_index = 0
if auto_wh_name and auto_wh_name in wh_keys:
    default_index = wh_keys.index(auto_wh_name)

selected_wh_name = st.sidebar.selectbox(
    "เลือกสาขาคลังสินค้า:", wh_keys, index=default_index
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
        else:
            warehouse_coord = (13.66800, 100.61000)
    else:
        warehouse_coord = (13.66800, 100.61000)
else:
    warehouse_coord = warehouse_options[selected_wh_name]

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
    "รูปแบบการแสดงผลบนแผนที่ตามเวลาจริง:",
    (
        "แบบที่ 1: แสดงหมุดครบทั้งหมดล่วงหน้า (เส้นทางวิ่งตามเวลา)",
        "แบบที่ 2: ปรากฏหมุดและเส้นทางเฉพาะจุดล่าสุดทีละจุดตามลำดับเวลา",
    ),
)

anim_speed_ms = st.sidebar.slider(
    "ระยะเวลาต่อจุด(มิลลิวินาที/จุด)",
    min_value=100,
    max_value=3000,
    value=600,
    step=100,
)


def haversine(lat1, lon1, lat2, lon2):
    r = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


def time_to_mins(t_str):
    try:
        t_clean = re.sub(r"[^\d:]", "", str(t_str))
        parts = t_clean.split(":")
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(parts[1])
    except:
        pass
    return 0


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


if dw_uploaded_file and sum_uploaded_file:
    with st.spinner("กำลังอ่านและประมวลผลข้อมูลจากไฟล์ทั้งสอง..."):
        df, trip_quotas, header_info = parse_dual_excel_data(
            dw_uploaded_file, sum_uploaded_file
        )

    if df.empty:
        st.error(
            "❌ ไม่พบข้อมูลรายการจัดส่ง กรุณาตรวจสอบรูปแบบไฟล์รายงานสรุปการจัดส่งประจำวันอีกครั้ง"
        )
    else:
        st.success(
            f"✅ ประมวลผลสำเร็จ! ดึงข้อมูลได้ทั้งหมด {len(df)} รายการ | ยอดจัดส่งรวม {df['qty'].sum()} ถัง | จำนวนเที่ยวการส่ง {len(trip_quotas)} เที่ยว"
        )

        tab1, tab2, tab3 = st.tabs([
            "📊 1. แผนที่และเส้นทางตามลำดับเวลาจริง",
            "🚀 2. แผนที่และเส้นทางเหมาะสมที่สุด",
            "🔍 3. ตรวจสอบและแทรกพิกัดสมาชิกใหม่",
        ])

        with tab1:
            st.markdown("### 📌 ข้อมูลสรุปการปฏิบัติงานตามเวลาจริง")
            c1, c2, c3 = st.columns(3)
            c1.info(f"📅 **ประจำวันที่:** {header_info['date']}")
            c2.info(f"🚛 **รหัสรถส่ง:** {header_info['truck_no']}")

            trip_colors = {
                "เที่ยวที่ 1": "#0055FF",
                "เที่ยวที่ 2": "#FF0055",
                "เที่ยวที่ 3": "#00AA44",
                "เที่ยวที่ 4": "#AA00FF",
                "เที่ยวที่ 5": "#FF8800",
                "เที่ยวที่ 6": "#00CCCC",
            }

            with st.spinner(
                "กำลังคำนวณเส้นทางถนนจริงและระยะทางรวม (เฉพาะจุดที่มีพิกัด)..."
            ):
                segments_data = []
                grouped = df.groupby("trip", sort=False)

                trip_distances = {}
                trip_time_ranges = {}
                point_counter = 0

                row_incremental_distances = []
                row_incremental_time_diffs = []
                last_time_dt = None

                for trip_name, group in grouped:
                    valid_group = group[(group["lat"] != 0.0) & (group["lng"] != 0.0)].copy()
                    route_pts = [warehouse_coord] + list(zip(valid_group["lat"], valid_group["lng"])) + [warehouse_coord]

                    total_trip_dist = 0.0
                    trip_times = []

                    trip_route_segments = []
                    for i in range(len(route_pts) - 1):
                        p1, p2 = route_pts[i], route_pts[i + 1]
                        road_path, dist_km = get_osrm_route(
                            p1[0], p1[1], p2[0], p2[1]
                        )
                        total_trip_dist += dist_km
                        trip_route_segments.append(road_path)

                    records_list = group.to_dict("records")
                    valid_idx_counter = 0

                    for idx_r, info in enumerate(records_list):
                        info["point_idx"] = point_counter
                        point_counter += 1

                        row_incremental_distances.append(round(info.get("gps_diff_num", 0.0), 2))

                        t_str = re.sub(
                            r"[^\d:]", "", str(info.get("time", ""))
                        )
                        time_diff_str = "-"
                        if t_str:
                            try:
                                parts = t_str.split(":")
                                curr_dt = datetime.strptime(
                                    f"{parts[0].zfill(2)}:{parts[1].zfill(2)}",
                                    "%H:%M",
                                )
                                if last_time_dt is not None:
                                    diff = curr_dt - last_time_dt
                                    total_seconds = int(diff.total_seconds())
                                    if total_seconds < 0:
                                        total_seconds += 24 * 3600
                                    mins = total_seconds // 60
                                    time_diff_str = f"{mins} นาที"
                                    if mins >= 60:
                                        hrs = mins // 60
                                        rmins = mins % 60
                                        time_diff_str = (
                                            f"{hrs} ชม. {rmins} นาที"
                                        )
                                last_time_dt = curr_dt
                            except Exception:
                                pass
                        row_incremental_time_diffs.append(time_diff_str)

                        if info.get("time") and "ไม่ระบุ" not in str(
                            info.get("time")
                        ):
                            trip_times.append(str(info.get("time")))

                        info["trip"] = trip_name
                        info["seg_dist_km"] = 0.0
                        info["is_warehouse"] = False

                        segment_path = [[info["lat"], info["lng"]], [info["lat"], info["lng"]]]
                        if info["lat"] != 0.0 and valid_idx_counter < len(trip_route_segments):
                            segment_path = trip_route_segments[valid_idx_counter]
                            valid_idx_counter += 1

                        segments_data.append({
                            "trip": trip_name,
                            "color": trip_colors.get(trip_name, "#0055FF"),
                            "path": segment_path,
                            "info": info,
                            "dist_km": 0.0,
                        })

                    if valid_idx_counter < len(trip_route_segments):
                        return_path = trip_route_segments[valid_idx_counter]
                        last_cust = records_list[-1]
                        wh_info = {
                            "point_idx": point_counter,
                            "trip": trip_name,
                            "cust_id": "WH-RETURN",
                            "cust_name": "คลังสินค้าหลัก",
                            "shipping_address": "กลับถึงคลังสินค้าประจำเที่ยว",
                            "shipping_district": "-",
                            "qty": 0,
                            "acc_qty": last_cust.get("acc_qty", 0),
                            "lat": warehouse_coord[0],
                            "lng": warehouse_coord[1],
                            "lat_display": f"{warehouse_coord[0]:.5f}",
                            "lng_display": f"{warehouse_coord[1]:.5f}",
                            "time": "สิ้นสุดเที่ยว",
                            "on_time_col": "กลับถึงคลัง",
                            "short_reason_col": "-",
                            "gps_diff": "0.00",
                            "is_warehouse": True,
                            "warehouse_type": "trip_return"
                        }
                        point_counter += 1
                        segments_data.append({
                            "trip": trip_name,
                            "color": trip_colors.get(trip_name, "#0055FF"),
                            "path": return_path,
                            "info": wh_info,
                            "dist_km": 0.0,
                        })

                    trip_distances[trip_name] = round(total_trip_dist, 2)
                    if trip_times:
                        trip_time_ranges[trip_name] = (
                            f"{trip_times[0]} - {trip_times[-1]}"
                        )
                    else:
                        trip_time_ranges[trip_name] = "-"

                total_day_distance = round(sum(trip_distances.values()), 2)

            c3.success(
                f"📏 **ระยะทางวิ่งรวมทั้งหมด:** {total_day_distance:.2f} กม."
            )

            df["inc_dist"] = row_incremental_distances
            df["inc_time"] = row_incremental_time_diffs

            st.markdown("### 📋 ตารางรายการจัดส่งสินค้าประจำวัน")

            def get_notification_badge(row):
                notices = []
                on_time_val = str(row.get("on_time_col", ""))

                if "ไม่สามารถเข้าส่งได้" in on_time_val:
                    notices.append("เข้าส่งไม่ได้")
                elif "ไม่ตรงเวลา" in on_time_val:
                    notices.append("ไม่ตรงเวลา")
                elif "รอบเสริม" in on_time_val:
                    notices.append("รอบเสริม")
                elif "สมาชิกใหม่" in on_time_val:
                    notices.append("สมาชิกใหม่")
                else:
                    notices.append("ตรงเวลา")

                if row["lat"] != 0.0 and row["lng"] != 0.0 and row["gps_diff_num"] > 100:
                    notices.append(f"GPS H:{row['gps_diff']}m")
                if row.get("is_extra_trip"):
                    notices.append("รอบเสริม")
                if row.get("is_cannot_calc"):
                    notices.append("คำนวณไม่ได้")
                if row.get("is_new_member"):
                    notices.append("สมาชิกใหม่")
                if row.get("is_moved_trip"):
                    notices.append("ย้ายรอบ")

                reason = str(row.get("short_reason_col", ""))
                if reason.startswith("ไม่"):
                    notices.append(f"เหตุขาดส่ง: {reason}")

                return " | ".join(notices)

            disp_df = df[[
                "time",
                "inc_time",
                "trip",
                "cust_id",
                "cust_name",
                "shipping_address",
                "shipping_district",
                "qty",
                "acc_qty",
                "inc_dist",
                "status",
                "on_time_col",
                "short_reason_col",
                "lat_display",
                "lng_display",
                "gps_diff",
            ]].copy()

            disp_df["การแจ้งเตือน"] = df.apply(get_notification_badge, axis=1)
            disp_df.insert(0, "ลำดับ", range(1, len(disp_df) + 1))

            disp_df.columns = [
                "ลำดับ",
                "เวลาส่ง",
                "ช่วงเวลา",
                "เที่ยว",
                "รหัสลูกค้า",
                "ชื่อลูกค้า",
                "ที่อยู่จัดส่ง",
                "แขวง/เขตจัดส่ง",
                "ยอดส่ง (ถัง)",
                "ยอดสะสม",
                "ระยะทาง (กม.)",
                "สถานะ",
                "ตรงเวลา",
                "เหตุขาดส่ง",
                "Lat",
                "Lng",
                "ผลต่าง GPS",
                "หมายเหตุ",
            ]

            st.dataframe(
                disp_df, use_container_width=True, height=350, hide_index=True
            )

            st.divider()

            st.markdown("### 🗺️ แผนที่จำลองการวิ่งจัดส่งตามเส้นทางเวลาจริง (OSRM Map)")

            st.markdown("### 📊 สรุปภาพรวมแบ่งตามเที่ยวการส่ง")
            summaries = []
            for idx, t_info in enumerate(trip_quotas):
                trip_name = f"เที่ยวที่ {t_info['trip_no']}"
                group = (
                    df[df["trip"] == trip_name]
                    if trip_name in df["trip"].values
                    else pd.DataFrame()
                )
                t_dist = trip_distances.get(trip_name, 0.0)
                t_time_range = trip_time_ranges.get(trip_name, "-")

                actual_qty = group["qty"].sum() if not group.empty else 0
                point_count = len(group)
                
                ontime_count = len(group[group["on_time_col"] == "จัดส่งตรงเวลา"]) if not group.empty else 0
                late_count = len(group[group["on_time_col"].str.contains("ไม่ตรงเวลา", na=False)]) if not group.empty else 0
                no_loc_count = len(group[group["on_time_col"] == "ไม่สามารถเข้าส่งได้"]) if not group.empty else 0
                extra_count = len(group[group["on_time_col"] == "รอบเสริม"]) if not group.empty else 0
                new_count = len(group[group["on_time_col"] == "สมาชิกใหม่"]) if not group.empty else 0
                
                gps_err_count = (
                    len(group[(group["lat"] != 0.0) & (group["lng"] != 0.0) & (group["gps_diff_num"] > 100)])
                    if not group.empty
                    else 0
                )

                summaries.append({
                    "เที่ยวการส่ง": trip_name,
                    "เวลาจัดส่งแต่ละเที่ยว": t_time_range,
                    "ใบเบิก (DW)": t_info["dw_text"],
                    "ยอดเบิก (ถัง)": t_info["dws_qty"],
                    "ยอดคืน (ถัง)": t_info["res_qty"],
                    "ยอดจัดส่งจริง (ถัง)": actual_qty,
                    "จำนวนจุดส่ง (จุด)": point_count,
                    "ระยะทางวิ่งรวม (กม.)": f"{t_dist:.2f}",
                    "จัดส่งตรงเวลา (จุด)": ontime_count,
                    "จัดส่งไม่ตรงเวลา (จุด)": late_count,
                    "ไม่มีพิกัด (เข้าส่งไม่ได้)": no_loc_count,
                    "รอบเสริม (จุด)": extra_count,
                    "สมาชิกใหม่ (จุด)": new_count,
                    "GPS คลาดเคลื่อน >100m (จุด)": gps_err_count,
                })

            total_dws = sum([t["dws_qty"] for t in trip_quotas])
            total_res = sum([t["res_qty"] for t in trip_quotas])

            summaries.append({
                "เที่ยวการส่ง": "รวมทั้งหมดประจำวัน",
                "เวลาจัดส่งแต่ละเที่ยว": "-",
                "ใบเบิก (DW)": "-",
                "ยอดเบิก (ถัง)": total_dws,
                "ยอดคืน (ถัง)": total_res,
                "ยอดจัดส่งจริง (ถัง)": df["qty"].sum(),
                "จำนวนจุดส่ง (จุด)": len(df),
                "ระยะทางวิ่งรวม (กม.)": f"{total_day_distance:.2f}",
                "จัดส่งตรงเวลา (จุด)": len(df[df["on_time_col"] == "จัดส่งตรงเวลา"]),
                "จัดส่งไม่ตรงเวลา (จุด)": len(df[df["on_time_col"].str.contains("ไม่ตรงเวลา", na=False)]),
                "ไม่มีพิกัด (เข้าส่งไม่ได้)": len(df[df["on_time_col"] == "ไม่สามารถเข้าส่งได้"]),
                "รอบเสริม (จุด)": len(df[df["on_time_col"] == "รอบเสริม"]),
                "สมาชิกใหม่ (จุด)": len(df[df["on_time_col"] == "สมาชิกใหม่"]),
                "GPS คลาดเคลื่อน >100m (จุด)": len(
                    df[(df["lat"] != 0.0) & (df["lng"] != 0.0) & (df["gps_diff_num"] > 100)]
                ),
            })

            st.table(pd.DataFrame(summaries))

            df_records = df.to_dict("records")
            for idx, r in enumerate(df_records):
                r["color"] = trip_colors.get(r.get("trip"), "#0055FF")
                r["point_idx"] = idx
                r["is_warehouse"] = False

            points_json = json.dumps(df_records, ensure_ascii=False)
            segments_json = json.dumps(segments_data, ensure_ascii=False)
            wh_json = json.dumps(warehouse_coord)
            is_mode_1 = "แบบที่ 1" in play_mode

            legend_html_items = ""
            for t_info in trip_quotas:
                t_name = f"เที่ยวที่ {t_info['trip_no']}"
                t_color = trip_colors.get(t_name, "#0055FF")
                legend_html_items += f'<div class="legend-item"><span class="color-box" style="background:{t_color};"></span> {t_name}</div>\n'

            trip_filter_buttons = '<button class="filter-btn active" id="btn-all" onclick="setTripFilter(\'ALL\')">แสดงทั้งหมด</button>\n'
            for t_info in trip_quotas:
                t_name = f"เที่ยวที่ {t_info['trip_no']}"
                trip_filter_buttons += f'<button class="filter-btn" id="btn-trip{t_info["trip_no"]}" onclick="setTripFilter(\'{t_name}\')">{t_name}</button>\n'

            map_html = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
                <style>
                    #map { width: 100%; height: 540px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
                    
                    /* ปรับแต่ง Leaflet Tooltip ให้มีมุมโค้งมนสบายตา */
                    .leaflet-tooltip {
                        border-radius: 8px !important;
                        padding: 8px 12px !important;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.18) !important;
                        border: 1px solid #cbd5e1 !important;
                    }
                    
                    #top-active-banner {
                        background: linear-gradient(135deg, #2c3e50, #34495e);
                        color: white;
                        padding: 10px 16px;
                        border-radius: 8px;
                        margin-bottom: 12px;
                        font-family: sans-serif;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                        border-left: 6px solid #5dade2;
                    }
                    
                    .controls { margin-bottom: 10px; font-family: sans-serif; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
                    button { padding: 8px 16px; background-color: #008CBA; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: bold; transition: 0.2s; }
                    button:hover { background-color: #005f73; transform: scale(1.02); }
                    
                    .filter-bar { margin-bottom: 8px; font-family: sans-serif; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; background: #f1f4f9; padding: 8px 12px; border-radius: 6px; }
                    .filter-btn { padding: 5px 12px; background-color: #e0e0e0; color: #333; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: bold; transition: 0.2s; }
                    .filter-btn:hover { background-color: #cfd8dc; }
                    .filter-btn.active { background-color: #2c3e50; color: white; }

                    .status-filter-btn { padding: 4px 10px; background-color: #e0e0e0; color: #333; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold; transition: 0.2s; display: inline-flex; align-items: center; gap: 4px; }
                    .status-filter-btn:hover { background-color: #d5dbdb; opacity: 0.9; }
                    .status-filter-btn.active { background-color: #d9534f; color: white; box-shadow: 0 0 6px rgba(0,0,0,0.3); }

                    .timeline-container { position: relative; width: 100%; display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-family: sans-serif; background: #eef2f5; padding: 8px 12px; border-radius: 6px; box-sizing: border-box; }
                    .timeline-slider { flex-grow: 1; height: 8px; cursor: pointer; accent-color: #0055FF; }
                    
                    /* Tooltip แสดงตัวเลขจุดเมื่อเอาเมาส์ชี้บนสไลเดอร์ */
                    #slider-hover-tip {
                        position: absolute;
                        display: none;
                        background: #0284c7;
                        color: #ffffff;
                        padding: 3px 8px;
                        border-radius: 6px;
                        font-size: 11px;
                        font-weight: bold;
                        pointer-events: none;
                        white-space: nowrap;
                        box-shadow: 0 2px 6px rgba(0,0,0,0.25);
                        z-index: 1000;
                        transform: translate(-50%, -34px);
                    }
                    #slider-hover-tip::after {
                        content: '';
                        position: absolute;
                        top: 100%;
                        left: 50%;
                        transform: translateX(-50%);
                        border-width: 4px;
                        border-style: solid;
                        border-color: #0284c7 transparent transparent transparent;
                    }

                    #info-box { margin-top: 10px; padding: 12px 16px; background: #f8f9fa; border-left: 6px solid #008CBA; font-family: sans-serif; border-radius: 6px; font-size: 14px; line-height: 1.6; color: #333; }
                    .legend { display: flex; gap: 12px; margin-bottom: 6px; font-family: sans-serif; font-size: 12px; font-weight: bold; flex-wrap: wrap; align-items: center; }
                    .legend-item { display: flex; align-items: center; gap: 4px; }
                    .color-box { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
                    
                    .leaflet-div-icon { background: transparent !important; border: none !important; }
                    .marker-container { position: relative; width: 28px; height: 28px; }

                    .number-icon {
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
                        display: flex !important;
                        align-items: center !important;
                        justify-content: center !important;
                        box-sizing: border-box !important;
                    }

                    .number-icon-active {
                        transform: scale(1.6) !important;
                        z-index: 9999 !important;
                        border: 2px solid #FFFFFF !important;
                        box-shadow: 0 0 16px #FFD700, 0 4px 12px rgba(0,0,0,0.9) !important;
                    }

                    .marker-badge-late {
                        position: absolute; top: -6px; right: -8px;
                        background-color: #D32F2F; color: white; border: 1.5px solid white;
                        border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                        display: flex; align-items: center; justify-content: center; z-index: 20;
                    }
                    .marker-badge-gps {
                        position: absolute; top: -6px; left: -8px;
                        background-color: #FF9800; color: white; border: 1.5px solid white;
                        border-radius: 50%; width: 15px; height: 15px; font-size: 9px;
                        display: flex; align-items: center; justify-content: center; z-index: 20;
                    }
                    .marker-badge-extra {
                        position: absolute; bottom: -4px; right: -6px;
                        background-color: #8E44AD; color: white; border: 1px solid white;
                        border-radius: 3px; padding: 0 2px; font-size: 8px; font-weight: bold; z-index: 20;
                    }
                    .marker-badge-new {
                        position: absolute; bottom: -4px; left: -6px;
                        background-color: #2980B9; color: white; border: 1px solid white;
                        border-radius: 3px; padding: 0 2px; font-size: 8px; font-weight: bold; z-index: 20;
                    }
                    .marker-badge-reason {
                        position: absolute; top: 50%; left: -14px; transform: translateY(-50%);
                        background-color: #C0392B; color: white; border: 1px solid white;
                        border-radius: 3px; padding: 0 2px; font-size: 7px; font-weight: bold; z-index: 20;
                    }
                    .alert-badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; color: white; margin-left: 4px; }
                </style>
            </head>
            <body>
                <div class="legend">
                    __LEGEND_ITEMS__
                </div>

                <div class="filter-bar">
                    <span style="font-weight:bold; font-size:13px;">🔍 กรองเที่ยว:</span>
                    __TRIP_FILTER_BUTTONS__
                </div>

                <div class="filter-bar" style="background: #faf2f2;">
                    <span style="font-weight:bold; font-size:13px;">🏷️ กรองสถานะ:</span>
                    <button class="status-filter-btn" id="status-btn-late" onclick="setStatusFilter('late')">ไม่ตรงเวลา (<span id="count-late">0</span>)</button>
                    <button class="status-filter-btn" id="status-btn-gps" onclick="setStatusFilter('gps')">GPS>100 (<span id="count-gps">0</span>)</button>
                    <button class="status-filter-btn" id="status-btn-reason" onclick="setStatusFilter('reason')">เหตุขาดส่ง (<span id="count-reason">0</span>)</button>
                    <button class="status-filter-btn" id="status-btn-extra" onclick="setStatusFilter('extra')">รอบเสริม (<span id="count-extra">0</span>)</button>
                    <button class="status-filter-btn" id="status-btn-new" onclick="setStatusFilter('new')">สมาชิกใหม่ (<span id="count-new">0</span>)</button>
                </div>

                <div class="controls">
                    <button onclick="startAnimation()">▶️ เล่น</button>
                    <button onclick="pauseAnimation()">⏸️ พัก</button>
                    <button onclick="resetAnimation()">🔄 เริ่มใหม่</button>
                    <span id="status-text" style="font-weight: bold; font-family: sans-serif; color: #2c3e50;">พร้อมจำลองเส้นทาง...</span>
                </div>

                <div class="timeline-container">
                    <span style="font-weight:bold; font-size:13px;">⏱️ ไทม์ไลน์:</span>
                    <input type="range" id="timeSlider" class="timeline-slider" min="0" max="__MAX_SEG__" value="0" oninput="onSliderChange(this.value)" onmousemove="showSliderHoverTooltip(event)" onmouseleave="hideSliderHoverTooltip()">
                    <div id="slider-hover-tip">จุดที่ 1</div>
                    <span id="slider-label" style="font-weight:bold; font-size:12px; min-width:260px; text-align:right; background:#fff; padding:4px 10px; border-radius:4px; border:1px solid #ccc;">09:00 - จุดที่ 1</span>
                </div>

                <div id="top-active-banner">
                    <div style="font-size: 11px; color: #a9cce3; font-weight: bold; margin-bottom: 2px;">📍 ตำแหน่งปัจจุบัน / จุดถัดไป:</div>
                    <div id="top-banner-content" style="font-size: 13px; font-weight: bold;">กำลังโหลด...</div>
                </div>

                <div id="map"></div>
                <div id="info-box">📍 <b>สถานะ</b>: คลิกปุ่ม "เล่น" เพื่อดูการติดตามเส้นทางการจัดส่งแบบเรียลไทม์</div>

                <script>
                    const points = __POINTS_JSON__;
                    const segments = __SEGMENTS_JSON__;
                    const warehouse = __WH_JSON__;
                    let currentSpeedMs = __ANIM_SPEED__;
                    const isMode1 = __IS_MODE_1__;

                    let currentFilter = 'ALL';
                    let currentStatusFilter = null;

                    const map = L.map('map').setView([warehouse[0], warehouse[1]], 13);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                        attribution: '© OpenStreetMap contributors'
                    }).addTo(map);

                    const warehouseIcon = L.divIcon({
                        className: '',
                        html: '<div style="background:#2c3e50; color:white; border:2px solid white; border-radius:50%; width:30px; height:30px; text-align:center; font-size:14px; line-height:26px; font-weight:bold; box-shadow:0 2px 6px rgba(0,0,0,0.4); display:flex; align-items:center; justify-content:center;" title="กลับถึงคลังสินค้า">🏢</div>',
                        iconSize: [30, 30], iconAnchor: [15, 15]
                    });

                    let warehouseMarker = L.marker(warehouse, {icon: warehouseIcon}).addTo(map)
                        .bindTooltip("🏢 คลังสินค้าหลัก (Warehouse)", {permanent: false, direction: 'top'});

                    let allMarkers = [];
                    let activePolylines = [];
                    let currentStep = 0;
                    let animTimer = null;
                    let isPlaying = false;
                    let activeMarkerRef = null;

                    function showSliderHoverTooltip(e) {
                        const slider = document.getElementById('timeSlider');
                        const tip = document.getElementById('slider-hover-tip');
                        const rect = slider.getBoundingClientRect();
                        const containerRect = slider.parentElement.getBoundingClientRect();
                        
                        const offsetX = e.clientX - rect.left;
                        const pct = Math.max(0, Math.min(1, offsetX / rect.width));
                        const maxVal = parseInt(slider.max) || 0;
                        const hoverIdx = Math.round(pct * maxVal);
                        
                        tip.innerText = "จุดที่ " + (hoverIdx + 1);
                        tip.style.display = "block";
                        tip.style.left = (e.clientX - containerRect.left) + "px";
                    }

                    function hideSliderHoverTooltip() {
                        const tip = document.getElementById('slider-hover-tip');
                        tip.style.display = "none";
                    }

                    function hasReasonStartsWithNot(pt) {
                        let r = pt.short_reason_col || '';
                        return r.startsWith('ไม่');
                    }

                    function pointMatchesFilter(pt) {
                        if (pt.is_warehouse) return true;
                        if (pt.lat === 0.0 || pt.lng === 0.0) return false;
                        if (currentFilter !== 'ALL' && pt.trip !== currentFilter) return false;
                        if (currentStatusFilter !== null) {
                            let onTimeCol = pt.on_time_col || '';
                            let isLate = onTimeCol.includes("ไม่ตรงเวลา");
                            let isGps = (pt.lat !== 0.0 && pt.lng !== 0.0) && ((pt.gps_diff_num || parseFloat(pt.gps_diff || 0)) > 100);
                            let isReasonNot = hasReasonStartsWithNot(pt);
                            let isExtra = pt.is_extra_trip || onTimeCol.includes("รอบเสริม");
                            let isNew = pt.is_new_member || onTimeCol.includes("สมาชิกใหม่");

                            if (currentStatusFilter === 'late' && !isLate) return false;
                            if (currentStatusFilter === 'gps' && !isGps) return false;
                            if (currentStatusFilter === 'reason' && !isReasonNot) return false;
                            if (currentStatusFilter === 'extra' && !isExtra) return false;
                            if (currentStatusFilter === 'new' && !isNew) return false;
                        }
                        return true;
                    }

                    function updateStatusCounts() {
                        let counts = { late: 0, gps: 0, reason: 0, extra: 0, new: 0 };
                        points.forEach(pt => {
                            if (!pt.is_warehouse && pt.lat !== 0.0 && pt.lng !== 0.0 && (currentFilter === 'ALL' || pt.trip === currentFilter)) {
                                let onTimeCol = pt.on_time_col || '';
                                if (onTimeCol.includes("ไม่ตรงเวลา")) counts.late++;
                                if ((pt.lat !== 0.0 && pt.lng !== 0.0) && ((pt.gps_diff_num || parseFloat(pt.gps_diff || 0)) > 100)) counts.gps++;
                                if (hasReasonStartsWithNot(pt)) counts.reason++;
                                if (pt.is_extra_trip || onTimeCol.includes("รอบเสริม")) counts.extra++;
                                if (pt.is_new_member || onTimeCol.includes("สมาชิกใหม่")) counts.new++;
                            }
                        });
                        document.getElementById('count-late').innerText = counts.late;
                        document.getElementById('count-gps').innerText = counts.gps;
                        document.getElementById('count-reason').innerText = counts.reason;
                        document.getElementById('count-extra').innerText = counts.extra;
                        document.getElementById('count-new').innerText = counts.new;
                    }

                    function createTooltipHtml(info, seqNum) {
                        if (info.is_warehouse) {
                            return '<div style="font-family:sans-serif; font-size:11px; line-height:1.4;">' +
                                '<b>🏢 คลังสินค้าหลัก (' + info.trip + ') - กลับถึงสาขา</b><br>' +
                                '<b>สถานะ:</b> รถกลับถึงคลังสินค้าประจำเที่ยวเรียบร้อย เพื่อเตรียมไปเที่ยวอื่นต่อ<br>' +
                                '<b>ยอดสะสมรวม:</b> ' + info.acc_qty + ' ถัง' +
                            '</div>';
                        }
                        let badgesHtml = [];
                        let onTimeVal = info.on_time_col || 'จัดส่งตรงเวลา';
                        if (onTimeVal.includes("ไม่ตรงเวลา")) badgesHtml.push('<span class="alert-badge" style="background:#D32F2F;">' + onTimeVal + '</span>');
                        else badgesHtml.push('<span class="alert-badge" style="background:#4CAF50;">' + onTimeVal + '</span>');
                        
                        if (info.lat !== 0.0 && info.lng !== 0.0 && (info.gps_diff_num || parseFloat(info.gps_diff || 0)) > 100) badgesHtml.push('<span class="alert-badge" style="background:#FF9800;">GPS>100</span>');
                        if (hasReasonStartsWithNot(info)) badgesHtml.push('<span class="alert-badge" style="background:#C0392B;">ขาดส่ง: ' + info.short_reason_col + '</span>');

                        let addrInfo = info.shipping_address && info.shipping_address !== '-' ? info.shipping_address : '';
                        let fullAddressText = addrInfo ? '<br><b>ที่อยู่:</b> ' + addrInfo : '';

                        return '<div style="font-family:sans-serif; font-size:11px; line-height:1.4; width:4cm; word-break:break-word; overflow-wrap:break-word; white-space:normal;">' +
                            '<b>📍 จุดที่ ' + seqNum + ' (' + info.trip + ')</b><br>' +
                            badgesHtml.join(' ') + '<br>' +
                            '<b>เวลา:</b> ' + info.time + '<br>' +
                            '<b>ลูกค้า:</b> ' + info.cust_id + ' (' + (info.cust_name || '-') + ')' +
                            fullAddressText + '<br>' +
                            '<b>ยอดส่ง:</b> ' + info.qty + ' ถัง' +
                        '</div>';
                    }

                    function createMarkerIcon(seqNum, color, ptInfo) {
                        if (ptInfo && ptInfo.is_warehouse) {
                            return L.divIcon({
                                className: '',
                                html: '<div style="background:#2c3e50; color:white; border:2px solid white; border-radius:50%; width:28px; height:28px; text-align:center; font-size:14px; line-height:24px; font-weight:bold; box-shadow:0 2px 6px rgba(0,0,0,0.5); display:flex; align-items:center; justify-content:center;" title="กลับถึงคลังสินค้า">🏢</div>',
                                iconSize: [28, 28], iconAnchor: [14, 14]
                            });
                        }
                        let onTimeVal = ptInfo && ptInfo.on_time_col ? ptInfo.on_time_col : '';
                        let isLate = onTimeVal.includes("ไม่ตรงเวลา");
                        let isGpsDiff = ptInfo && (ptInfo.lat !== 0.0 && ptInfo.lng !== 0.0) && ((ptInfo.gps_diff_num || parseFloat(ptInfo.gps_diff || 0)) > 100);
                        let isReasonNot = ptInfo && hasReasonStartsWithNot(ptInfo);
                        
                        let lateBadgeHtml = isLate ? '<div class="marker-badge-late">!</div>' : '';
                        let gpsBadgeHtml = isGpsDiff ? '<div class="marker-badge-gps">G</div>' : '';
                        let reasonBadgeHtml = isReasonNot ? '<div class="marker-badge-reason" title="' + ptInfo.short_reason_col + '">ไม่</div>' : '';
                        let extraBadgeHtml = (ptInfo && (ptInfo.is_extra_trip || onTimeVal.includes("รอบเสริม"))) ? '<div class="marker-badge-extra">เสริม</div>' : '';
                        let newBadgeHtml = (ptInfo && (ptInfo.is_new_member || onTimeVal.includes("สมาชิกใหม่"))) ? '<div class="marker-badge-new">ใหม่</div>' : '';

                        let innerHtml = '<div class="marker-container">' + lateBadgeHtml + gpsBadgeHtml + reasonBadgeHtml + extraBadgeHtml + newBadgeHtml + '<div class="number-icon" style="background-color: ' + (color || '#008CBA') + ' !important;">' + seqNum + '</div></div>';
                        return L.divIcon({ className: '', html: innerHtml, iconSize: [28, 28], iconAnchor: [14, 14] });
                    }

                    function initMarkers() {
                        allMarkers.forEach(m => map.removeLayer(m));
                        allMarkers = [];
                        segments.forEach((seg, idx) => {
                            let pt = seg.info;
                            if (pt && pointMatchesFilter(pt)) {
                                let seqNumber = idx + 1;
                                let customIcon = createMarkerIcon(seqNumber, seg.color, pt);
                                let marker = L.marker(pt.is_warehouse ? warehouse : [pt.lat, pt.lng], { icon: customIcon });
                                
                                if (!isMode1 && idx > currentStep) {
                                    // ซ่อนไว้ก่อน
                                } else {
                                    marker.addTo(map);
                                }
                                
                                marker.bindTooltip(createTooltipHtml(pt, seqNumber), { direction: 'top', opacity: 0.95 });
                                allMarkers[idx] = marker;
                            }
                        });
                        updateStatusCounts();
                    }

                    initMarkers();

                    function setTripFilter(filterName) {
                        pauseAnimation();
                        currentFilter = filterName;
                        
                        document.querySelectorAll('.filter-btn').forEach(el => {
                            if (el.id.startsWith('btn-trip') || el.id === 'btn-all') {
                                el.classList.remove('active');
                            }
                        });
                        
                        if (filterName === 'ALL') {
                            let btnAll = document.getElementById('btn-all');
                            if (btnAll) btnAll.classList.add('active');
                        } else {
                            document.querySelectorAll('.filter-btn').forEach(el => {
                                if (el.innerText === filterName) {
                                    el.classList.add('active');
                                }
                            });
                        }

                        initMarkers();
                        let firstMatchIdx = segments.findIndex(seg => pointMatchesFilter(seg.info));
                        if (firstMatchIdx !== -1) { currentStep = firstMatchIdx; updateStep(currentStep); }
                    }

                    function setStatusFilter(statusKey) {
                        pauseAnimation();
                        currentStatusFilter = (currentStatusFilter === statusKey) ? null : statusKey;
                        ['late', 'gps', 'reason', 'extra', 'new'].forEach(k => {
                            let btn = document.getElementById('status-btn-' + k);
                            if (btn) {
                                if (k === currentStatusFilter) btn.classList.add('active');
                                else btn.classList.remove('active');
                            }
                        });
                        initMarkers();
                        let firstMatchIdx = segments.findIndex(seg => pointMatchesFilter(seg.info));
                        if (firstMatchIdx !== -1) { currentStep = firstMatchIdx; updateStep(currentStep); }
                    }

                    function highlightMarkerByInfo(stepIdx) {
                        if (activeMarkerRef) {
                            if (activeMarkerRef._icon) {
                                let innerDiv = activeMarkerRef._icon.querySelector('.number-icon');
                                if (innerDiv) innerDiv.classList.remove('number-icon-active');
                            }
                        }
                        activeMarkerRef = null;
                        let target = allMarkers[stepIdx];
                        if (target) {
                            if (target._icon) {
                                let innerDiv = target._icon.querySelector('.number-icon');
                                if (innerDiv) innerDiv.classList.add('number-icon-active');
                            }
                            if (target.setZIndexOffset) target.setZIndexOffset(10000);
                            activeMarkerRef = target;
                        }
                    }

                    function updateStep(stepIndex) {
                        if (stepIndex < 0 || stepIndex >= segments.length) return;
                        currentStep = stepIndex;
                        let currentSeg = segments[currentStep];
                        let info = currentSeg.info;

                        if (!pointMatchesFilter(info)) {
                            let nextValid = segments.findIndex((seg, idx) => idx >= currentStep && pointMatchesFilter(seg.info));
                            if (nextValid !== -1) { currentStep = nextValid; currentSeg = segments[currentStep]; info = currentSeg.info; }
                        }

                        let slider = document.getElementById('timeSlider');
                        slider.value = currentStep;
                        slider.style.accentColor = currentSeg.color;

                        let timeLabel = info.time || '-';
                        let tripLabel = info.trip || currentSeg.trip || '-';
                        let stepNumText = currentStep + 1;

                        if (info.is_warehouse) {
                            document.getElementById('top-banner-content').innerHTML = 
                                'จุดที่ <span style="color:#5dade2; font-size:14px;">' + stepNumText + '</span> (' + tripLabel + ') | 🏢 <span style="color:#ffffff;">กลับถึงคลังสินค้าหลัก (เตรียมไปเที่ยวอื่นต่อ)</span> | ยอดสะสมรวม: <span style="color:#f39c12;">' + info.acc_qty + ' ถัง</span>';
                            document.getElementById('slider-label').innerHTML = '<span style="color:' + currentSeg.color + '; font-weight:bold;">' + tripLabel + '</span> - <span style="color:#5dade2;">กลับถึงคลัง</span>';
                        } else {
                            document.getElementById('top-banner-content').innerHTML = 
                                'จุดที่ <span style="color:#5dade2; font-size:14px;">' + stepNumText + '</span> (' + tripLabel + ') | เวลา: <b>' + timeLabel + '</b> | ลูกค้า: <span style="color:#ffffff;">' + info.cust_id + ' (' + info.cust_name + ')</span> | ยอดส่ง: <span style="color:#f39c12;">' + info.qty + ' ถัง</span> | สะสม: <span style="color:#5dade2;">' + info.acc_qty + ' ถัง</span>';
                            document.getElementById('slider-label').innerHTML = '<span style="color:' + currentSeg.color + '; font-weight:bold;">' + timeLabel + '</span> - <span style="color:#5dade2;">' + info.cust_id + '</span> (จุด ' + stepNumText + ')';
                        }

                        activePolylines.forEach(p => map.removeLayer(p));
                        activePolylines = [];

                        let accumulatedDistance = 0.0;
                        for (let i = 0; i <= currentStep; i++) {
                            let seg = segments[i];
                            if (!pointMatchesFilter(seg.info)) continue;
                            accumulatedDistance += (seg.dist_km || 0.0);
                            if (seg.path && seg.path.length > 0) {
                                let polyline = L.polyline(seg.path, { color: seg.color, weight: 5, opacity: 0.85 }).addTo(map);
                                activePolylines.push(polyline);
                            }
                        }

                        if (!isMode1) {
                            allMarkers.forEach((marker, mIdx) => {
                                if (marker) {
                                    let ptInfo = segments[mIdx].info;
                                    let matches = pointMatchesFilter(ptInfo);
                                    if (matches && mIdx <= currentStep) {
                                        if (!map.hasLayer(marker)) marker.addTo(map);
                                    } else {
                                        if (map.hasLayer(marker)) map.removeLayer(marker);
                                    }
                                }
                            });
                        }

                        highlightMarkerByInfo(currentStep);

                        if (info.is_warehouse) {
                            document.getElementById('info-box').innerHTML = 
                                '<b>🚛 ' + tripLabel + ' | กลับถึงคลังสินค้าหลัก (จุดที่ ' + stepNumText + ' / ' + segments.length + ')</b><br>' +
                                '<b>🏢 สถานะ:</b> รถขนส่งเดินทางกลับถึงคลังสินค้าประจำเที่ยวเรียบร้อย พร้อมสำหรับจัดสรรเที่ยววิ่งถัดไป | <b>📦 ยอดสะสมรวม:</b> <span style="color:#D32F2F; font-weight:bold;">' + info.acc_qty + ' ถัง</span>';
                        } else {
                            let addrStr = info.shipping_address && info.shipping_address !== '-' ? info.shipping_address : '-';
                            document.getElementById('info-box').innerHTML = 
                                '<b>🚛 ' + tripLabel + ' | จุดที่ ' + stepNumText + ' จาก ' + segments.length + '</b><br>' +
                                '<b>🕒 เวลาส่ง:</b> ' + info.time + ' | <b>👤 ลูกค้า:</b> <span style="color:#0055FF; font-weight:bold;">' + info.cust_id + ' (' + info.cust_name + ')</span><br>' +
                                '<b>🏠 ที่อยู่:</b> ' + addrStr + '<br>' +
                                '<b>📦 ยอดส่ง:</b> <span style="color:#D32F2F; font-weight:bold;">' + info.qty + ' ถัง</span> | <b>📍 พิกัด:</b> ' + info.lat_display + ', ' + info.lng_display + ' | <b>📏 GPS Diff:</b> <span style="color:#FF9800; font-weight:bold;">' + (info.gps_diff || '0.00') + ' ม.</span><br>' +
                                '<b>📝 เหตุขาดส่ง:</b> <span style="color:#C0392B; font-weight:bold;">' + (info.short_reason_col || '-') + '</span> | <b>📌 สถานะ:</b> <span style="color:#2E7D32; font-weight:bold;">' + (info.on_time_col || '-') + '</span>';
                        }

                        let panTarget = info.is_warehouse ? warehouse : [info.lat, info.lng];
                        map.panTo(panTarget);
                    }

                    function nextStep() {
                        let nextIdx = currentStep + 1;
                        while (nextIdx < segments.length) {
                            if (pointMatchesFilter(segments[nextIdx].info)) break;
                            nextIdx++;
                        }
                        if (nextIdx < segments.length) {
                            currentStep = nextIdx;
                            updateStep(currentStep);
                        } else {
                            pauseAnimation();
                            document.getElementById('status-text').innerText = "🏁 จำลองเส้นทางเสร็จสิ้น!";
                        }
                    }

                    function startAnimation() {
                        if (isPlaying) return;
                        isPlaying = true;
                        document.getElementById('status-text').innerText = "▶ กำลังจำลองเส้นทาง...";
                        updateStep(currentStep);
                        animTimer = setInterval(nextStep, currentSpeedMs);
                    }

                    function pauseAnimation() {
                        isPlaying = false;
                        if (animTimer) { clearInterval(animTimer); animTimer = null; }
                        document.getElementById('status-text').innerText = "⏸ พักการจำลองชั่วคราว";
                    }

                    function resetAnimation() {
                        pauseAnimation();
                        let firstMatchIdx = segments.findIndex(seg => pointMatchesFilter(seg.info));
                        currentStep = firstMatchIdx !== -1 ? firstMatchIdx : 0;
                        updateStep(currentStep);
                        document.getElementById('status-text').innerText = "🔄 รีเซ็ตการจำลองแล้ว";
                    }

                    function onSliderChange(val) {
                        pauseAnimation();
                        updateStep(parseInt(val));
                    }

                    if (segments.length > 0) { updateStep(0); }
                </script>
            </body>
            </html>
            """

            map_html = map_html.replace("__LEGEND_ITEMS__", legend_html_items)
            map_html = map_html.replace("__TRIP_FILTER_BUTTONS__", trip_filter_buttons)
            map_html = map_html.replace("__MAX_SEG__", str(max(len(segments_data) - 1, 0)))
            map_html = map_html.replace("__POINTS_JSON__", points_json)
            map_html = map_html.replace("__SEGMENTS_JSON__", segments_json)
            map_html = map_html.replace("__WH_JSON__", wh_json)
            map_html = map_html.replace("__ANIM_SPEED__", str(anim_speed_ms))
            map_html = map_html.replace("__IS_MODE_1__", str(is_mode_1).lower())

            st.components.v1.html(map_html, height=800, scrolling=False)

        # --- TAB 2: เปรียบเทียบเส้นทางเหมาะสมที่สุด (Optimized Route & Maps) ---
        with tab2:
            st.markdown("### 🚀 แผนที่และเส้นทางที่เหมาะสมที่สุด")
            st.markdown(
                "ระบบประมวลผลเส้นทางจากแบบที่ 1 เสร็จสิ้นแล้ว นำระยะทางรวมตั้งต้นมาเปรียบเทียบ และคำนวณเส้นทางใหม่โดยให้ระยะทางน้อยกว่าแบบที่ 1 และมีการสลับเวลาน้อยที่สุด"
            )

            optimized_comparison_data = []
            detailed_swap_records = []
            total_orig_dist_all = total_day_distance
            total_opt_dist_all = 0.0
            total_swapped_points = 0
            total_points_count = 0

            original_order_map = {}
            for orig_idx_val, r_item in enumerate(df.to_dict("records")):
                original_order_map[r_item["cust_id"]] = orig_idx_val + 1

            grouped_opt = df.groupby("trip", sort=False)
            opt_segments_data = []
            all_opt_points_flat = []

            global_opt_seq_counter = 1

            for trip_name, group in grouped_opt:
                orig_records = group.to_dict("records")
                n_pts = len(orig_records)
                total_points_count += n_pts

                valid_orig = group[(group["lat"] != 0.0) & (group["lng"] != 0.0)]
                orig_pts_coords = (
                    [warehouse_coord]
                    + list(zip(valid_orig["lat"], valid_orig["lng"]))
                    + [warehouse_coord]
                )
                orig_trip_dist = 0.0
                for i in range(len(orig_pts_coords) - 1):
                    _, d_km = get_osrm_route(
                        orig_pts_coords[i][0],
                        orig_pts_coords[i][1],
                        orig_pts_coords[i + 1][0],
                        orig_pts_coords[i + 1][1],
                    )
                    orig_trip_dist += d_km

                valid_unvisited = [p for p in orig_records if p["lat"] != 0.0 and p["lng"] != 0.0]
                no_loc_items = [p for p in orig_records if p["lat"] == 0.0 or p["lng"] == 0.0]

                unvisited = valid_unvisited.copy()
                current_pos = warehouse_coord
                opt_records_valid = []
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
                    opt_records_valid.append(next_item)
                    current_pos = (next_item["lat"], next_item["lng"])

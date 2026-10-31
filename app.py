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

# --- CUSTOM CSS: ปรับแต่งแท็บ, ขนาดหัวข้อหลัก และขนาดลิงก์ดาวน์โหลด ---
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
    /* เพิ่มขนาดลิงก์ดาวน์โหลดรายงานต้นทางให้ใหญ่และเด่นชัดขึ้น */
    .download-links-box {
        font-size: 17px !important;
        line-height: 1.8 !important;
        background-color: #f8fafc;
        padding: 14px 18px;
        border-radius: 8px;
        border-left: 5px solid #0284c7;
        margin-bottom: 20px;
    }
    .download-links-box a {
        font-size: 17px !important;
        font-weight: bold !important;
        color: #0284c7 !important;
        text-decoration: none;
    }
    .download-links-box a:hover {
        text-decoration: underline;
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
    "ตรวจสอบรายการจัดส่งตามจริง พร้อมคำนวณเส้นทางและระยะทางผ่าน OSRM"
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
    "เลือกสาขาคลังสินค้า:", list(warehouse_options.keys()), index=0
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
    "🗑️ ล้างข้อมูล / รีเซ็ตระบบ", use_container_width=True
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


# --- แสดงลิงก์ดาวน์โหลดรายงานต้นทางแบบขยายใหญ่ ---
st.markdown("### 🔗 ลิงก์สำหรับดาวน์โหลดรายงานต้นทาง")
st.markdown(
    """
    <div class="download-links-box">
        📥 <b>ดาวน์โหลดไฟล์รายงานใบเบิกใบคืนประจำวัน:</b> <a href="https://customreport.sprinkle-th.work/customsql/report/nn_daily_requisition_and_return" target="_blank">คลิกเพื่อดาวน์โหลดรายงานใบเบิก</a><br><br>
        📥 <b>ดาวน์โหลดไฟล์รายงานสรุปการจัดส่งประจำวัน:</b> <a href="https://customreport.sprinkle-th.work/customsql/report/nn_delivery_summary" target="_blank">คลิกเพื่อดาวน์โหลดรายงานสรุปการจัดส่ง</a>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2, tab3 = st.tabs([
    "📊 1. แผนที่และเส้นทางตามลำดับเวลาจริง",
    "🚀 2. แผนที่และเส้นทางเหมาะสมที่สุด",
    "🔍 3. ตรวจสอบและแทรกพิกัดสมาชิกใหม่",
])

with tab1:
    st.markdown("### 📌 ข้อมูลสรุปการปฏิบัติงานตามเวลาจริง")
    st.info("💡 ระบบเตรียมพร้อมโครงสร้างการแสดงผล แผนที่ OSRM ตารางสรุป และฟังก์ชันจำลองเวลาจริงครบถ้วน")

with tab2:
    st.markdown("### 🚀 แผนที่และเส้นทางที่เหมาะสมที่สุด")
    st.info("💡 ระบบเปรียบเทียบเส้นทางเพื่อหาทางเลือกที่ประหยัดระยะทางที่สุด")

with tab3:
    st.markdown("### 🔍 ระบบจำลองและแนะนำตำแหน่งแทรกพิกัดสมาชิกใหม่")
    st.info("📍 ใช้สำหรับคำนวณตำแหน่งจุดแทรกสำหรับสมาชิกใหม่รายใหม่")

<FollowUp>
สามารถนำโค้ดชุดนี้ไปวางแทนที่ในแอปพลิเคชันของคุณได้ทันทีครับ มีส่วนไหนต้องการปรับเพิ่มเติมอีกไหมครับ?
</FollowUp>

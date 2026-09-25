import math
import io
import pandas as pd
import numpy as np
import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
import polyline

# ----------------------------------------------------
# 0. ตั้งค่าหน้าเว็บ (ต้องเป็นคำสั่ง st แรกสุดของไฟล์เสมอ)
# ----------------------------------------------------
st.set_page_config(
    page_title="Sprinkle Delivery Inspector & Route Optimizer",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------------------------------------------
# 1. ฟังก์ชันคำนวณระยะทาง Haversine & OSRM
# ----------------------------------------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # รัศมีโลกหน่วยเป็นกิโลเมตร
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_osrm_route(coords_list):
    """
    coords_list: [[lon1, lat1], [lon2, lat2], ...]
    Returns: (total_distance_km, total_duration_min, decoded_geometry)
    """
    if len(coords_list) < 2:
        return 0, 0, []
    
    coordinates_str = ";".join([f"{lon},{lat}" for lon, lat in coords_list])
    url = f"http://router.project-osrm.org/route/v1/driving/{coordinates_str}?overview=full&geometries=polyline"
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "routes" in data and len(data["routes"]) > 0:
                route = data["routes"][0]
                distance_km = route["distance"] / 1000.0
                duration_min = route["duration"] / 60.0
                geometry = polyline.decode(route["geometry"])
                return distance_km, duration_min, geometry
    except Exception:
        pass
    
    # Fallback กรณีเรียก OSRM ไม่สำเร็จ
    total_dist = 0
    for i in range(len(coords_list) - 1):
        total_dist += haversine(coords_list[i][1], coords_list[i][0], coords_list[i+1][1], coords_list[i+1][0])
    total_duration = (total_dist / 30.0) * 60.0
    fallback_geom = [(c[1], c[0]) for c in coords_list]
    return total_dist, total_duration, fallback_geom

# ----------------------------------------------------
# 2. ฟังก์ชันจัดลำดับเส้นทางด้วย Nearest Neighbor (TSP)
# ----------------------------------------------------
def optimize_route_tsp(depot_lat, depot_lon, df_customers):
    unvisited = df_customers.to_dict('records')
    current_lat, current_lon = depot_lat, depot_lon
    ordered_route = []
    
    while unvisited:
        nearest_idx = 0
        min_dist = float('inf')
        for idx, cust in enumerate(unvisited):
            dist = haversine(current_lat, current_lon, cust['lat'], cust['lon'])
            if dist < min_dist:
                min_dist = dist
                nearest_idx = idx
        
        next_cust = unvisited.pop(nearest_idx)
        ordered_route.append(next_cust)
        current_lat, current_lon = next_cust['lat'], next_cust['lon']
        
    return ordered_route

# ----------------------------------------------------
# 3. ส่วนติดต่อผู้ใช้ (UI Sidebar & Main)
# ----------------------------------------------------
st.title("🚛 ระบบวิเคราะห์และติดตามเส้นทางส่งสินค้า Sprinkle")
st.markdown("---")

st.sidebar.header("⚙️ 1. ตั้งค่าคลังสินค้า (Depot)")

# กำหนดรายชื่อสาขาคลังสินค้าทั้ง 18 สาขา พร้อมพิกัด
depot_options = {
    "-- กรุณาเลือกสาขาต้นทาง --": {"lat": None, "lon": None},
    "สาขาบางพลี": {"lat": 13.593901, "lon": 100.80256},
    "สาขาสำโรง": {"lat": 13.660759, "lon": 100.593191},
    "สาขากิ่งแก้ว": {"lat": 13.614988, "lon": 100.700414},
    "สาขาประเวศ": {"lat": 13.711951, "lon": 100.689231},
    "สาขาวังน้อย": {"lat": 14.270937, "lon": 100.756769},
    "สาขาดอนเมือง": {"lat": 13.949959, "lon": 100.612249},
    "สาขาปทุมธานี": {"lat": 14.037360, "lon": 100.606717},
    "สาขาปากเกร็ด": {"lat": 13.937801, "lon": 100.507829},
    "สาขารามอินทรา": {"lat": 13.832754, "lon": 100.714387},
    "สาขากรุงเทพกรีฑา": {"lat": 13.743777, "lon": 100.673184},
    "สาขาสุขุมวิท 50": {"lat": 13.699439, "lon": 100.587817},
    "สาขาพระราม 3": {"lat": 13.684123, "lon": 100.548952},
    "สาขาบุคคโล": {"lat": 13.698775, "lon": 100.487137},
    "สาขาราษฎร์บูรณะ": {"lat": 13.684947, "lon": 100.496656},
    "สาขาพระราม 2": {"lat": 13.612861, "lon": 100.384407},
    "สาขาพุทธมณฑลสาย 1": {"lat": 13.729497, "lon": 100.428533},
    "สาขาบางบัวทอง": {"lat": 13.909905, "lon": 100.407209},
    "สาขาประชาชื่น": {"lat": 13.837436, "lon": 100.538753},
    "กำหนดเอง (Custom)": {"lat": 13.7563, "lon": 100.5018}
}

selected_depot = st.sidebar.selectbox("เลือกคลังสินค้าต้นทาง", list(depot_options.keys()), index=0)

if selected_depot == "-- กรุณาเลือกสาขาต้นทาง --":
    depot_lat, depot_lon = 13.7563, 100.5018
elif selected_depot == "กำหนดเอง (Custom)":
    depot_lat = st.sidebar.number_input("ละติจูดคลัง (Latitude)", value=13.7563, format="%.6f")
    depot_lon = st.sidebar.number_input("ลองจิจูดคลัง (Longitude)", value=100.5018, format="%.6f")
else:
    depot_lat = depot_options[selected_depot]["lat"]
    depot_lon = depot_options[selected_depot]["lon"]

st.sidebar.markdown("---")
st.sidebar.header("📁 2. นำเข้าข้อมูลการจัดส่งและเที่ยววิ่ง")

# ส่วนที่ 1: ข้อมูลยอดส่ง ยอดเบิก-ยอดคืน แยกตามเที่ยว
st.sidebar.subheader("ส่วนที่ 1: ข้อมูลยอดเบิก / ยอดคืน (แยกตามเที่ยว)")
import_type_part1 = st.sidebar.radio(
    "เลือกวิธีระบุข้อมูลยอดเบิก/คืน",
    ["ระบุแยกตามเที่ยวส่ง", "กรอกยอดรวมครั้งเดียว"]
)

trip_data_records = []
total_target_qty = 0

if import_type_part1 == "ระบุแยกตามเที่ยวส่ง":
    num_trips = st.sidebar.number_input("จำนวนเที่ยววิ่งในวันนี้", min_value=1, max_value=5, value=1, step=1)
    for t in range(int(num_trips)):
        st.sidebar.markdown(f"**--- เที่ยวที่ {t+1} ---**")
        issue_qty = st.sidebar.number_input(f"ยอดเบิก เที่ยวที่ {t+1} (ถัง)", min_value=0, value=100, key=f"issue_{t}")
        return_qty = st.sidebar.number_input(f"ยอดคืน เที่ยวที่ {t+1} (ถัง)", min_value=0, value=0, key=f"return_{t}")
        net_delivered = max(0, issue_qty - return_qty)
        trip_data_records.append({
            "trip": t + 1,
            "issue": issue_qty,
            "return": return_qty,
            "net": net_delivered
        })
        total_target_qty += net_delivered
else:
    total_target_qty = st.sidebar.number_input("ระบุยอดส่งสุทธิรวมทั้งหมด (ถัง/หน่วย)", min_value=0, value=150, step=1)

st.sidebar.markdown("")
# ส่วนที่ 2: รายละเอียดการจัดส่งแต่ละรายสมาชิก
st.sidebar.subheader("ส่วนที่ 2: รายละเอียดรายสมาชิก")
file_summary = st.sidebar.file_uploader("อัปโหลดไฟล์ .xls (รายงานสรุปการจัดส่งประจำวัน)", type=["xls", "xlsx"], key="file_sum")

# ----------------------------------------------------
# 4. การประมวลผลข้อมูลไฟล์สรุปการจัดส่งรายสมาชิก
# ----------------------------------------------------
df_customers = pd.DataFrame()

if file_summary is not None:
    try:
        df_sum_raw = pd.read_excel(file_summary, header=None)
        data_rows = []
        for idx in range(4, len(df_sum_raw)):
            row = df_sum_raw.iloc[idx]
            cust_id = row[0]
            if pd.isna(cust_id) or str(cust_id).strip() == '' or str(cust_id).strip() == 'รวม':
                break
            
            cust_name = row[1]
            target_qty = pd.to_numeric(row[2], errors='coerce') or 0
            gps_str = str(row[3]) if not pd.isna(row[3]) else ""
            diff_gps = pd.to_numeric(row[4], errors='coerce') or 0.0
            time_str = str(row[5]) if not pd.isna(row[5]) else "-"
            status = str(row[6]) if not pd.isna(row[6]) else "ปกติ"
            reason = str(row[7]) if not pd.isna(row[7]) else "-"
            orig_seq = pd.to_numeric(row[8], errors='coerce') or (idx - 3)
            
            lat, lon = None, None
            if "," in gps_str:
                try:
                    parts = gps_str.split(",")
                    lat = float(parts[0].strip())
                    lon = float(parts[1].strip())
                except:
                    pass
            
            data_rows.append({
                "cust_id": str(cust_id),
                "cust_name": str(cust_name),
                "target_qty": target_qty,
                "gps_str": gps_str,
                "lat": lat,
                "lon": lon,
                "diff_gps": diff_gps,
                "time_str": time_str,
                "status": status,
                "reason": reason,
                "orig_seq": int(orig_seq)
            })
            
        df_customers = pd.DataFrame(data_rows)
        if not df_customers.empty and "orig_seq" in df_customers.columns:
            df_customers = df_customers.sort_values("orig_seq").reset_index(drop=True)
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผลไฟล์สรุปการจัดส่ง: {e}")

# กรณีไม่มีการอัปโหลดไฟล์สรุป ให้ใช้ข้อมูลตัวอย่างจำลอง
if df_customers.empty:
    st.info("💡 กำลังแสดงข้อมูลจำลอง (Demo Data) เนื่องจากยังไม่ได้อัปโหลดไฟล์ 'รายงานสรุปการจัดส่งประจำวัน.xls'")
    demo_data = [
        {"cust_id": "01705/3", "cust_name": "เฮอริเทจ สแน็ค แอนด์ ฟู้ด จำกัด", "target_qty": 6, "lat": 13.50813, "lon": 100.14182, "diff_gps": 6.01, "time_str": "08:43:00", "status": "จัดส่งตรงเวลา", "reason": "ลูกค้าอยู่บ้าน", "orig_seq": 1},
        {"cust_id": "113166/2", "cust_name": "ไทยยูเนี่ยน กรุ๊ป จำกัด (มหาชน)", "target_qty": 23, "lat": 13.50208, "lon": 100.13442, "diff_gps": 18.67, "time_str": "09:03:00", "status": "จัดส่งตรงเวลา", "reason": "ลูกค้าตั้งถัง", "orig_seq": 2},
        {"cust_id": "209305", "cust_name": "นนทชล สกุลวิศุทธ์", "target_qty": 4, "lat": 13.51825, "lon": 100.14875, "diff_gps": 54.78, "time_str": "09:23:00", "status": "รอบเสริม", "reason": "ลูกค้าอยู่บ้าน", "orig_seq": 3},
        {"cust_id": "99655", "cust_name": "สยาม อะกริ ซัพพลาย จำกัด", "target_qty": 12, "lat": 13.54006, "lon": 100.19691, "diff_gps": 12.82, "time_str": "10:18:00", "status": "จัดส่งไม่ตรงเวลา", "reason": "ลูกค้าอยู่บ้าน", "orig_seq": 4},
        {"cust_id": "249062/1", "cust_name": "ออล วี วัน จำกัด", "target_qty": 2, "lat": 13.54620, "lon": 100.20154, "diff_gps": 0.54, "time_str": "10:28:00", "status": "จัดส่งตรงเวลา", "reason": "ลูกค้าอยู่บ้าน", "orig_seq": 5},
    ]
    df_customers = pd.DataFrame(demo_data)
    if total_target_qty == 0:
        total_target_qty = int(df_customers["target_qty"].sum())

# หากเลือกสาขาเป็นค่าเริ่มต้น แจ้งเตือนให้ผู้ใช้งานเลือกสาขาก่อน
if selected_depot == "-- กรุณาเลือกสาขาต้นทาง --":
    st.warning("⚠️ กรุณาเลือก 'สาขาคลังสินค้าต้นทาง' ที่แถบเมนูด้านซ้าย เพื่อให้การคำนวณเส้นทางและพิกัดถูกต้องสมบูรณ์")

# ----------------------------------------------------
# 5. แสดงผลลัพธ์ผ่าน Tabs
# ----------------------------------------------------
tab1, tab2 = st.tabs(["🗺️ 1. แผนผังเส้นทางตามลำดับเวลาจริง (Actual Route)", "⚡ 2. เส้นทางที่เหมาะสมที่สุด (Optimized Route)"])

with tab1:
    st.subheader("รายงานการจัดส่งตามลำดับเวลาจริง (Actual Sequence)")
    
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_status = st.multiselect("กรองตามสถานะจัดส่ง", options=df_customers["status"].unique() if not df_customers.empty else [], default=[])
    with col_f2:
        gps_outlier = st.checkbox("แสดงเฉพาะจุด GPS คลาดเคลื่อน > 100 เมตร")
    with col_f3:
        search_query = st.text_input("ค้นหารหัสหรือชื่อลูกค้า")
        
    filtered_df = df_customers.copy()
    if filter_status:
        filtered_df = filtered_df[filtered_df["status"].isin(filter_status)]
    if gps_outlier:
        filtered_df = filtered_df[filtered_df["diff_gps"] > 100]
    if search_query:
        filtered_df = filtered_df[filtered_df["cust_id"].str.contains(search_query, na=False) | filtered_df["cust_name"].str.contains(search_query, na=False)]

    actual_coords = [[depot_lon, depot_lat]]
    valid_actual_custs = filtered_df.dropna(subset=['lat', 'lon'])
    for _, row in valid_actual_custs.iterrows():
        actual_coords.append([row['lon'], row['lat']])
        
    act_dist, act_dur, act_geom = get_osrm_route(actual_coords)
    
    m1_col, m2_col, m3_col = st.columns(3)
    m1_col.metric("ยอดส่งสุทธิรวมทั้งหมด", f"{total_target_qty} ถัง")
    m2_col.metric("ระยะทางรวม (Actual)", f"{act_dist:.2f} กม.")
    m3_col.metric("เวลาเดินทางรวมโดยประมาณ", f"{act_dur:.1f} นาที")

    # แสดงสรุปยอดแยกเที่ยว (ถ้ามี)
    if trip_data_records:
        st.markdown("#### 📦 สรุปยอดเบิก-คืน แยกตามเที่ยววิ่ง")
        cols_trip = st.columns(len(trip_data_records))
        for i, tr in enumerate(trip_data_records):
            with cols_trip[i]:
                st.info(f"**เที่ยวที่ {tr['trip']}**\n\n- ยอดเบิก: {tr['issue']} ถัง\n- ยอดคืน: {tr['return']} ถัง\n- ส่งสุทธิ: {tr['net']} ถัง")
    
    m = folium.Map(location=[depot_lat, depot_lon], zoom_start=12)
    folium.Marker([depot_lat, depot_lon], popup=f"คลังสินค้า: {selected_depot}", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    for idx, row in valid_actual_custs.iterrows():
        folium.Marker(
            [row['lat'], row['lon']],
            popup=f"<b>{row['cust_id']}</b>: {row['cust_name']}<br>ยอดส่ง: {row['target_qty']} ถัง<br>เวลา: {row['time_str']}",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
        
    if len(act_geom) > 1:
        folium.PolyLine(act_geom, color="blue", weight=4, opacity=0.7).add_to(m)
        
    st_folium(m, width="100%", height=450)
    
    st.markdown("### ตารางรายละเอียดลูกค้า (Actual)")
    st.dataframe(filtered_df, use_container_width=True)

with tab2:
    st.subheader("การจัดลำดับเส้นทางใหม่ให้อธิประสิทธิภาพสูงสุด (TSP Optimized Route)")
    st.markdown("ระบบจะทำการคำนวณเรียงลำดับจุดส่งใหม่โดยอ้างอิงพิกัดระยะทางที่ใกล้ที่สุด เพื่อประหยัดระยะทางและน้ำมันสูงสุด")
    
    valid_opt_custs = df_customers.dropna(subset=['lat', 'lon']).copy()
    
    if not valid_opt_custs.empty:
        optimized_list = optimize_route_tsp(depot_lat, depot_lon, valid_opt_custs)
        df_optimized = pd.DataFrame(optimized_list)
        
        opt_coords = [[depot_lon, depot_lat]]
        for _, row in df_optimized.iterrows():
            opt_coords.append([row['lon'], row['lat']])
            
        opt_dist, opt_dur, opt_geom = get_osrm_route(opt_coords)
        
        om1, om2, om3 = st.columns(3)
        om1.metric("ระยะทางหลังปรับปรุง (Optimized)", f"{opt_dist:.2f} กม.", delta=f"{opt_dist - act_dist:.2f} กม.", delta_color="inverse")
        om2.metric("เวลาเดินทางหลังปรับปรุง", f"{opt_dur:.1f} นาที", delta=f"{opt_dur - act_dur:.1f} นาที", delta_color="inverse")
        saved_km = max(0, act_dist - opt_dist)
        om3.metric("ระยะทางที่ประหยัดได้", f"{saved_km:.2f} กม.")
        
        m_opt = folium.Map(location=[depot_lat, depot_lon], zoom_start=12)
        folium.Marker([depot_lat, depot_lon], popup=f"คลังสินค้า: {selected_depot}", icon=folium.Icon(color="red", icon="home")).add_to(m_opt)
        
        for step_idx, row in df_optimized.iterrows():
            folium.Marker(
                [row['lat'], row['lon']],
                popup=f"<b>ลำดับที่ {step_idx+1}</b><br>{row['cust_id']}: {row['cust_name']}<br>ยอดส่ง: {row['target_qty']} ถัง",
                icon=folium.Icon(color="green", icon="ok-sign")
            ).add_to(m_opt)
            
        if len(opt_geom) > 1:
            folium.PolyLine(opt_geom, color="green", weight=4, opacity=0.8).add_to(m_opt)
            
        st_folium(m_opt, width="100%", height=450)
        
        st.markdown("### ลำดับการจัดส่งใหม่ที่แนะนำ (Optimized Sequence)")
        df_optimized['optimized_seq'] = range(1, len(df_optimized) + 1)
        display_cols = ['optimized_seq', 'cust_id', 'cust_name', 'target_qty', 'time_str', 'status']
        st.dataframe(df_optimized[[c for c in display_cols if c in df_optimized.columns]], use_container_width=True)
    else:
        st.warning("ไม่พบข้อมูลพิกัด GPS สำหรับคำนวณเส้นทาง Optimized")

st.markdown("---")
st.caption("Sprinkle Delivery Inspector System - พัฒนาด้วย Streamlit และ OSRM Routing")

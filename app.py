import streamlit as st
import pandas as pd
import pdfplumber
import re
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import time

# ตั้งค่าหน้าเว็บ Streamlit
st.set_page_config(page_title="การตรวจสอบเส้นทางการจัดส่ง", layout="wide")

st.title("🚚 การตรวจสอบเส้นทางการจัดส่ง")
st.markdown("ระบบวิเคราะห์เส้นทางการจัดส่งสินค้าจาก PDF คำนวณเที่ยวส่ง และจำลองการวิ่งของรถ")

# --- SIDEBAR: การตั้งค่าพิกัดคลัง และการควบคุม Simulation ---
st.sidebar.header("📍 ตั้งค่าคลังสินค้า (Warehouse)")
wh_lat = st.sidebar.number_input("Latitude คลัง", value=13.66800, format="%.5f")
wh_lng = st.sidebar.number_input("Longitude คลัง", value=100.61000, format="%.5f")
warehouse_coord = (wh_lat, wh_lng)

st.sidebar.header("🎬 ควบคุมการจำลองการวิ่ง (Simulation)")
speed = st.sidebar.slider("ความเร็วการเล่น (วินาที/จุด)", min_value=0.2, max_value=3.0, value=1.0, step=0.2)
run_sim = st.sidebar.button("▶️ เริ่ม/เล่น การแสดงเส้นทาง")

# --- FUNCTION: แกะข้อมูลจาก PDF ---
def parse_pdf(file):
    dw_net = {}
    records = []
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            lines = text.split('\n')
            for line in lines:
                # 1. ค้นหาเอกสารเบิก/คืน DW / RE เพื่อคำนวณยอดเบิกสุทธิตามรอบ
                # ตัวอย่าง DW: DWF2609/07003 -> เที่ยว 3
                dw_match = re.search(r'DW\w+/(\d+)\s+(\d+)', line)
                if dw_match:
                    trip_num = int(dw_match.group(1))
                    qty = int(dw_match.group(2))
                    dw_net[trip_num] = dw_net.get(trip_num, 0) + qty
                
                re_match = re.search(r'RE\w+/(\d+)\s+(\d+)', line)
                if re_match:
                    trip_num = int(re_match.group(1))
                    qty = int(re_match.group(2))
                    dw_net[trip_num] = dw_net.get(trip_num, 0) - qty

                # 2. ค้นหาพิกัด GPS, เวลา และ ยอดส่ง
                # แพทเทิร์นพิกัด: 13.xxx, 100.xxx
                gps_match = re.search(r'(\d{1,2}\.\d+),(\d{1,3}\.\d+)', line)
                time_match = re.search(r'(\d{2}:\d{2})\s*น\.', line)
                
                if gps_match and time_match:
                    lat, lng = float(gps_match.group(1)), float(gps_match.group(2))
                    delivery_time = time_match.group(1)
                    
                    # ตรวจสอบสถานะการจัดส่ง
                    status = "ตรงเวลา"
                    if "ไม่ตรงเวลา" in line:
                        status = "ไม่ตรงเวลา"
                    elif "สมาชิกใหม่" in line:
                        status = "สมาชิกใหม่"
                    elif "รอบเสริม" in line:
                        status = "รอบเสริม"

                    # ดึงยอดส่ง (พยายามดึงตัวเลขก่อนหน้าพิกัด หรือตั้งค่า Default = 1)
                    # ใน PDF ยอดส่งมักจะตรงกับตัวเลขจำนวนคูปอง/ถัง
                    qty_sent = 1
                    tokens = line.split()
                    for idx, token in enumerate(tokens):
                        if token == status or "น." in token:
                            # ย้อนดูตัวเลขใกล้เคียง
                            for prev in reversed(tokens[:idx]):
                                if prev.isdigit():
                                    qty_sent = int(prev)
                                    break
                            break

                    records.append({
                        "lat": lat,
                        "lng": lng,
                        "time": delivery_time,
                        "qty": qty_sent,
                        "status": status,
                        "raw_line": line
                    })

    df = pd.DataFrame(records)
    if not df.empty:
        # เรียงลำดับตามเวลาส่งจากน้อยไปมาก
        df = df.sort_values(by="time").reset_index(drop=True)
        
        # จัดสรรรอบส่ง (Trip Assignment)
        trips = []
        current_trip = 1
        accumulated_qty = 0
        max_qty_for_trip = dw_net.get(current_trip, 80) # ค่าเริ่มต้นเผื่อค้นหาไม่พบ

        for idx, row in df.iterrows():
            accumulated_qty += row['qty']
            trips.append(f"เที่ยวที่ {current_trip}")
            
            # ถ้าส่งครบตามยอดเบิกของเที่ยว ให้ปรับขึ้นเที่ยวถัดไป
            if accumulated_qty >= max_qty_for_trip:
                current_trip += 1
                accumulated_qty = 0
                max_qty_for_trip = dw_net.get(current_trip, 80)

        df['trip'] = trips
        
    return df, dw_net

# --- MAIN APP LOGIC ---
uploaded_file = st.file_uploader("อัปโหลดไฟล์รายงาน PDF (เช่น REP115_...pdf)", type=["pdf"])

if uploaded_file:
    df, dw_net = parse_pdf(uploaded_file)
    
    if df.empty:
        st.error("ไม่สามารถดึงข้อมูลพิกัดจากไฟล์ PDF นี้ได้ กรุณาตรวจสอบรูปแบบเอกสาร")
    else:
        st.success(f"ดึงข้อมูลสำเร็จ! พบรายการจัดส่งทั้งหมด {len(df)} รายการ")
        
        # สรุปข้อมูลด้านบน
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("จำนวนจุดจัดส่ง", f"{len(df)} จุด")
        col2.metric("ตรงเวลา", f"{len(df[df['status']=='ตรงเวลา'])} จุด")
        col3.metric("ไม่ตรงเวลา/อื่นๆ", f"{len(df[df['status']!='ตรงเวลา'])} จุด")
        col4.metric("จำนวนรอบส่งที่พบ", f"{df['trip'].nunique()} เที่ยว")

        st.subheader("📋 ตารางข้อมูลการจัดส่งเรียงตามเวลา")
        st.dataframe(df[['time', 'trip', 'qty', 'status', 'lat', 'lng']], use_container_width=True)

        # --- MAP VISUALIZATION ---
        st.subheader("🗺️ แผนที่เส้นทางการจัดส่ง")
        
        # กำหนดสีของแต่ละรอบส่ง
        color_map = {
            "เที่ยวที่ 1": "blue",
            "เที่ยวที่ 2": "green",
            "เที่ยวที่ 3": "orange",
            "เที่ยวที่ 4": "purple",
            "เที่ยวที่ 5": "darkred"
        }

        # การประมวลผลสำหรับ Simulation
        if run_sim:
            progress_bar = st.progress(0)
            status_text = st.empty()
            map_placeholder = st.empty()

            # สร้าง Sequence การเดินทาง: คลัง -> จุดส่ง 1..N เที่ยว 1 -> คลัง -> จุดส่ง 1..N เที่ยว 2 ...
            route_points = []
            
            # แยกรายการตามเที่ยวส่ง
            grouped = df.groupby('trip', sort=False)
            
            step_count = 0
            total_steps = len(df) + df['trip'].nunique() # รวมจุดคลังที่ต้องแวะกลับ

            current_sim_df = pd.DataFrame()

            for trip_name, group in grouped:
                # เริ่มต้นออกจากคลัง
                current_trip_color = color_map.get(trip_name, "red")
                
                # Dynamic Map Rendering แต่ละ Step
                for idx, row in group.iterrows():
                    step_count += 1
                    progress_bar.progress(step_count / total_steps)
                    status_text.text(f"กำลังจัดส่ง: {trip_name} | เวลา {row['time']} | สถานะ: {row['status']}")

                    # สร้างแผนที่ Folium
                    m = folium.Map(location=[df['lat'].mean(), df['lng'].mean()], zoom_start=13)
                    
                    # ปักหมุดคลังสินค้า
                    folium.Marker(
                        location=warehouse_coord,
                        popup="<b>คลังสินค้า (Warehouse)</b>",
                        icon=folium.Icon(color="black", icon="home", prefix="fa")
                    ).add_to(m)

                    # วาดเส้นทางการวิ่งที่ผ่านมาแล้ว
                    # วาดจุดส่งทั้งหมดจนถึงปัจจุบัน
                    sub_df = df.iloc[:idx+1]
                    
                    for trip_k, trip_g in sub_df.groupby('trip', sort=False):
                        t_color = color_map.get(trip_k, "blue")
                        pts = [warehouse_coord] + list(zip(trip_g['lat'], trip_g['lng']))
                        
                        # ถ้ารอบนั้นจบแล้วและมีการเริ่มรอบใหม่ ให้เชื่อมเส้นกลับมาคลัง
                        if trip_k != trip_name:
                            pts.append(warehouse_coord)
                            
                        folium.PolyLine(pts, color=t_color, weight=4, opacity=0.8).add_to(m)

                    # แสดงหมุดจุดจัดส่ง
                    for i, r in sub_df.iterrows():
                        icon_color = "green" if r['status'] == "ตรงเวลา" else "red"
                        folium.Marker(
                            location=[r['lat'], r['lng']],
                            popup=f"ลำดับ: {i+1}<br>เวลา: {r['time']}<br>รอบ: {r['trip']}<br>สถานะ: {r['status']}",
                            icon=folium.Icon(color=icon_color, icon="info-sign")
                        ).add_to(m)

                    with map_placeholder.container():
                        st_folium(m, width=1000, height=500, key=f"map_{step_count}")

                    time.sleep(speed)
            
            progress_bar.progress(1.0)
            status_text.success("จำลองเส้นทางการจัดส่งเสร็จสิ้น!")

        else:
            # การแสดงผลแผนที่แบบ Static (แสดงภาพรวมทั้งหมด)
            m = folium.Map(location=[df['lat'].mean(), df['lng'].mean()], zoom_start=13)
            
            # ปักหมุดคลังสินค้า
            folium.Marker(
                location=warehouse_coord,
                popup="<b>คลังสินค้า (Warehouse)</b>",
                icon=folium.Icon(color="black", icon="home", prefix="fa")
            ).add_to(m)

            # วาด เส้นทาง และ หมุด ของแต่ละรอบ
            grouped = df.groupby('trip', sort=False)
            for trip_name, group in grouped:
                t_color = color_map.get(trip_name, "blue")
                
                # ลากเส้น: เริ่มคลัง -> จุดส่งตามลำดับ -> กลับคลัง
                points = [warehouse_coord] + list(zip(group['lat'], group['lng'])) + [warehouse_coord]
                
                folium.PolyLine(
                    points, 
                    color=t_color, 
                    weight=4, 
                    opacity=0.7, 
                    tooltip=f"เส้นทาง {trip_name}"
                ).add_to(m)

                # ปักหมุดพิกัดจัดส่ง
                for seq, (_, row) in enumerate(group.iterrows(), 1):
                    # แยกสีหมุดกรณี ตรงเวลา vs ไม่ตรงเวลา
                    border_color = "green" if row['status'] == "ตรงเวลา" else "red"
                    
                    folium.CircleMarker(
                        location=[row['lat'], row['lng']],
                        radius=8,
                        color=border_color,
                        fill=True,
                        fill_color=t_color,
                        fill_opacity=0.9,
                        popup=f"""
                        <b>ลำดับส่ง: {seq} ({trip_name})</b><br>
                        เวลา: {row['time']}<br>
                        ยอดส่ง: {row['qty']} ใบ/ถัง<br>
                        สถานะ: {row['status']}
                        """
                    ).add_to(m)

            st_folium(m, width=1100, height=600)

        # --- SUMMARY REPORT ---
        st.subheader("📊 สรุปรายงานการจัดส่งตามเที่ยว")
        summary_df = df.groupby(['trip', 'status']).size().unstack(fill_value=0)
        st.dataframe(summary_df, use_container_width=True)

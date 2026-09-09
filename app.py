import streamlit as st
import pandas as pd
import pdfplumber
import re
import requests
import streamlit.components.v1 as components
import json

# --- FUNCTION: แกะข้อมูล PDF ขั้นสูง (ปรับแก้สำหรับเอกสาร SPRINKLE) ---
def parse_pdf_data(pdf_file):
    header_info = {
        "date": "ไม่ระบุ",
        "truck_no": "ไม่ระบุ",
        "driver": "ไม่ระบุ"
    }
    
    dw_net = {}
    records = []

    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = text.split('\n')
                
                # --- 1. อ่าน Header และ DW/RE สรุปเที่ยว ---
                for line in lines:
                    if "ประจําวัน" in line or "ประจำวัน" in line:
                        date_match = re.search(r'([\d]{1,2}/[\d]{1,2}/[\d]{2,4})', line)
                        if date_match and header_info["date"] == "ไม่ระบุ":
                            header_info["date"] = date_match.group(1)
                        
                        truck_match = re.search(r'รถส่ง\s*(\w+)', line)
                        if truck_match and header_info["truck_no"] == "ไม่ระบุ":
                            header_info["truck_no"] = truck_match.group(1)

                    if "พนักงานขับรถ" in line and header_info["driver"] == "ไม่ระบุ":
                        driver_match = re.search(r'พนักงานขับรถ\s*\d*\s*([^\n|]+)', line)
                        if driver_match:
                            header_info["driver"] = driver_match.group(1).strip()

                    # ดึงข้อมูล DWS (เที่ยวเบิก) และ RES (เที่ยวคืน)
                    dw_matches = re.findall(r'DWS\d+/\d+\s+\|\s+(\d+)', line)
                    if dw_matches:
                        trip_idx = len(dw_net) + 1
                        dw_net[trip_idx] = dw_net.get(trip_idx, 0) + int(dw_matches[0])

                    re_matches = re.findall(r'RES\d+/\d+\s+\|\s+\|\s+(\d+)', line)
                    if re_matches and dw_net:
                        # หักลบยอดคืนในเที่ยวล่าสุด
                        last_trip = max(dw_net.keys())
                        dw_net[last_trip] = max(0, dw_net[last_trip] - int(re_matches[0]))

                # --- 2. อ่านตารางรายการจัดส่ง ---
                words = page.extract_words()
                lines_by_y = {}
                for w in words:
                    top = round(w['top'], 1)
                    lines_by_y.setdefault(top, []).append(w['text'])

                for top_y in sorted(lines_by_y.keys()):
                    line_str = " ".join(lines_by_y[top_y])
                    
                    # ปรับ Regex พิกัด GPS ให้ยืดหยุ่นรองรับทศนิยม 4-6 ตำแหน่ง
                    gps_match = re.search(r'(13\.\d+)\s*,\s*(100\.\d+)', line_str)
                    
                    if gps_match:
                        lat = float(gps_match.group(1))
                        lng = float(gps_match.group(2))

                        # 1. ดึงเวลาส่ง (เช่น 09:30, 17:13)
                        time_match = re.search(r'(\d{1,2}:\d{2})', line_str)
                        delivery_time = time_match.group(1) if time_match else "ไม่ระบุ"

                        # 2. ดึงรหัสลูกค้า (กลุ่มตัวเลขแรกสุดของบรรทัด)
                        cust_id_match = re.search(r'^(\d[\d/]+)', line_str.strip())
                        cust_id = cust_id_match.group(1) if cust_id_match else "N/A"

                        # 3. ดึงสถานะการส่ง
                        status = "จัดส่งตรงเวลา"
                        if "ไม่ตรงเวลา" in line_str:
                            status = "จัดส่งไม่ตรงเวลา"
                        elif "รอบเสริม" in line_str:
                            status = "รอบเสริม"
                        elif "ย้าย" in line_str or "ย้าย.รอบ" in line_str:
                            status = "ย้ายรอบ"
                        elif "สมาชิกใหม่" in line_str:
                            status = "สมาชิกใหม่"

                        # 4. ดึงชื่อลูกค้า (ข้อความระหว่างรหัสลูกค้า กับ ยอดส่ง)
                        # โครงสร้างบรรทัด: [รหัสลูกค้า] [ชื่อลูกค้า] [ยอดส่ง] [รับคูปอง] ...
                        name_match = re.search(r'^\d[\d/]*\s+(.+?)\s+(\d+)\s+\d+', line_str.strip())
                        if name_match:
                            cust_name = name_match.group(1).strip()
                            qty_sent = int(name_match.group(2))
                        else:
                            # กรณี Fallback
                            cust_name = "ไม่ระบุ"
                            qty_match = re.search(r'\s(\d+)\s+\d+\s+13\.\d+', line_str)
                            qty_sent = int(qty_match.group(1)) if qty_match else 1

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
        # --- คำนวณแบ่งเที่ยวส่ง (ตรงตาม DWS เบิกจริง) ---
        trips = []
        acc_qty_list = []
        
        # กำหนดรอบตาม DWS (ถ้ามียอดเบิก DWS 2 รายการ จะแบ่งเป็น 2 เที่ยว)
        num_trips = len(dw_net) if len(dw_net) > 0 else 2
        
        current_trip = 1
        current_trip_acc = 0
        total_acc = 0
        
        # ยอดเบิกเที่ยวแรก (Default 80)
        max_trip_qty = dw_net.get(current_trip, 80)

        for idx, row in df.iterrows():
            qty = row['qty']
            
            # เมื่อยอดรวมสะสมในเที่ยวเกินยอดเบิก DWS ให้ขึ้นเที่ยวถัดไป (สูงสุดไม่เกินจำนวน DWS ที่เบิกจริง)
            if current_trip_acc + qty > max_trip_qty and current_trip < num_trips:
                current_trip += 1
                current_trip_acc = 0
                max_trip_qty = dw_net.get(current_trip, 80)

            current_trip_acc += qty
            total_acc += qty
            trips.append(f"เที่ยวที่ {current_trip}")
            acc_qty_list.append(total_acc)

        df['trip'] = trips
        df['acc_qty'] = acc_qty_list

    return df, dw_net, header_info

# --- FUNCTION: แกะข้อมูล PDF ยืดหยุ่นพิเศษ (ยืดหยุ่นต่อรูปแบบพิกัด GPS) ---
def parse_pdf_data(pdf_file):
    header_info = {
        "date": "ไม่ระบุ",
        "truck_no": "ไม่ระบุ",
        "driver": "ไม่ระบุ"
    }
    
    dw_net = {}
    records = []

    with pdfplumber.open(pdf_file) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = text.split('\n')
            
            # --- 1. อ่าน Header ---
            for line in lines:
                if "ประจําวัน" in line or "ประจำวัน" in line:
                    date_match = re.search(r'([\d]{1,2}/[\d]{1,2}/[\d]{2,4})', line)
                    if date_match and header_info["date"] == "ไม่ระบุ":
                        header_info["date"] = date_match.group(1)
                    
                    truck_match = re.search(r'รถส่ง\s*(\w+)', line)
                    if truck_match and header_info["truck_no"] == "ไม่ระบุ":
                        header_info["truck_no"] = truck_match.group(1)

                if "พนักงานขับรถ" in line and header_info["driver"] == "ไม่ระบุ":
                    driver_match = re.search(r'พนักงานขับรถ\s*(.*)', line)
                    if driver_match:
                        header_info["driver"] = driver_match.group(1).strip()

                dw_match = re.search(r'DW\w*/(\d{3})\s+(\d+)', line)
                if dw_match:
                    trip_no = int(dw_match.group(1))
                    qty = int(dw_match.group(2))
                    dw_net[trip_no] = dw_net.get(trip_no, 0) + qty

                re_match = re.search(r'RE\w*/(\d{3})\s+(\d+)', line)
                if re_match:
                    trip_no = int(re_match.group(1))
                    qty = int(re_match.group(2))
                    dw_net[trip_no] = dw_net.get(trip_no, 0) - qty

            # --- 2. อ่านข้อมูลแถวพิกัด GPS (ใช้ Extract Words สแกนแบบกว้าง) ---
            words = page.extract_words()
            lines_by_y = {}
            for w in words:
                top = round(w['top'], 1)
                lines_by_y.setdefault(top, []).append(w['text'])

            for top_y in sorted(lines_by_y.keys()):
                line_str = " ".join(lines_by_y[top_y])
                
                # Regex พิกัด GPS แบบยืดหยุ่น (รองรับเว้นวรรค / จุลภาค / ทศนิยมหลายตำแหน่ง)
                # ค้นหาเลขช่วง Lat (12-19) และ Lng (98-105) ของไทย
                gps_match = re.search(r'(1[2-9]\.\d+)\s*[\,\/\s]\s*(9[8-9]\.\d+|10[0-5]\.\d+)', line_str)
                time_match = re.search(r'(\d{1,2}:\d{2})', line_str)

                if gps_match:
                    lat = float(gps_match.group(1))
                    lng = float(gps_match.group(2))
                    delivery_time = time_match.group(1) if time_match else "00:00"

                    cust_id_match = re.search(r'^([\d/]+)\s+', line_str.strip())
                    cust_id = cust_id_match.group(1) if cust_id_match else "N/A"

                    status = "จัดส่งตรงเวลา"
                    if "ไม่ตรงเวลา" in line_str:
                        status = "จัดส่งไม่ตรงเวลา"
                    elif "สมาชิกใหม่" in line_str:
                        status = "สมาชิกใหม่"
                    elif "รอบเสริม" in line_str:
                        status = "รอบเสริม"
                    elif "ย้ายรอบ" in line_str:
                        status = "ย้ายรอบ"

                    # ดึงจำนวนยอดส่ง
                    tokens = line_str.split()
                    qty_sent = 1
                    cust_name = "ลูกค้าทั่วไป"

                    for idx, t in enumerate(tokens):
                        if ("13." in t or "14." in t or "12." in t) and "." in t:
                            if idx >= 2 and tokens[idx-2].isdigit():
                                qty_sent = int(tokens[idx-2])
                            
                            if len(tokens) > 2:
                                name_tokens = [nt for nt in tokens[1:idx-2] if not nt.isdigit()]
                                if name_tokens:
                                    cust_name = " ".join(name_tokens)
                            break

                    records.append({
                        "cust_id": cust_id,
                        "cust_name": cust_name,
                        "lat": lat,
                        "lng": lng,
                        "time": delivery_time,
                        "qty": qty_sent,
                        "status": status
                    })

    df = pd.DataFrame(records)

    if not df.empty:
        # ลบรายการพิกัดซ้ำ
        df = df.drop_duplicates(subset=['time', 'lat', 'lng']).sort_values(by="time").reset_index(drop=True)

        trips = []
        acc_qty_list = []
        current_trip = 1
        current_trip_acc = 0
        total_acc = 0

        max_trip_qty = dw_net.get(current_trip, 80)

        for idx, row in df.iterrows():
            qty = row['qty']
            if current_trip_acc + qty > max_trip_qty and current_trip_acc > 0:
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

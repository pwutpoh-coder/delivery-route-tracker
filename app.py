import io
import math
import time
import numpy as np
import pandas as pd
import polyline
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

# ----------------------------------------------------
# 0. ตั้งค่าหน้าเว็บ (ต้องเป็นคำสั่ง st แรกสุดของไฟล์เสมอ)
# ----------------------------------------------------
st.set_page_config(
    page_title="Sprinkle Delivery Inspector & Route Optimizer",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ----------------------------------------------------
# 1. ฟังก์ชันคำนวณระยะทาง Haversine & OSRM
# ----------------------------------------------------
def haversine(lat1, lon1, lat2, lon2):
  R = 6371.0  # รัศมีโลกหน่วยเป็นกิโลเมตร
  dlat = math.radians(lat2 - lat1)
  dlon = math.radians(lon2 - lon1)
  a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
      math.radians(lat2)
  ) * math.sin(dlon / 2) ** 2
  c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
  return R * c


def get_osrm_route(coords_list):
  """coords_list: [[lon1, lat1], [lon2, lat2], ...]

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
    total_dist += haversine(
        coords_list[i][1],
        coords_list[i][0],
        coords_list[i + 1][1],
        coords_list[i + 1][0],
    )
  total_duration = (total_dist / 30.0) * 60.0
  fallback_geom = [(c[1], c[0]) for c in coords_list]
  return total_dist, total_duration, fallback_geom


# ----------------------------------------------------
# 2. ฟังก์ชันจัดลำดับเส้นทางด้วย Nearest Neighbor (TSP)
# ----------------------------------------------------
def optimize_route_tsp(depot_lat, depot_lon, df_customers):
  unvisited = df_customers.to_dict("records")
  current_lat, current_lon = depot_lat, depot_lon
  ordered_route = []

  while unvisited:
    nearest_idx = 0
    min_dist = float("inf")
    for idx, cust in enumerate(unvisited):
      dist = haversine(current_lat, current_lon, cust["lat"], cust["lon"])
      if dist < min_dist:
        min_dist = dist
        nearest_idx = idx

    next_cust = unvisited.pop(nearest_idx)
    ordered_route.append(next_cust)
    current_lat, current_lon = next_cust["lat"], next_cust["lon"]

  return ordered_route


# สีสำหรับแต่ละรอบการจัดส่ง (Trip Colors)
trip_colors = ["blue", "green", "purple", "orange", "darkred", "cadetblue"]

# ----------------------------------------------------
# 3. ส่วนติดต่อผู้ใช้ (UI Sidebar & Main)
# ----------------------------------------------------
st.title("🚛 ระบบวิเคราะห์และติดตามเส้นทางส่งสินค้า Sprinkle")
st.markdown("---")

st.sidebar.header("⚙️ 1. ตั้งค่าคลังสินค้า (Depot)")

depot_options = {
    "-- กรุณาเลือกสาขาต้นทาง --": {"lat": None, "lon": None},
    "สาขาบางพลี": {"lat": 13.593901, "lon": 100.80256},
    "สาขาสำโรง": {"lat": 13.660759, "lon": 100.593191},
    "สาขากิ่งแก้ว": {"lat": 13.614988, "lon": 100.700414},
    "สาขาประเวศ": {"lat": 13.711951, "lon": 100.689231},
    "สาขาวังน้อย": {"lat": 14.270937, "lon": 100.756769},
    "สาขาดอนเมือง": {"lat": 13.949959, "lon": 100.612249},
    "สาขาปทุมธานี": {"lat": 14.03736, "lon": 100.606717},
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
    "กำหนดเอง (Custom)": {"lat": 13.7563, "lon": 100.5018},
}

selected_depot = st.sidebar.selectbox(
    "เลือกคลังสินค้าต้นทาง", list(depot_options.keys()), index=0
)

depot_lat, depot_lon = None, None
if selected_depot != "-- กรุณาเลือกสาขาต้นทาง --":
  if selected_depot == "กำหนดเอง (Custom)":
    depot_lat = st.sidebar.number_input(
        "ละติจูดคลัง (Latitude)", value=13.7563, format="%.6f"
    )
    depot_lon = st.sidebar.number_input(
        "ลองจิจูดคลัง (Longitude)", value=100.5018, format="%.6f"
    )
  else:
    depot_lat = depot_options[selected_depot]["lat"]
    depot_lon = depot_options[selected_depot]["lon"]

st.sidebar.markdown("---")
st.sidebar.header("📁 2. นำเข้าข้อมูลการจัดส่งและเที่ยววิ่ง")

import_type_part1 = st.sidebar.radio(
    "เลือกวิธีระบุข้อมูลยอดเบิก/คืน",
    [
        "1. ระบุยอดเบิก ยอดคืนเอง (แยกตามเที่ยว)",
        "2. ข้อมูลจากไฟล์ 'รายงานใบเบิกใบคืนประจำวัน'",
    ],
)

trip_data_records = []
total_target_qty = 0

if import_type_part1 == "1. ระบุยอดเบิก ยอดคืนเอง (แยกตามเที่ยว)":
  num_trips = st.sidebar.number_input(
      "จำนวนเที่ยววิ่งในวันนี้", min_value=1, max_value=6, value=1, step=1
  )
  for t in range(int(num_trips)):
    st.sidebar.markdown(f"**--- เที่ยวที่ {t+1} ---**")
    issue_qty = st.sidebar.number_input(
        f"ยอดเบิก เที่ยวที่ {t+1} (ถัง)", min_value=0, value=0, key=f"issue_{t}"
    )
    return_qty = st.sidebar.number_input(
        f"ยอดคืน เที่ยวที่ {t+1} (ถัง)", min_value=0, value=0, key=f"return_{t}"
    )
    net_delivered = max(0, issue_qty - return_qty)
    if issue_qty > 0 or return_qty > 0:
      trip_data_records.append({
          "trip": t + 1,
          "issue": issue_qty,
          "return": return_qty,
          "net": net_delivered,
      })
      total_target_qty += net_delivered
else:
  file_dwt = st.sidebar.file_uploader(
      "อัปโหลดไฟล์ .xls (รายงานใบเบิกใบคืนประจำวัน)",
      type=["xls", "xlsx"],
      key="file_dwt",
  )
  if file_dwt is not None:
    try:
      df_dwt_raw = pd.read_excel(file_dwt, header=None)
      sub_dwt = df_dwt_raw.iloc[4:].copy()
      sub_dwt = sub_dwt[
          sub_dwt.iloc[:, 2].notna() & (sub_dwt.iloc[:, 2] != "รวม")
      ]
      bev_col = pd.to_numeric(sub_dwt.iloc[:, 3], errors="coerce").fillna(0)
      total_target_qty = int(bev_col.sum())
      if total_target_qty > 0:
        trip_data_records.append({
            "trip": 1,
            "issue": total_target_qty,
            "return": 0,
            "net": total_target_qty,
        })
      st.sidebar.success(f"อ่านยอดเบิกจากไฟล์สำเร็จ: {total_target_qty} หน่วย")
    except Exception as e:
      st.sidebar.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์เบิก: {e}")

st.sidebar.markdown("")
st.sidebar.subheader("ส่วนที่ 2: รายละเอียดรายสมาชิก")
file_summary = st.sidebar.file_uploader(
    "อัปโหลดไฟล์ .xls (รายงานสรุปการจัดส่งประจำวัน)",
    type=["xls", "xlsx"],
    key="file_sum",
)

st.sidebar.markdown("---")
st.sidebar.header("🗺️ 3. ตั้งค่าการแสดงแผนที่")
map_view_mode = st.sidebar.radio(
    "รูปแบบการแสดงพิกัดบนแผนที่",
    [
        "แสดงทีละพิกัดตามลำดับเส้นทางที่วิ่งผ่าน (เริ่มเมื่อกด Play)",
        "แสดงพิกัดทั้งหมดไว้เลย (ทุกจุด)",
    ],
)

# ----------------------------------------------------
# 4. ประมวลผลข้อมูลไฟล์สรุปการจัดส่งรายสมาชิก
# ----------------------------------------------------
df_customers = pd.DataFrame()

if file_summary is not None:
  try:
    df_sum_raw = pd.read_excel(file_summary, header=None)
    data_rows = []
    for idx in range(4, len(df_sum_raw)):
      row = df_sum_raw.iloc[idx]
      cust_id = row[0]
      if (
          pd.isna(cust_id)
          or str(cust_id).strip() == ""
          or str(cust_id).strip() == "รวม"
      ):
        break

      cust_name = row[1]
      target_qty = pd.to_numeric(row[2], errors="coerce") or 0
      gps_str = str(row[3]) if not pd.isna(row[3]) else ""
      diff_gps = pd.to_numeric(row[4], errors="coerce") or 0.0
      time_str = str(row[5]) if not pd.isna(row[5]) else "00:00:00"
      status = str(row[6]) if not pd.isna(row[6]) else "ปกติ"
      reason = str(row[7]) if not pd.isna(row[7]) else "-"
      orig_seq = pd.to_numeric(row[8], errors="coerce") or (idx - 3)

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
          "orig_seq": int(orig_seq),
      })

    df_customers = pd.DataFrame(data_rows)
    if not df_customers.empty:
      df_customers["time_parsed"] = pd.to_datetime(
          df_customers["time_str"], format="%H:%M:%S", errors="coerce"
      )
      df_customers["is_zero_time"] = (
          df_customers["time_str"].isin(["00:00:00", "0:00", "00:00"])
          & (df_customers["target_qty"] == 0)
      )

      df_customers = df_customers.sort_values(
          by=["is_zero_time", "time_parsed", "orig_seq"],
          ascending=[True, True, True],
      ).reset_index(drop=True)

      df_customers["seq_time"] = range(1, len(df_customers) + 1)
      df_customers["cum_qty"] = df_customers["target_qty"].cumsum()

      if trip_data_records:
        thresholds = []
        curr_sum = 0
        for tr in trip_data_records:
          curr_sum += tr["net"]
          thresholds.append((tr["trip"], curr_sum))

        def assign_trip(cum_q):
          for trip_num, limit in thresholds:
            if cum_q <= limit:
              return trip_num
          return thresholds[-1][0] if thresholds else 1

        df_customers["trip"] = df_customers["cum_qty"].apply(assign_trip)
      else:
        df_customers["trip"] = np.clip(
            (df_customers.index // 10) + 1, 1, len(trip_colors)
        )

  except Exception as e:
    st.error(f"เกิดข้อผิดพลาดในการประมวลผลไฟล์สรุปการจัดส่ง: {e}")

# ----------------------------------------------------
# 5. การเตรียมเส้นทางและสถานะล่วงหน้า (Pre-computation)
# ----------------------------------------------------
if "playback_step" not in st.session_state:
  st.session_state.playback_step = 1
if "is_playing" not in st.session_state:
  st.session_state.is_playing = False
if "slider_step" not in st.session_state:
  st.session_state.slider_step = 1

valid_actual_custs = pd.DataFrame()
act_dist, act_dur, act_geom = 0, 0, []
is_system_ready = False

if not df_customers.empty and depot_lat is not None and depot_lon is not None:
  valid_actual_custs = df_customers.dropna(subset=["lat", "lon"]).copy()
  if not valid_actual_custs.empty:
    actual_coords = [[depot_lon, depot_lat]]
    for _, row in valid_actual_custs.iterrows():
      actual_coords.append([row["lon"], row["lat"]])
    act_dist, act_dur, act_geom = get_osrm_route(actual_coords)
    if len(act_geom) > 0:
      is_system_ready = True

# ----------------------------------------------------
# 6. การแสดงผลหลัก (Tabs)
# ----------------------------------------------------
if selected_depot == "-- กรุณาเลือกสาขาต้นทาง --":
  st.warning(
      "⚠️ กรุณาเลือก 'สาขาคลังสินค้าต้นทาง' ที่แถบเมนูด้านซ้าย"
      " เพื่อเริ่มต้นใช้งานแผนที่และระบบคำนวณ"
  )

tab1, tab2 = st.tabs([
    "🗺️ 1. แผนผังเส้นทางตามลำดับเวลาจริง (Actual Route)",
    "⚡ 2. เส้นทางที่เหมาะสมที่สุด (Optimized Route)",
])

with tab1:
  st.subheader(
      "รายงานการจัดส่งตามลำดับเวลาจริง (เรียงลำดับจากเวลาน้อยไปหามากจากคอลัมน์"
      " F)"
  )

  if not df_customers.empty:
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
      filter_status = st.multiselect(
          "กรองตามสถานะจัดส่ง",
          options=(
              df_customers["status"].unique()
              if not df_customers.empty
              else []
          ),
          default=[],
      )
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
      filtered_df = filtered_df[
          filtered_df["cust_id"].str.contains(search_query, na=False)
          | filtered_df["cust_name"].str.contains(search_query, na=False)
      ]

    m1_col, m2_col, m3_col = st.columns(3)
    m1_col.metric(
        "ยอดส่งสุทธิรวมทั้งวัน", f"{df_customers['target_qty'].sum():,.0f} ถัง"
    )
    m2_col.metric("ระยะทางรวมทั้งวัน (Actual)", f"{act_dist:.2f} กม.")
    m3_col.metric("เวลาเดินทางรวมทั้งวัน", f"{act_dur:.1f} นาที")

    # ----------------------------------------------------
    # ส่วนสรุปการจัดส่งในแต่ละรอบ และรวมทั้งวัน
    # ----------------------------------------------------
    st.markdown("---")
    st.markdown("### 📊 สรุปผลการจัดส่ง (แยกรายรอบ และรวมทั้งวัน)")

    trip_summary_list = []
    unique_trips = sorted(df_customers["trip"].unique())

    for t_num in unique_trips:
      t_data = df_customers[df_customers["trip"] == t_num]
      t_cust_count = len(t_data)
      t_total_qty = t_data["target_qty"].sum()

      t_coords = [[depot_lon, depot_lat]] if depot_lat is not None else []
      for _, r in t_data.dropna(subset=["lat", "lon"]).iterrows():
        t_coords.append([r["lon"], r["lat"]])
      if depot_lat is not None and len(t_coords) > 1:
        t_coords.append([depot_lon, depot_lat])

      t_dist, t_dur, _ = get_osrm_route(t_coords)

      trip_summary_list.append({
          "เที่ยววิ่งที่": f"รอบที่ {t_num}",
          "จำนวนลูกค้า": t_cust_count,
          "ยอดส่งรวม (ถัง)": int(t_total_qty),
          "ระยะทาง (กม.)": round(t_dist, 2),
          "เวลาโดยประมาณ (นาที)": round(t_dur, 1),
      })

    df_trip_summary = pd.DataFrame(trip_summary_list)
    st.dataframe(df_trip_summary, use_container_width=True)

    col_sum1, col_sum2, col_sum3, col_sum4 = st.columns(4)
    col_sum1.metric("จำนวนรอบวิ่งทั้งหมด", f"{len(unique_trips)} รอบ")
    col_sum2.metric("จำนวนลูกค้ารวมทั้งวัน", f"{len(df_customers)} ราย")
    col_sum3.metric(
        "ยอดจัดส่งรวมทั้งวัน", f"{df_customers['target_qty'].sum():,.0f} ถัง"
    )
    col_sum4.metric("ระยะทางสะสมรวมทั้งวัน", f"{act_dist:.2f} กม.")

    # ----------------------------------------------------
    # ส่วนควบคุมการเล่นแผนที่ (Playback Controls & Speed)
    # ----------------------------------------------------
    st.markdown("---")
    st.markdown("#### ⏱️ แถบควบคุมการเล่นเส้นทางบนแผนที่")

    st.markdown("##### 🟢 สถานะการเตรียมพร้อมของระบบ")
    if is_system_ready:
      st.success(
          "✅ **ระบบโหลดข้อมูลและจำลองเส้นทางเรียบร้อยพร้อมเล่นแล้ว!**"
          " (สามารถกดปุ่ม Play ด้านล่างได้ทันที)"
      )
    else:
      st.warning(
          "⏳ **กำลังโหลดหรือข้อมูลยังไม่ครบถ้วน...**"
          " กรุณาเลือกคลังสินค้าและอัปโหลดไฟล์ให้เรียบร้อย"
      )

    max_steps = max(1, len(valid_actual_custs))

    speed_option = st.selectbox(
        "⚡ เลือกระดับความเร็วในการเล่นจำลองเส้นทาง",
        ["ช้ามาก (1.5 วินาที/จุด)", "ปกติ (0.8 วินาที/จุด)", "เร็ว (0.3 วินาที/จุด)"],
        index=1,
    )
    if "ช้ามาก" in speed_option:
      sleep_time = 1.5
    elif "เร็ว" in speed_option:
      sleep_time = 0.3
    else:
      sleep_time = 0.8

    c_btn1, c_btn2, c_btn3, c_btn4 = st.columns(4)
    if c_btn1.button("▶️ เล่น (Play)", disabled=not is_system_ready):
      st.session_state.is_playing = True
      if st.session_state.playback_step >= max_steps:
        st.session_state.playback_step = 1
      st.session_state.slider_step = st.session_state.playback_step
      st.rerun()

    if c_btn2.button("⏸️ พัก (Pause)"):
      st.session_state.is_playing = False
      st.rerun()

    if c_btn3.button("⏪ เล่นซ้ำ (Replay)", disabled=not is_system_ready):
      st.session_state.playback_step = 1
      st.session_state.slider_step = 1
      st.session_state.is_playing = True
      st.rerun()

    if c_btn4.button("🔄 รีเซ็ต (Reset)"):
      st.session_state.playback_step = 1
      st.session_state.slider_step = 1
      st.session_state.is_playing = False
      st.rerun()

    # ซิงค์ค่าระหว่าง playback_step และ slider_step ให้ตรงกันก่อนสร้าง widget เพื่อป้องกัน state conflict
    if not st.session_state.is_playing:
      st.session_state.slider_step = int(st.session_state.playback_step)


    def on_slider_change():
      st.session_state.playback_step = st.session_state.slider_step
      st.session_state.is_playing = (
          False  # หยุดเล่นอัตโนมัติหากผู้ใช้เลื่อนเอง
      )


    # ใช้ slider ร่วมกับ key เพื่อจัดการสเต็ปได้อย่างแม่นยำ
    st.slider(
        "เลือกลำดับจุดส่งเพื่ออัปเดตเส้นทางทันที",
        1,
        max_steps,
        key="slider_step",
        on_change=on_slider_change,
    )

    # อัปเดตสเต็ปอัตโนมัติเมื่ออยู่ในโหมด Play
    if st.session_state.is_playing:
      if st.session_state.playback_step < max_steps:
        time.sleep(sleep_time)
        st.session_state.playback_step += 1
        st.session_state.slider_step = st.session_state.playback_step
        st.rerun()
      else:
        st.session_state.is_playing = False
  else:
    st.info(
        "💡 กรุณาอัปโหลดไฟล์ **'รายงานสรุปการจัดส่งประจำวัน.xls'**"
        " เพื่อแสดงผลลัพธ์การคำนวณและข้อมูลสถิติการจัดส่ง"
    )

  # ตั้งค่าพิกัดกลางแผนที่ให้ขยับตามจุดล่าสุดอัตโนมัติ
  map_center = (
      [depot_lat, depot_lon] if depot_lat is not None else [13.7563, 100.5018]
  )
  if (
      not df_customers.empty
      and not valid_actual_custs.empty
      and map_view_mode != "แสดงพิกัดทั้งหมดไว้เลย (ทุกจุด)"
  ):
    current_idx = min(
        max(0, st.session_state.playback_step - 1),
        len(valid_actual_custs) - 1,
    )
    latest_row = valid_actual_custs.iloc[current_idx]
    if pd.notna(latest_row["lat"]) and pd.notna(latest_row["lon"]):
      map_center = [latest_row["lat"], latest_row["lon"]]

  m = folium.Map(
      location=map_center, zoom_start=14 if depot_lat is not None else 10
  )

  if depot_lat is not None and depot_lon is not None:
    folium.Marker(
        [depot_lat, depot_lon],
        popup=f"คลังสินค้า: {selected_depot}",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m)

  if not df_customers.empty and not valid_actual_custs.empty:
    current_display_limit = st.session_state.playback_step

    if map_view_mode == "แสดงพิกัดทั้งหมดไว้เลย (ทุกจุด)":
      current_display_limit = len(valid_actual_custs)
      if st.session_state.is_playing or st.session_state.playback_step > 1:
        if len(act_geom) > 1:
          folium.PolyLine(
              act_geom, color="blue", weight=4, opacity=0.7
          ).add_to(m)
    else:
      if (
          current_display_limit > 0
          and depot_lat is not None
          and depot_lon is not None
      ):
        sub_coords = [[depot_lon, depot_lat]]
        current_active_trip = 1

        for idx_sub, (_, row_sub) in enumerate(valid_actual_custs.iterrows()):
          if idx_sub + 1 <= current_display_limit:
            trip_num = int(row_sub.get("trip", 1))
            if trip_num != current_active_trip:
              sub_coords.append([depot_lon, depot_lat])
              sub_coords.append([depot_lon, depot_lat])
              current_active_trip = trip_num

            sub_coords.append([row_sub["lon"], row_sub["lat"]])

        if len(sub_coords) >= 2:
          _, _, sub_geom = get_osrm_route(sub_coords)
          folium.PolyLine(
              sub_geom, color="blue", weight=4, opacity=0.7
          ).add_to(m)

    for idx, (i, row) in enumerate(valid_actual_custs.iterrows()):
      if (
          map_view_mode == "แสดงพิกัดทั้งหมดไว้เลย (ทุกจุด)"
          or idx + 1 <= current_display_limit
      ):
        is_latest = (idx + 1 == current_display_limit) and (
            map_view_mode != "แสดงพิกัดทั้งหมดไว้เลย (ทุกจุด)"
        )
        t_idx = int(row.get("trip", 1)) - 1
        color_name = trip_colors[t_idx % len(trip_colors)]
        seq_num = row.get("seq_time", idx + 1)

        popup_text = f"""
                <b>รหัสลูกค้า:</b> {row['cust_id']}<br>
                <b>ชื่อลูกค้า:</b> {row['cust_name']}<br>
                <b>ยอดจัดส่ง:</b> {row['target_qty']} ถัง<br>
                <b>พิกัด GPS:</b> {row['gps_str']}<br>
                <b>เวลาการจัดส่ง:</b> {row['time_str']}<br>
                <b>รอบที่:</b> {row.get('trip', 1)} (ลำดับที่ {seq_num})
                """

        if is_latest:
          div_icon = folium.DivIcon(
              html=f'<div style="background-color: {color_name}; color: white; border-radius: 50%; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 12px; border: 3px solid gold; box-shadow: 0 0 12px gold;">{seq_num}</div>'
          )
        else:
          div_icon = folium.DivIcon(
              html=f'<div style="background-color: {color_name}; color: white; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 11px; border: 2px solid white;">{seq_num}</div>'
          )

        folium.Marker(
            [row["lat"], row["lon"]],
            popup=popup_text,
            tooltip=f"{row['cust_id']} - {row['cust_name']} (ยอด: {row['target_qty']} ถัง)",
            icon=div_icon,
        ).add_to(m)

  st_folium(m, width="100%", height=450, key="map_tab1")

  if not df_customers.empty:
    st.markdown("### ตารางรายละเอียดลูกค้า (Actual เรียงตามเวลา)")
    st.dataframe(filtered_df, use_container_width=True)

with tab2:
  st.subheader(
      "การจัดลำดับเส้นทางใหม่ให้มีประสิทธิภาพสูงสุด (TSP Optimized Route)"
  )
  st.markdown(
      "ระบบจะทำการคำนวณเรียงลำดับจุดส่งใหม่โดยอ้างอิงพิกัดระยะทางที่ใกล้ที่สุด"
      " เพื่อประหยัดระยะทางและน้ำมันสูงสุด"
  )

  if not df_customers.empty:
    valid_opt_custs = df_customers.dropna(subset=["lat", "lon"]).copy()

    if (
        not valid_opt_custs.empty
        and depot_lat is not None
        and depot_lon is not None
    ):
      optimized_list = optimize_route_tsp(depot_lat, depot_lon, valid_opt_custs)
      df_optimized = pd.DataFrame(optimized_list)

      opt_coords = [[depot_lon, depot_lat]]
      for _, row in df_optimized.iterrows():
        opt_coords.append([row["lon"], row["lat"]])

      opt_dist, opt_dur, opt_geom = get_osrm_route(opt_coords)

      om1, om2, om3 = st.columns(3)
      act_coords_temp = [[depot_lon, depot_lat]] + [
          [r["lon"], r["lat"]] for _, r in valid_opt_custs.iterrows()
      ]
      act_d_tmp, _, _ = get_osrm_route(act_coords_temp)

      om1.metric(
          "ระยะทางหลังปรับปรุง (Optimized)",
          f"{opt_dist:.2f} กม.",
          delta=f"{opt_dist - act_d_tmp:.2f} กม.",
          delta_color="inverse",
      )
      om2.metric(
          "เวลาเดินทางหลังปรับปรุง",
          f"{opt_dur:.1f} นาที",
          delta_color="inverse",
      )
      saved_km = max(0, act_d_tmp - opt_dist)
      om3.metric("ระยะทางที่ประหยัดได้", f"{saved_km:.2f} กม.")

      m_opt = folium.Map(location=[depot_lat, depot_lon], zoom_start=12)
      folium.Marker(
          [depot_lat, depot_lon],
          popup=f"คลังสินค้า: {selected_depot}",
          icon=folium.Icon(color="red", icon="home"),
      ).add_to(m_opt)

      max_opt_steps = max(1, len(df_optimized))
      selected_opt_step = st.slider(
          "เลือกดูลำดับจุดส่ง Optimized บนแผนที่",
          0,
          max_opt_steps,
          0,
          key="opt_slider",
      )

      opt_sub_coords = [[depot_lon, depot_lat]]
      for step_idx, row in df_optimized.iterrows():
        if step_idx + 1 <= selected_opt_step:
          is_latest_opt = step_idx + 1 == selected_opt_step
          opt_seq_num = step_idx + 1
          opt_sub_coords.append([row["lon"], row["lat"]])

          popup_opt_text = f"""
                    <b>รหัสลูกค้า:</b> {row['cust_id']}<br>
                    <b>ชื่อลูกค้า:</b> {row['cust_name']}<br>
                    <b>ยอดจัดส่ง:</b> {row['target_qty']} ถัง<br>
                    <b>พิกัด GPS:</b> {row['gps_str']}<br>
                    <b>เวลาการจัดส่ง:</b> {row['time_str']}
                    """

          if is_latest_opt:
            div_icon_opt = folium.DivIcon(
                html=f'<div style="background-color: green; color: white; border-radius: 50%; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 12px; border: 3px solid gold; box-shadow: 0 0 12px gold;">{opt_seq_num}</div>'
            )
          else:
            div_icon_opt = folium.DivIcon(
                html=f'<div style="background-color: green; color: white; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 11px; border: 2px solid white;">{opt_seq_num}</div>'
            )

          folium.Marker(
              [row["lat"], row["lon"]],
              popup=popup_opt_text,
              tooltip=f"{row['cust_id']} - {row['cust_name']} (ยอด: {row['target_qty']} ถัง)",
              icon=div_icon_opt,
          ).add_to(m_opt)

      if selected_opt_step > 0 and len(opt_sub_coords) >= 2:
        _, _, opt_sub_geom = get_osrm_route(opt_sub_coords)
        folium.PolyLine(
            opt_sub_geom, color="green", weight=4, opacity=0.8
        ).add_to(m_opt)

      st_folium(m_opt, width="100%", height=450, key="map_tab2_optimized")

      st.markdown("### ลำดับการจัดส่งใหม่ที่แนะนำ (Optimized Sequence)")
      df_optimized["optimized_seq"] = range(1, len(df_optimized) + 1)
      display_cols = [
          "optimized_seq",
          "cust_id",
          "cust_name",
          "target_qty",
          "time_str",
          "status",
          "trip",
      ]
      st.dataframe(
          df_optimized[
              [c for c in display_cols if c in df_optimized.columns]
          ],
          use_container_width=True,
      )
    else:
      st.warning(
          "กรุณาเลือกสาขาคลังสินค้าต้นทางและตรวจสอบข้อมูลพิกัด GPS ให้ครบถ้วน"
      )
      m_opt_empty = folium.Map(location=[13.7563, 100.5018], zoom_start=10)
      st_folium(m_opt_empty, width="100%", height=450, key="map_tab2_empty")
  else:
    m_opt_empty = folium.Map(location=[13.7563, 100.5018], zoom_start=10)
    st_folium(m_opt_empty, width="100%", height=450, key="map_tab2_empty")
    st.info(
        "💡 กรุณานำเข้าข้อมูลไฟล์สรุปการจัดส่งเพื่อคำนวณเส้นทางที่มีประสิทธิภาพที่สุด"
    )

st.markdown("---")
st.caption(
    "Sprinkle Delivery Inspector System - พัฒนาด้วย Streamlit และ OSRM Routing"
)

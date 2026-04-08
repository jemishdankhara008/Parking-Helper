import cv2
import numpy as np
from ultralytics import YOLO
import yt_dlp
import pandas as pd
from datetime import datetime
from multiprocessing import Process, Lock
import os
import time
import json
from pathlib import Path
import torch
from shapely.geometry import Polygon, box # ⚡ NEW: Advanced Geometry Math

VEHICLE_CLASSES = {2, 3, 5, 7}
SPOT_OVERLAP_THRESHOLD = 0.25
CAR_OVERLAP_THRESHOLD = 0.40
MIN_DETECTION_CONFIDENCE = 0.15
INFERENCE_IMAGE_SIZE = 1920

def get_youtube_stream(url):
    """Helper to get raw stream URL from YouTube"""
    try:
        ydl_opts = {'format': 'best[height<=720]', 'quiet': True, 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info['url']
    except Exception as e:
        print(f"YouTube Error: {e}")
        return None

def apply_clahe_night_vision(frame):
    """⚡ NEW: CLAHE Filter for extreme clarity in night/snow conditions"""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    limg = cv2.merge((cl, a, b))
    return cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

def load_detection_model(root_dir, parking_lot_id):
    """Prefer TensorRT if present, otherwise prefer local models that detect vehicles correctly."""
    engine_path = os.path.join(root_dir, 'src', 'models', 'yolo26n.engine')
    pt_candidates = [
        os.path.join(root_dir, 'yolov8n.pt'),
        os.path.join(root_dir, 'yolov8s.pt'),
        os.path.join(root_dir, 'src', 'models', 'yolo26n.pt'),
        os.path.join(root_dir, 'main', 'src', 'models', 'yolo26n.pt'),
    ]
    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    if os.path.exists(engine_path):
        print(f"[TensorRT] Engine found. Booting {parking_lot_id} in hyper-speed...")
        return YOLO(engine_path, task='detect'), device

    model_path = next((path for path in pt_candidates if os.path.exists(path)), None)
    if model_path is None:
        raise FileNotFoundError("Missing detector weights. Expected yolov8*.pt or src/models/yolo26n.pt.")

    print(f"[PyTorch] Booting {parking_lot_id} with {os.path.basename(model_path)} on {device.upper()}...")
    model = YOLO(model_path)
    model.to(device)
    return model, device

def is_detection_inside_spot(car_box, car_area, spot_poly, spot_pts, center_point, bottom_center_point):
    """Use polygon IoU plus point-based fallbacks to recover practical parked-car matching."""
    if spot_poly is None or not car_box.intersects(spot_poly):
        return (
            cv2.pointPolygonTest(spot_pts, center_point, False) >= 0
            or cv2.pointPolygonTest(spot_pts, bottom_center_point, False) >= 0
        )

    intersection_area = car_box.intersection(spot_poly).area
    if intersection_area <= 0 or car_area <= 0 or spot_poly.area <= 0:
        return False

    spot_overlap = intersection_area / spot_poly.area
    car_overlap = intersection_area / car_area

    return (
        spot_overlap >= SPOT_OVERLAP_THRESHOLD
        or car_overlap >= CAR_OVERLAP_THRESHOLD
        or cv2.pointPolygonTest(spot_pts, center_point, False) >= 0
        or cv2.pointPolygonTest(spot_pts, bottom_center_point, False) >= 0
    )

def process_parking_lot(parking_lot_id, video_source_path, roi_csv_path, output_csv_path, output_json_path, lock, root_dir, is_primary=False):
    
    model, device = load_detection_model(root_dir, parking_lot_id)

    # 2. Setup Reporting
    report_dir = os.path.join(root_dir, 'data', 'reporting')
    os.makedirs(report_dir, exist_ok=True)
    history_csv_path = os.path.join(report_dir, f'{parking_lot_id}_history.csv')

    # 3. Load ROI Coordinates & Build Shapely Polygons
    if not os.path.exists(roi_csv_path):
        print(f"Error: ROI file not found at {roi_csv_path}")
        return
    data = pd.read_csv(roi_csv_path)

    spots = []
    shapely_polys = [] # ⚡ NEW: Mathematical representations of spots
    
    # ⏳ NEW: Advanced State Machine for Time-Delay Locking
    spot_states = [] 
    LOCK_THRESHOLD = 5  # Frames a car must be continuously present
    FREE_THRESHOLD = 5  # Frames a car must be continuously absent

    for i in range(len(data)):
        coords = [
            (data['Point1_X'].iloc[i], data['Point1_Y'].iloc[i]),
            (data['Point2_X'].iloc[i], data['Point2_Y'].iloc[i]),
            (data['Point3_X'].iloc[i], data['Point3_Y'].iloc[i]),
            (data['Point4_X'].iloc[i], data['Point4_Y'].iloc[i])
        ]
        pts = np.array(coords, np.int32)
        spots.append(pts)
        
        # Create mathematically accurate polygon
        if len(np.unique(pts, axis=0)) >= 3: # Ensure valid shape
            poly = Polygon(coords)
            if not poly.is_valid:
                poly = poly.buffer(0)
            shapely_polys.append(poly)
        else:
            shapely_polys.append(None)
            
        spot_states.append({
            'status': 'empty',
            'occupied_hits': 0,
            'empty_hits': 0
        })

    # 4. Handle Video Source
    final_video_path = video_source_path
    if "youtube.com" in video_source_path or "youtu.be" in video_source_path:
        final_video_path = get_youtube_stream(video_source_path)
    elif not video_source_path.startswith(('http', 'https')):
        final_video_path = os.path.join(root_dir, video_source_path)

    cap = cv2.VideoCapture(final_video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video: {final_video_path}")
        return

    frame_save_path = os.path.join(root_dir, 'data', 'latest_frame.jpg')
    last_log_time = time.time()
    last_10s_print = time.time()  # 👈 YE NAYI LINE ADD KAR
    prev_status = None
    print(f"✅ Enterprise Monitor Active: {parking_lot_id} (CLAHE + Polygon IoU)")

    while True:
        ret, frame = cap.read()
        if not ret:
            if "youtube" not in video_source_path: 
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0) 
                continue
            else:
                break

        # ⚡ NEW: Apply Night-Vision / Snow-Vision processing
        enhanced_frame = apply_clahe_night_vision(frame)

        # Inference on enhanced frame
        results = model.predict(
            enhanced_frame,
            verbose=False,
            conf=MIN_DETECTION_CONFIDENCE,
            imgsz=INFERENCE_IMAGE_SIZE,
            device=device
        )
        detections = results[0].boxes.data
        
        current_frame_hits = [False] * len(spots)

        # 🎯 ADVANCED DETECTION LOGIC (Polygon IoU)
        for det in detections:
            x1, y1, x2, y2, conf, cls = map(float, det[:6])
            if int(cls) not in VEHICLE_CLASSES:
                continue

            car_box = box(x1, y1, x2, y2)
            car_area = car_box.area
            if car_area <= 0:
                continue

            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
            bottom_cy = int(y2)
            is_parked = False

            for i, spot_poly in enumerate(shapely_polys):
                if is_detection_inside_spot(car_box, car_area, spot_poly, spots[i], (cx, cy), (cx, bottom_cy)):
                    current_frame_hits[i] = True
                    is_parked = True

            if is_parked:
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                cv2.circle(frame, (cx, cy), 3, (0, 0, 255), -1)
            else:
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)

        # ⏳ STATE MACHINE PROCESSING
        final_status = []
        for i in range(len(spots)):
            state = spot_states[i]
            
            if current_frame_hits[i]:
                state['occupied_hits'] += 1
                state['empty_hits'] = 0
                if state['occupied_hits'] >= LOCK_THRESHOLD:
                    state['status'] = 'occupied'
            else:
                state['empty_hits'] += 1
                state['occupied_hits'] = 0
                if state['empty_hits'] >= FREE_THRESHOLD:
                    state['status'] = 'empty'
                    
            final_status.append(state['status'])

        # 🔔 STATUS CHANGE LOGIC
        if final_status != prev_status:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            empty_count = final_status.count('empty')
            occupied_count = len(spots) - empty_count
            
            print(f"\n[{timestamp}] {parking_lot_id} Update:")
            print(f"  -> Empty lots: {empty_count}")
            print(f"  -> Occupied lots: {occupied_count}")

            with lock:
                # Update CSV
                try:
                    df = pd.read_csv(output_csv_path)
                    df = df[df['ParkingLotID'] != parking_lot_id]
                except (FileNotFoundError, pd.errors.EmptyDataError):
                    df = pd.DataFrame()

                cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
                new_row = pd.DataFrame([[parking_lot_id, timestamp] + final_status], columns=cols)
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv(output_csv_path, index=False)

                # Update JSON
                try:
                    if os.path.exists(output_json_path):
                        with open(output_json_path, 'r') as f:
                            json_data = json.load(f)
                    else:
                        json_data = {}
                except (json.JSONDecodeError, FileNotFoundError):
                    json_data = {}

                json_data[parking_lot_id] = {
                    "timestamp": timestamp,
                    "total_spots": len(spots),
                    "empty_spots": empty_count,
                    "occupied_spots": occupied_count,
                    "spots": {f"SP{j+1}": stat for j, stat in enumerate(final_status)}
                }

                with open(output_json_path, 'w') as f:
                    json.dump(json_data, f, indent=4)
            
        # if final_status != prev_status:
            prev_status = list(final_status)

        # 📊 DETAILED REPORTING
        current_time = time.time()
        
        # ⏳ NAYA LOGIC: Har 10 second mein console par Update print karega
        if current_time - last_10s_print >= 10.0:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            empty_count = final_status.count('empty')
            occupied_count = len(spots) - empty_count
            print(f"\n[{timestamp}] {parking_lot_id} Update:")
            print(f"  -> Empty lots: {empty_count}")
            print(f"  -> Occupied lots: {occupied_count}")
            last_10s_print = current_time
            
        if current_time - last_log_time >= 1.0:
            ts_sec = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
            new_row = pd.DataFrame([[parking_lot_id, ts_sec] + final_status], columns=cols)
            
            file_exists = os.path.isfile(history_csv_path)
            new_row.to_csv(history_csv_path, mode='a', index=False, header=not file_exists)
            
            last_log_time = current_time

        # 🎨 DRAW PARKING SPOTS (Red = Occupied, Green = Empty, Yellow = Transitioning)
        for i, spot in enumerate(spots):
            # Show a transition color (Yellow) if it's currently verifying a car
            if final_status[i] == 'empty' and spot_states[i]['occupied_hits'] > 0:
                color = (0, 255, 255) # Yellow
            else:
                color = (0, 0, 255) if final_status[i] == 'occupied' else (0, 255, 0)
                
            cv2.polylines(frame, [spot], True, color, 2)
            area_center = np.mean(spot, axis=0).astype(int)
            cv2.putText(frame, f'SP{i+1}', tuple(area_center), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Show the normal frame with drawings to the user (enhanced frame is processed in background)
        if is_primary:
            cv2.imwrite(frame_save_path, frame)

        cv2.imshow(f"Enterprise Monitor: {parking_lot_id}", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()

def cleanup_pid():
    try:
        import sys
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        base = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
    pid_path = os.path.join(base, 'data', 'detector.pid')
    if os.path.exists(pid_path):
        try:
            os.remove(pid_path)
        except Exception:
            pass

def main():
    root_dir = Path(__file__).resolve().parents[1]
    
    config_csv = os.path.join(root_dir, 'data', 'parking_lots.csv')
    output_csv_path = os.path.join(root_dir, 'data', 'parking_status.csv')
    output_json_path = os.path.join(root_dir, 'data', 'parking_status.json')
    
    os.makedirs(os.path.join(root_dir, 'data'), exist_ok=True)
    
    if not os.path.exists(config_csv):
        print(f"Error: Missing config at {config_csv}")
        return

    parking_lots_data = pd.read_csv(config_csv)
    processes = []
    lock = Lock() 

    for i, (_, lot) in enumerate(parking_lots_data.iterrows()):
        roi_filename = os.path.basename(lot['ROI'])
        roi_path = os.path.join(root_dir, 'data', roi_filename)

        p = Process(target=process_parking_lot, args=(
            lot['ParkingLotID'], 
            lot['URL'], 
            roi_path,
            output_csv_path,
            output_json_path,
            lock,
            root_dir,
            (i == 0)
        ))
        p.start()
        processes.append(p)

    for p in processes: p.join()

if __name__ == '__main__':
    import atexit
    atexit.register(cleanup_pid)
    main()

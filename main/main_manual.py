# Older detector implementation kept as a manual/reference version alongside main/main.py.
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

def process_parking_lot(parking_lot_id, video_source_path, roi_csv_path, output_csv_path, output_json_path, lock, root_dir):
    # ⚡ FIX: Moved inside the function so each process gets its own isolated history memory
    stability_history = {}

    # 1. Load Model (Robust pathing)
    model_candidates = [
        os.path.join(root_dir, 'yolov8n.pt'),
        os.path.join(root_dir, 'yolov8s.pt'),
    ]
    model_path = next((path for path in model_candidates if os.path.exists(path)), None)
    if model_path is None:
        raise FileNotFoundError("Missing yolov8n.pt and yolov8s.pt in the project root.")
    model = YOLO(model_path)
    
    # 2. Setup Detailed Reporting (Per-Second History)
    report_dir = os.path.join(root_dir, 'data', 'reporting')
    os.makedirs(report_dir, exist_ok=True)
    history_csv_path = os.path.join(report_dir, f'{parking_lot_id}_history.csv')

    # 3. Load ROI Coordinates
    if not os.path.exists(roi_csv_path):
        print(f"Error: ROI file not found at {roi_csv_path}")
        return
    data = pd.read_csv(roi_csv_path)

    spots = []
    for i in range(len(data)):
        coords = [
            (data['Point1_X'].iloc[i], data['Point1_Y'].iloc[i]),
            (data['Point2_X'].iloc[i], data['Point2_Y'].iloc[i]),
            (data['Point3_X'].iloc[i], data['Point3_Y'].iloc[i]),
            (data['Point4_X'].iloc[i], data['Point4_Y'].iloc[i])
        ]
        spots.append(np.array(coords, np.int32))
        stability_history[i] = []

    # 4. Handle Video Source (YouTube or Local)
    final_video_path = video_source_path
    if "youtube.com" in video_source_path or "youtu.be" in video_source_path:
        final_video_path = get_youtube_stream(video_source_path)
    elif not video_source_path.startswith(('http', 'https')):
        final_video_path = os.path.join(root_dir, video_source_path)

    cap = cv2.VideoCapture(final_video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video: {final_video_path}")
        return

    last_log_time = time.time()
    prev_status = None
    print(f"✅ Monitoring {parking_lot_id} Started (Advanced Visuals & JSON Reporting)...")

    while True:
        ret, frame = cap.read()
        if not ret:
            if "youtube" not in video_source_path: 
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # Loop local video
                continue
            else:
                break

        # Inference
        results = model.predict(frame, verbose=False, conf=0.25)
        detections = results[0].boxes.data
        
        current_frame_occupied = [0] * len(spots)

        # 🎯 DETECTION LOGIC & VISUAL FEATURES
        for det in detections:
            x1, y1, x2, y2, conf, cls = det
            if int(cls) in [2, 3, 5, 7]: # Car, Motorcycle, Bus, Truck
                cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                
                is_parked = False
                for i, spot in enumerate(spots):
                    # Point in Polygon Test
                    if cv2.pointPolygonTest(spot, (cx, cy), False) >= 0:
                        current_frame_occupied[i] = 1
                        is_parked = True
                        break
                
                # DRAW VEHICLE FEATURES
                if is_parked:
                    # Green Box for properly parked cars
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                    cv2.circle(frame, (cx, cy), 3, (0, 0, 255), -1) 
                else:
                    # Red Box for cars driving in the aisle or not in a spot
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)

        # The rolling vote smooths out noisy detections before a spot is marked occupied in the live outputs.
        # Stability Filter (5-frame window)
        final_status = []
        for i in range(len(spots)):
            stability_history[i].append(current_frame_occupied[i])
            if len(stability_history[i]) > 5: stability_history[i].pop(0)
            status = 'occupied' if sum(stability_history[i]) >= 3 else 'empty'
            final_status.append(status)

        # 🔔 STATUS CHANGE LOGIC (Console Print & Live Snapshot Update)
        if final_status != prev_status:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            empty_count = final_status.count('empty')
            occupied_count = len(spots) - empty_count
            
            print(f"\n[{timestamp}] {parking_lot_id} Update:")
            print(f"  -> Empty lots: {empty_count}")
            print(f"  -> Occupied lots: {occupied_count}")

            # Safely update the live snapshot CSV and JSON using the Lock
            with lock:
                # 1. Update CSV
                try:
                    df = pd.read_csv(output_csv_path)
                    df = df[df['ParkingLotID'] != parking_lot_id]
                except (FileNotFoundError, pd.errors.EmptyDataError):
                    df = pd.DataFrame()

                cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
                new_row = pd.DataFrame([[parking_lot_id, timestamp] + final_status], columns=cols)
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv(output_csv_path, index=False)

                # 2. ⚡ NEW: Update JSON File for the Frontend
                try:
                    if os.path.exists(output_json_path):
                        with open(output_json_path, 'r') as f:
                            json_data = json.load(f)
                    else:
                        json_data = {}
                except (json.JSONDecodeError, FileNotFoundError):
                    json_data = {}

                # Build the structured dictionary for this lot
                json_data[parking_lot_id] = {
                    "timestamp": timestamp,
                    "total_spots": len(spots),
                    "empty_spots": empty_count,
                    "occupied_spots": occupied_count,
                    "spots": {f"SP{j+1}": stat for j, stat in enumerate(final_status)}
                }

                # Write it back to the JSON file
                with open(output_json_path, 'w') as f:
                    json.dump(json_data, f, indent=4)
            
            prev_status = list(final_status)

        # 📊 DETAILED REPORTING: Log Every Second
        current_time = time.time()
        if current_time - last_log_time >= 1.0:
            ts_sec = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
            new_row = pd.DataFrame([[parking_lot_id, ts_sec] + final_status], columns=cols)
            
            file_exists = os.path.isfile(history_csv_path)
            new_row.to_csv(history_csv_path, mode='a', index=False, header=not file_exists)
            
            last_log_time = current_time

        # 🎨 DRAW PARKING SPOTS (Red = Occupied, Green = Empty)
        for i, spot in enumerate(spots):
            color = (0, 0, 255) if final_status[i] == 'occupied' else (0, 255, 0)
            cv2.polylines(frame, [spot], True, color, 2)
            area_center = np.mean(spot, axis=0).astype(int)
            cv2.putText(frame, f'SP{i+1}', tuple(area_center), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        cv2.imshow(f"Monitor: {parking_lot_id}", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()

def main():
    root_dir = Path(__file__).resolve().parents[1]
    
    # Paths for configuration and the live snapshot output
    config_csv = os.path.join(root_dir, 'data', 'parking_lots.csv')
    output_csv_path = os.path.join(root_dir, 'data', 'parking_status.csv')
    output_json_path = os.path.join(root_dir, 'data', 'parking_status.json') # ⚡ Added JSON path
    
    os.makedirs(os.path.join(root_dir, 'data'), exist_ok=True)
    
    if not os.path.exists(config_csv):
        print(f"Error: Missing config at {config_csv}")
        return

    parking_lots_data = pd.read_csv(config_csv)
    processes = []
    lock = Lock() 

    for _, lot in parking_lots_data.iterrows():
        roi_filename = os.path.basename(lot['ROI'])
        roi_path = os.path.join(root_dir, 'data', roi_filename)

        p = Process(target=process_parking_lot, args=(
            lot['ParkingLotID'], 
            lot['URL'], 
            roi_path,
            output_csv_path,
            output_json_path, # ⚡ Pass JSON path to process
            lock,
            root_dir
        ))
        p.start()
        processes.append(p)

    for p in processes: p.join()

if __name__ == '__main__':
    main()

# import cv2
# import numpy as np
# from ultralytics import YOLO
# import yt_dlp
# import pandas as pd
# from datetime import datetime
# from multiprocessing import Process, Lock
# import os
# import time
# from pathlib import Path

# # Buffer to store detection history for each spot to prevent status flickering
# STABILITY_HISTORY = {}

# def get_youtube_stream(url):
#     """Helper to get raw stream URL from YouTube"""
#     try:
#         ydl_opts = {'format': 'best[height<=720]', 'quiet': True, 'noplaylist': True}
#         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#             info = ydl.extract_info(url, download=False)
#             return info['url']
#     except Exception as e:
#         print(f"YouTube Error: {e}")
#         return None

# def process_parking_lot(parking_lot_id, video_source_path, roi_csv_path, output_csv_path, lock, root_dir):
#     # 1. Load Model (Robust pathing)
#     model_path = os.path.join(root_dir, 'src', 'models', 'yolov8n.pt')
#     if not os.path.exists(model_path):
#         model_path = os.path.join(root_dir, 'main', 'src', 'models', 'yolov8n.pt')
#     model = YOLO(model_path)
    
#     # 2. Setup Detailed Reporting (Per-Second History)
#     report_dir = os.path.join(root_dir, 'data', 'reporting')
#     os.makedirs(report_dir, exist_ok=True)
#     history_csv_path = os.path.join(report_dir, f'{parking_lot_id}_history.csv')

#     # 3. Load ROI Coordinates
#     if not os.path.exists(roi_csv_path):
#         print(f"Error: ROI file not found at {roi_csv_path}")
#         return
#     data = pd.read_csv(roi_csv_path)

#     spots = []
#     for i in range(len(data)):
#         coords = [
#             (data['Point1_X'].iloc[i], data['Point1_Y'].iloc[i]),
#             (data['Point2_X'].iloc[i], data['Point2_Y'].iloc[i]),
#             (data['Point3_X'].iloc[i], data['Point3_Y'].iloc[i]),
#             (data['Point4_X'].iloc[i], data['Point4_Y'].iloc[i])
#         ]
#         spots.append(np.array(coords, np.int32))
#         STABILITY_HISTORY[i] = []

#     # 4. Handle Video Source (YouTube or Local)
#     final_video_path = video_source_path
#     if "youtube.com" in video_source_path or "youtu.be" in video_source_path:
#         final_video_path = get_youtube_stream(video_source_path)
#     elif not video_source_path.startswith(('http', 'https')):
#         final_video_path = os.path.join(root_dir, video_source_path)

#     cap = cv2.VideoCapture(final_video_path)
#     if not cap.isOpened():
#         print(f"Error: Could not open video: {final_video_path}")
#         return

#     last_log_time = time.time()
#     prev_status = None
#     print(f"✅ Monitoring {parking_lot_id} Started (Advanced Visuals & Reporting)...")

#     while True:
#         ret, frame = cap.read()
#         if not ret:
#             if "youtube" not in video_source_path: 
#                 cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # Loop local video
#                 continue
#             else:
#                 break

#         # Inference
#         results = model.predict(frame, verbose=False, conf=0.25)
#         detections = results[0].boxes.data
        
#         current_frame_occupied = [0] * len(spots)

#         # 🎯 DETECTION LOGIC & VISUAL FEATURES
#         for det in detections:
#             x1, y1, x2, y2, conf, cls = det
#             if int(cls) in [2, 3, 5, 7]: # Car, Motorcycle, Bus, Truck
#                 cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                
#                 is_parked = False
#                 for i, spot in enumerate(spots):
#                     # Point in Polygon Test
#                     if cv2.pointPolygonTest(spot, (cx, cy), False) >= 0:
#                         current_frame_occupied[i] = 1
#                         is_parked = True
#                         break
                
#                 # DRAW VEHICLE FEATURES
#                 if is_parked:
#                     # Green Box for properly parked cars
#                     cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
#                     # Red dot at the center of the car
#                     cv2.circle(frame, (cx, cy), 3, (0, 0, 255), -1) 
#                 else:
#                     # Red Box for cars driving in the aisle or not in a spot
#                     cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)

#         # Stability Filter (5-frame window)
#         final_status = []
#         for i in range(len(spots)):
#             STABILITY_HISTORY[i].append(current_frame_occupied[i])
#             if len(STABILITY_HISTORY[i]) > 5: STABILITY_HISTORY[i].pop(0)
#             status = 'occupied' if sum(STABILITY_HISTORY[i]) >= 3 else 'empty'
#             final_status.append(status)

#         # 🔔 STATUS CHANGE LOGIC (Console Print & Live Snapshot Update)
#         if final_status != prev_status:
#             timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
#             empty_count = final_status.count('empty')
#             occupied_count = len(spots) - empty_count
            
#             # Print cleanly to the console
#             print(f"\n[{timestamp}] {parking_lot_id} Update:")
#             print(f"  -> Empty lots: {empty_count}")
#             print(f"  -> Occupied lots: {occupied_count}")
#             for i, status in enumerate(final_status):
#                 print(f"  {parking_lot_id} SP{i + 1} is {status}")

#             # Safely update the live snapshot CSV using the Lock
#             with lock:
#                 try:
#                     df = pd.read_csv(output_csv_path)
#                     # Remove the old entry for this specific parking lot
#                     df = df[df['ParkingLotID'] != parking_lot_id]
#                 except (FileNotFoundError, pd.errors.EmptyDataError):
#                     df = pd.DataFrame()

#                 cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
#                 new_row = pd.DataFrame([[parking_lot_id, timestamp] + final_status], columns=cols)
#                 df = pd.concat([df, new_row], ignore_index=True)
#                 df.to_csv(output_csv_path, index=False)
            
#             prev_status = list(final_status)

#         # 📊 DETAILED REPORTING: Log Every Second
#         current_time = time.time()
#         if current_time - last_log_time >= 1.0:
#             ts_sec = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
#             cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
#             new_row = pd.DataFrame([[parking_lot_id, ts_sec] + final_status], columns=cols)
            
#             # Append to lot-specific history file without locking
#             file_exists = os.path.isfile(history_csv_path)
#             new_row.to_csv(history_csv_path, mode='a', index=False, header=not file_exists)
            
#             last_log_time = current_time

#         # 🎨 DRAW PARKING SPOTS (Red = Occupied, Green = Empty)
#         for i, spot in enumerate(spots):
#             color = (0, 0, 255) if final_status[i] == 'occupied' else (0, 255, 0)
            
#             # Draw the polygon lines for the spot
#             cv2.polylines(frame, [spot], True, color, 2)
            
#             # Put the "SPX" text at the center of the spot
#             area_center = np.mean(spot, axis=0).astype(int)
#             cv2.putText(frame, f'SP{i+1}', tuple(area_center), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

#         cv2.imshow(f"Monitor: {parking_lot_id}", frame)
#         if cv2.waitKey(1) & 0xFF == ord('q'): break

#     cap.release()
#     cv2.destroyAllWindows()

# def main():
#     root_dir = Path(__file__).resolve().parents[1]
    
#     # Paths for configuration and the live snapshot output
#     config_csv = os.path.join(root_dir, 'data', 'parking_lots.csv')
#     output_csv_path = os.path.join(root_dir, 'data', 'parking_status.csv')
    
#     os.makedirs(os.path.join(root_dir, 'data'), exist_ok=True)
    
#     if not os.path.exists(config_csv):
#         print(f"Error: Missing config at {config_csv}")
#         return

#     parking_lots_data = pd.read_csv(config_csv)
#     processes = []
#     lock = Lock() # Lock is required here for the shared parking_status.csv

#     for _, lot in parking_lots_data.iterrows():
#         # Handle ROI path dynamically
#         roi_filename = os.path.basename(lot['ROI'])
#         roi_path = os.path.join(root_dir, 'data', roi_filename)

#         p = Process(target=process_parking_lot, args=(
#             lot['ParkingLotID'], 
#             lot['URL'], 
#             roi_path,
#             output_csv_path,
#             lock,
#             root_dir
#         ))
#         p.start()
#         processes.append(p)

#     for p in processes: p.join()

# if __name__ == '__main__':
#     main()
# # import cv2
# # import numpy as np
# # from ultralytics import YOLO
# # import yt_dlp
# # import pandas as pd
# # from datetime import datetime
# # from multiprocessing import Process, Lock
# # import os
# # import time
# # from pathlib import Path

# # # Buffer to store detection history for each spot to prevent status flickering
# # STABILITY_HISTORY = {}

# # def get_youtube_stream(url):
# #     """Helper to get raw stream URL from YouTube"""
# #     try:
# #         ydl_opts = {'format': 'best[height<=720]', 'quiet': True, 'noplaylist': True}
# #         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
# #             info = ydl.extract_info(url, download=False)
# #             return info['url']
# #     except Exception as e:
# #         print(f"YouTube Error: {e}")
# #         return None

# # def process_parking_lot(parking_lot_id, video_source_path, roi_csv_path, output_csv_path, lock, root_dir):
# #     # 1. Load Model
# #     model_path = os.path.join(root_dir, 'yolov8s.pt')
# #     model = YOLO(model_path)
    
# #     # 2. Setup Detailed Reporting (Per-Second History)
# #     report_dir = os.path.join(root_dir, 'data', 'reporting')
# #     os.makedirs(report_dir, exist_ok=True)
# #     history_csv_path = os.path.join(report_dir, f'{parking_lot_id}_history.csv')

# #     # 3. Load ROI Coordinates
# #     if not os.path.exists(roi_csv_path):
# #         print(f"Error: ROI file not found at {roi_csv_path}")
# #         return
# #     data = pd.read_csv(roi_csv_path)

# #     spots = []
# #     for i in range(len(data)):
# #         coords = [
# #             (data['Point1_X'].iloc[i], data['Point1_Y'].iloc[i]),
# #             (data['Point2_X'].iloc[i], data['Point2_Y'].iloc[i]),
# #             (data['Point3_X'].iloc[i], data['Point3_Y'].iloc[i]),
# #             (data['Point4_X'].iloc[i], data['Point4_Y'].iloc[i])
# #         ]
# #         spots.append(np.array(coords, np.int32))
# #         STABILITY_HISTORY[i] = []

# #     # 4. Handle Video Source (YouTube or Local)
# #     final_video_path = video_source_path
# #     if "youtube.com" in video_source_path or "youtu.be" in video_source_path:
# #         final_video_path = get_youtube_stream(video_source_path)
# #     elif not video_source_path.startswith(('http', 'https')):
# #         final_video_path = os.path.join(root_dir, video_source_path)

# #     cap = cv2.VideoCapture(final_video_path)
# #     if not cap.isOpened():
# #         print(f"Error: Could not open video: {final_video_path}")
# #         return

# #     last_log_time = time.time()
# #     prev_status = None
# #     print(f"✅ Monitoring {parking_lot_id} Started (Advanced Visuals & Reporting)...")

# #     while True:
# #         ret, frame = cap.read()
# #         if not ret:
# #             if "youtube" not in video_source_path: 
# #                 cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # Loop local video
# #                 continue
# #             else:
# #                 break

# #         # Inference
# #         results = model.predict(frame, verbose=False, conf=0.25)
# #         detections = results[0].boxes.data
        
# #         current_frame_occupied = [0] * len(spots)

# #         # 🎯 DETECTION LOGIC & VISUAL FEATURES
# #         for det in detections:
# #             x1, y1, x2, y2, conf, cls = det
# #             if int(cls) in [2, 3, 5, 7]: # Car, Motorcycle, Bus, Truck
# #                 cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                
# #                 is_parked = False
# #                 for i, spot in enumerate(spots):
# #                     # Point in Polygon Test
# #                     if cv2.pointPolygonTest(spot, (cx, cy), False) >= 0:
# #                         current_frame_occupied[i] = 1
# #                         is_parked = True
# #                         break
                
# #                 # DRAW VEHICLE FEATURES
# #                 if is_parked:
# #                     # Green Box for properly parked cars
# #                     cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
# #                     # Red dot at the center of the car
# #                     cv2.circle(frame, (cx, cy), 3, (0, 0, 255), -1) 
# #                 else:
# #                     # Red Box for cars driving in the aisle or not in a spot
# #                     cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)

# #         # Stability Filter
# #         final_status = []
# #         for i in range(len(spots)):
# #             STABILITY_HISTORY[i].append(current_frame_occupied[i])
# #             if len(STABILITY_HISTORY[i]) > 5: STABILITY_HISTORY[i].pop(0)
# #             status = 'occupied' if sum(STABILITY_HISTORY[i]) >= 3 else 'empty'
# #             final_status.append(status)

# #         # 🔔 STATUS CHANGE LOGIC (Console Print & Live Snapshot Update)
# #         if final_status != prev_status:
# #             timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
# #             empty_count = final_status.count('empty')
# #             occupied_count = len(spots) - empty_count
            
# #             # Print cleanly to the console
# #             print(f"\n[{timestamp}] {parking_lot_id} Update:")
# #             print(f"  -> Empty lots: {empty_count}")
# #             print(f"  -> Occupied lots: {occupied_count}")
# #             for i, status in enumerate(final_status):
# #                 print(f"  {parking_lot_id} SP{i + 1} is {status}")

# #             # Safely update the live snapshot CSV using the Lock
# #             with lock:
# #                 try:
# #                     df = pd.read_csv(output_csv_path)
# #                     # Remove the old entry for this specific parking lot
# #                     df = df[df['ParkingLotID'] != parking_lot_id]
# #                 except (FileNotFoundError, pd.errors.EmptyDataError):
# #                     df = pd.DataFrame()

# #                 cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
# #                 new_row = pd.DataFrame([[parking_lot_id, timestamp] + final_status], columns=cols)
# #                 df = pd.concat([df, new_row], ignore_index=True)
# #                 df.to_csv(output_csv_path, index=False)
            
# #             prev_status = list(final_status)

# #         # 📊 DETAILED REPORTING: Log Every Second
# #         current_time = time.time()
# #         if current_time - last_log_time >= 1.0:
# #             ts_sec = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
# #             cols = ['ParkingLotID', 'Timestamp'] + [f'SP{i+1}' for i in range(len(final_status))]
# #             new_row = pd.DataFrame([[parking_lot_id, ts_sec] + final_status], columns=cols)
            
# #             # Append to lot-specific history file
# #             file_exists = os.path.isfile(history_csv_path)
# #             new_row.to_csv(history_csv_path, mode='a', index=False, header=not file_exists)
            
# #             last_log_time = current_time

# #         # 🎨 DRAW PARKING SPOTS (Red = Occupied, Green = Empty)
# #         for i, spot in enumerate(spots):
# #             # Change color based on occupancy
# #             color = (0, 0, 255) if final_status[i] == 'occupied' else (0, 255, 0)
            
# #             # Draw the polygon lines for the spot
# #             cv2.polylines(frame, [spot], True, color, 2)
            
# #             # Put the "SPX" text at the center of the spot
# #             area_center = np.mean(spot, axis=0).astype(int)
# #             cv2.putText(frame, f'SP{i+1}', tuple(area_center), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

# #         cv2.imshow(f"Monitor: {parking_lot_id}", frame)
# #         if cv2.waitKey(1) & 0xFF == ord('q'): break

# #     cap.release()
# #     cv2.destroyAllWindows()

# # def main():
# #     root_dir = Path(__file__).resolve().parents[1]
    
# #     # Paths for configuration and the live snapshot output
# #     config_csv = os.path.join(root_dir, 'data', 'parking_lots.csv')
# #     output_csv_path = os.path.join(root_dir, 'data', 'parking_status.csv')
    
# #     if not os.path.exists(config_csv):
# #         print(f"Error: Missing config at {config_csv}")
# #         return

# #     parking_lots_data = pd.read_csv(config_csv)
# #     processes = []
# #     lock = Lock() # Lock is required here for the shared parking_status.csv

# #     for _, lot in parking_lots_data.iterrows():
# #         # Handle ROI path dynamically
# #         roi_filename = os.path.basename(lot['ROI'])
# #         roi_path = os.path.join(root_dir, 'data', roi_filename)

# #         p = Process(target=process_parking_lot, args=(
# #             lot['ParkingLotID'], 
# #             lot['URL'], 
# #             roi_path,
# #             output_csv_path,
# #             lock,
# #             root_dir
# #         ))
# #         p.start()
# #         processes.append(p)

# #     for p in processes: p.join()

# # if __name__ == '__main__':
# #     main()

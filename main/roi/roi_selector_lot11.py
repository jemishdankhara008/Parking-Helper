import cv2
import numpy as np
import pandas as pd
from ultralytics import YOLO
import subprocess
import os
from pathlib import Path
import torch 

# --- GLOBAL STATE FOR UI ---
all_spots = {}  
current_points = [] 
display_frame = None 

def calculate_iou(box1, box2):
    x1_1, y1_1, x2_1, y2_1 = box1
    x1_2, y1_2, x2_2, y2_2 = box2

    xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
    xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
    inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)

    box1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
    box2_area = (x2_2 - x1_2) * (y2_2 - y1_2)
    union_area = box1_area + box2_area - inter_area

    if union_area == 0: return 0
    return inter_area / union_area

# ⚡ TUNED: Threshold increased to 0.55 to allow tight side-by-side parking
def check_aggressive_overlap(box1, box2, threshold=0.55):
    x1_1, y1_1, x2_1, y2_1 = box1
    x1_2, y1_2, x2_2, y2_2 = box2

    cx1, cy1 = (x1_1 + x2_1) / 2, (y1_1 + y2_1) / 2
    cx2, cy2 = (x1_2 + x2_2) / 2, (y1_2 + y2_2) / 2
    
    if (x1_2 <= cx1 <= x2_2 and y1_2 <= cy1 <= y2_2) or \
       (x1_1 <= cx2 <= x2_1 and y1_1 <= cy2 <= y2_1):
        return True 

    dist = np.sqrt((cx1 - cx2)**2 + (cy1 - cy2)**2)
    min_width = min(x2_1 - x1_1, x2_2 - x1_2)
    
    # ⚡ TUNED: Relaxed proximity from 0.70 to 0.40
    if dist < (min_width * 0.40):
        return True

    xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
    xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
    inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)

    box1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
    box2_area = (x2_2 - x1_2) * (y2_2 - y1_2)
    
    if inter_area > 0:
        min_area = min(box1_area, box2_area)
        if (inter_area / min_area) > threshold:
            return True

    return False

def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0: return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def sort_spots_sequentially(polygons):
    if not polygons: return {}

    spots_data = []
    for poly in polygons:
        cx = sum(p[0] for p in poly) / len(poly)
        bottom_y = max(p[1] for p in poly)
        box_height = max(p[1] for p in poly) - min(p[1] for p in poly)
        spots_data.append({'polygon': poly, 'cx': cx, 'bottom_y': bottom_y, 'height': box_height})

    spots_data.sort(key=lambda item: item['bottom_y'], reverse=True)

    rows = []
    while spots_data:
        seed = spots_data.pop(0)
        current_row = [seed]
        
        i = 0
        while i < len(spots_data):
            candidate = spots_data[i]
            tolerance = max(20, seed['height'] * 0.65)
            if abs(candidate['bottom_y'] - seed['bottom_y']) <= tolerance:
                current_row.append(spots_data.pop(i))
            else:
                i += 1
        
        current_row.sort(key=lambda item: item['cx'])
        rows.append(current_row)

    sorted_dict = {}
    spot_counter = 1
    for row in rows:
        for s in row:
            sorted_dict[f"SP{spot_counter}"] = s['polygon']
            spot_counter += 1

    return sorted_dict

def mouse_callback(event, x, y, flags, params):
    global all_spots, current_points, display_frame

    if event == cv2.EVENT_LBUTTONDOWN:
        current_points.append((x, y))
        if len(current_points) == 4:
            polygons = list(all_spots.values())
            polygons.append(current_points.copy())
            all_spots = sort_spots_sequentially(polygons)
            print(f"➕ Added Manual Spot & Re-Sequenced! (Total: {len(all_spots)})")
            current_points = []

    elif event == cv2.EVENT_RBUTTONDOWN:
        for spot_id, spot in list(all_spots.items()):
            if cv2.pointPolygonTest(np.array(spot, np.int32), (x, y), False) >= 0:
                del all_spots[spot_id]
                polygons = list(all_spots.values())
                all_spots = sort_spots_sequentially(polygons)
                print(f"🗑️ Deleted Spot & Re-Sequenced! (Remaining: {len(all_spots)})")
                current_points = [] 
                break

    elif event == cv2.EVENT_MBUTTONDOWN:
        for spot_id, spot in list(all_spots.items()):
            if cv2.pointPolygonTest(np.array(spot, np.int32), (x, y), False) >= 0:
                new_id = input(f"Enter new ID for this spot (or press Enter to cancel): ").strip()
                if new_id and new_id != spot_id:
                    all_spots[new_id] = all_spots.pop(spot_id)
                    print(f"✅ Success! Spot updated to {new_id}.")
                break

def run_smart_mapper(video_source, root_dir, output_csv_name, playback_speed=2, load_existing=False):
    global all_spots, display_frame

    video_playlist = []
    
    if os.path.isdir(video_source):
        valid_extensions = ('.mp4', '.avi', '.mov', '.mkv')
        for file in sorted(os.listdir(video_source)):
            if file.lower().endswith(valid_extensions):
                video_playlist.append(os.path.join(video_source, file))
        if len(video_playlist) == 0:
            print("❌ Error: No valid video files found in the directory.")
            return
    elif "youtube.com" in video_source or "youtu.be" in video_source:
        try:
            print("Extracting YouTube stream via yt-dlp CLI...")
            result = subprocess.run(
                ['yt-dlp', '-f', 'best[height<=720]/best', '-g', video_source],
                capture_output=True, text=True, check=True
            )
            final_video_path = result.stdout.strip().split('\n')[0]
            if not final_video_path.startswith('http'):
                raise ValueError("Failed to extract a valid stream URL.")
            video_playlist.append(final_video_path)
        except Exception as e:
            print(f"\n❌ Error loading YouTube video: {e}")
            return
    else:
        if not os.path.isabs(video_source):
            video_source = os.path.join(root_dir, video_source)
        video_playlist.append(video_source)

    discovered_spots = [] 
    
    if load_existing:
        csv_path = os.path.join(root_dir, 'data', output_csv_name)
        if os.path.exists(csv_path):
            print(f"\n⚡ Loading existing ROIs from {output_csv_name} as a baseline...")
            df = pd.read_csv(csv_path)
            for _, row in df.iterrows():
                xs = [int(row['Point1_X']), int(row['Point2_X']), int(row['Point3_X']), int(row['Point4_X'])]
                ys = [int(row['Point1_Y']), int(row['Point2_Y']), int(row['Point3_Y']), int(row['Point4_Y'])]
                
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                discovered_spots.append((x1, y1, x2, y2))
            
            print(f"-> Successfully loaded {len(discovered_spots)} existing spots!")

    model_candidates = [
        os.path.join(root_dir, 'yolov8n.pt'),
        os.path.join(root_dir, 'yolov8s.pt'),
    ]
    model_path = next((path for path in model_candidates if os.path.exists(path)), None)
    if model_path is None:
        raise FileNotFoundError("Missing yolov8n.pt and yolov8s.pt in the project root.")
    model = YOLO(model_path)

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"\n🚀 Hardware Check: YOLOV8 is running on -> {device.upper()}")
    model.to(device)

    print("\n===========================================")
    print(" 🤖 PHASE 1: AUTOMATIC ROI DISCOVERY")
    print("===========================================")
    print(f"- Scanning video(s) using Dual-Inference Sniper Mode...")
    print("- Press 'n' to SKIP the current video.")
    print("- Press 'd' to FINISH scanning all videos.")

    frame_count = 0
    last_valid_frame = None 
    force_exit_scan = False

    for vid_index, current_video in enumerate(video_playlist):
        if force_exit_scan: break
            
        print(f"\n▶️ Playing Video {vid_index + 1} of {len(video_playlist)}...")
        cap = cv2.VideoCapture(current_video)
        
        if not cap.isOpened():
            print(f"⚠️ Warning: Could not open {current_video}. Skipping...")
            continue
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0: fps = 30 
        
        total_frames_in_vid = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        total_vid_seconds = total_frames_in_vid / fps if total_frames_in_vid > 0 else 0
            
        tracked_spots = [] 
        
        live_draw_threshold = int(450 / playback_speed) 
        lock_in_threshold = int(600 / playback_speed)   

        while True:
            for _ in range(playback_speed - 1): cap.read()
            ret, frame = cap.read()
            
            if not ret: 
                print(f"⏹️ Reached the end of Video {vid_index + 1}.")
                break 
                
            last_valid_frame = frame.copy() 
            frame_height = frame.shape[0] 
            frame_width = frame.shape[1]
            frame_count += playback_speed 
            
            current_frame_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)
            current_vid_seconds = current_frame_pos / fps
            time_display = f"Time: {format_time(current_vid_seconds)} / {format_time(total_vid_seconds)}" if total_vid_seconds > 0 else f"Time: {format_time(current_vid_seconds)} (Stream)"

            raw_detections = []

            # ⚡ TUNED: Confidence thresolds slightly increased to avoid ultra-noisy small spots
            results_normal = model.predict(frame, verbose=False, conf=0.15, imgsz=1920, device=device)
            for det in results_normal[0].boxes.data:
                x1, y1, x2, y2, conf, cls = map(int, det[:6])
                if cls in [2, 3, 5, 7]: 
                    raw_detections.append((x1, y1, x2, y2))

            scale_factor = 1.5
            crop_h = int(frame_height * 0.65)
            top_crop = frame[0:crop_h, :] 
            zoomed_crop = cv2.resize(top_crop, (0, 0), fx=scale_factor, fy=scale_factor) 
            
            results_zoomed = model.predict(zoomed_crop, verbose=False, conf=0.10, imgsz=1920, device=device)
            for det in results_zoomed[0].boxes.data:
                zx1, zy1, zx2, zy2, conf, cls = map(int, det[:6])
                if cls in [2, 3, 5, 7]: 
                    x1 = int(zx1 / scale_factor)
                    y1 = int(zy1 / scale_factor)
                    x2 = int(zx2 / scale_factor)
                    y2 = int(zy2 / scale_factor)
                    raw_detections.append((x1, y1, x2, y2))

            raw_detections.sort(key=lambda b: (b[2]-b[0])*(b[3]-b[1]), reverse=True)
            
            clean_detections = []
            for (x1, y1, x2, y2) in raw_detections:
                box_width, box_height = x2 - x1, y2 - y1
                distance_ratio = y2 / frame_height 
                
                dynamic_min_width = int(12 + (40 * distance_ratio))
                dynamic_min_height = int(8 + (30 * distance_ratio))
                
                if box_width < dynamic_min_width or box_height < dynamic_min_height: 
                    continue
                    
                if box_width > (box_height * 1.3):
                    expected_height = int(box_width * 0.90) 
                    y2 = min(frame_height, y1 + expected_height) 

                is_duplicate = False
                for kept_box in clean_detections:
                    if check_aggressive_overlap((x1, y1, x2, y2), kept_box):
                        is_duplicate = True
                        break
                if not is_duplicate:
                    clean_detections.append((x1, y1, x2, y2))

            for (x1, y1, x2, y2) in clean_detections:
                already_mapped = False
                for confirmed_box in discovered_spots:
                    if check_aggressive_overlap((x1, y1, x2, y2), confirmed_box):
                        already_mapped = True
                        break
                
                if already_mapped: continue 
                
                matched = False
                for spot in tracked_spots:
                    # ⚡ TUNED: Dropped IoU tracking strictness from 0.85 to 0.65.
                    # Now if the YOLO box jitters or shakes a bit, it will STILL lock in!
                    if calculate_iou((x1, y1, x2, y2), spot['box']) > 0.65:
                        spot['count'] += 1
                        matched = True
                        if spot['count'] == lock_in_threshold:
                            discovered_spots.append(spot['box'])
                        break
                
                if not matched:
                    tracked_spots.append({'box': (x1, y1, x2, y2), 'count': 1})

            display_clone = frame.copy()
            
            for box in discovered_spots:
                sx1, sy1, sx2, sy2 = box
                cv2.rectangle(display_clone, (sx1, sy1), (sx2, sy2), (0, 165, 255), 2)
                cv2.putText(display_clone, "LOCKED", (sx1, sy1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)

            for spot in tracked_spots:
                if live_draw_threshold < spot['count'] < lock_in_threshold:
                    sx1, sy1, sx2, sy2 = spot['box']
                    cv2.rectangle(display_clone, (sx1, sy1), (sx2, sy2), (0, 255, 0), 2)
                    cv2.putText(display_clone, "Verifying...", (sx1, sy1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

            ui_text_1 = f"Vid {vid_index+1}/{len(video_playlist)} | {time_display} | Speed: {playback_speed}x | Device: {device.upper()}"
            cv2.putText(display_clone, ui_text_1, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(display_clone, "Press 'n' to Skip Video | 'd' to Finish ALL", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imshow("Auto-Discovery", display_clone)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('d'): 
                force_exit_scan = True
                break
            elif key == ord('n'):
                print(f"⏭️ Skipping Video {vid_index + 1}...")
                break

        cap.release()
        
    cv2.destroyAllWindows()
    
    if last_valid_frame is None:
        print("\n❌ Error: Could not read any frames from the provided source(s).")
        return
    
    print("\n🧹 Final Cleanup: Destroying overlapping boxes...")
    all_gathered_boxes = discovered_spots.copy()
    
    for spot in tracked_spots:
        if spot['count'] > live_draw_threshold and spot['box'] not in discovered_spots:
            all_gathered_boxes.append(spot['box'])

    all_gathered_boxes.sort(key=lambda b: (b[2]-b[0])*(b[3]-b[1]), reverse=True)

    final_clean_boxes = []
    for box in all_gathered_boxes:
        is_duplicate = False
        for final_box in final_clean_boxes:
            if check_aggressive_overlap(box, final_box):
                is_duplicate = True
                break
        
        if not is_duplicate:
            final_clean_boxes.append(box)

    raw_polygons = []
    for box in final_clean_boxes:
        x1, y1, x2, y2 = box
        raw_polygons.append([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])

    all_spots = sort_spots_sequentially(raw_polygons)
    background_frame = last_valid_frame.copy()

    print("\n===========================================")
    print(" 🛠️ PHASE 2: MANUAL CORRECTION")
    print("===========================================")
    print(f"- Displaying {len(all_spots)} perfect parking spots.")
    print("- LEFT CLICK 4 times to ADD a missing spot.")
    print("- RIGHT CLICK inside a box to DELETE an incorrect spot.")
    print("- MIDDLE CLICK (Scroll Wheel) inside a box to RENAME its ID.")
    print("- Press 's' to SAVE all spots to CSV and exit.")
    
    cv2.namedWindow("Smart ROI Corrector")
    cv2.setMouseCallback("Smart ROI Corrector", mouse_callback)

    while True:
        display_frame = background_frame.copy()

        for spot_id, spot in all_spots.items():
            pts = np.array(spot, np.int32)
            cv2.polylines(display_frame, [pts], True, (0, 255, 0), 2)
            cv2.putText(display_frame, spot_id, (spot[0][0], spot[0][1]-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        for pt in current_points:
            cv2.circle(display_frame, pt, 5, (0, 0, 255), -1)
        if len(current_points) > 1:
            cv2.polylines(display_frame, [np.array(current_points, np.int32)], False, (0, 255, 255), 1)

        # ⚡ SAVE FRAME FOR WEB UI PREVIEW
        frame_roi_path = os.path.join(root_dir, 'data', 'latest_frame_roi.jpg')
        cv2.imwrite(frame_roi_path, display_frame)

        cv2.imshow("Smart ROI Corrector", display_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('s'): break

    cv2.destroyAllWindows()

    if all_spots:
        formatted_data = []
        for spot_id, spot in all_spots.items():
            formatted_data.append({
                'SpotID': spot_id,
                'Point1_X': spot[0][0], 'Point1_Y': spot[0][1],
                'Point2_X': spot[1][0], 'Point2_Y': spot[1][1],
                'Point3_X': spot[2][0], 'Point3_Y': spot[2][1],
                'Point4_X': spot[3][0], 'Point4_Y': spot[3][1]
            })
        
        df = pd.DataFrame(formatted_data)
        data_dir = os.path.join(root_dir, 'data')
        os.makedirs(data_dir, exist_ok=True)
        out_path = os.path.join(data_dir, output_csv_name)
        df.to_csv(out_path, index=False)
        print(f"\n✅ SUCCESS: {len(all_spots)} ROIs intelligently mapped and saved to {out_path}!")
    else:
        print("\n⚠️ No spots were saved.")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Smart Auto-ROI Mapper")
    parser.add_argument("--video", type=str, help="Path to video file, folder, or YouTube URL")
    parser.add_argument("--csv", type=str, help="Output CSV name (e.g., PL01.csv)")
    parser.add_argument("--speed", type=int, default=2, help="Scanning speed (1, 2, 5, etc.)")
    parser.add_argument("--load-baseline", action="store_true", help="Load existing ROIs")
    parser.add_argument("--no-load-baseline", action="store_false", dest="load_baseline", help="Do not load existing ROIs")
    parser.set_defaults(load_baseline=None)
    
    args = parser.parse_args()
    root_dir = Path(__file__).resolve().parents[1]
    
    video_input = args.video
    if not video_input:
        print("=== Smart Auto-ROI Mapper ===")
        video_input = input("1. Enter file path, YouTube URL, OR a Folder path:\n> ").strip()
    if not video_input: return
        
    csv_input = args.csv
    if not csv_input:
        csv_input = input("\n2. Enter output CSV name (e.g., PL01.csv):\n> ").strip()
    if not csv_input.endswith('.csv'): csv_input += '.csv'
        
    data_dir = os.path.join(root_dir, 'data')
    csv_path = os.path.join(data_dir, csv_input)
    
    load_existing = args.load_baseline
    if load_existing is None:
        if os.path.exists(csv_path):
            print(f"\n📁 Existing '{csv_input}' found!")
            choice = input("Do you want to LOAD existing ROIs as a baseline before scanning? (y/n):\n> ").strip().lower()
            load_existing = (choice == 'y')
        else:
            load_existing = False
            
    playback_speed = args.speed
    if not args.video: # Only prompt if not provided via args
        speed_input = input("\n3. Enter scanning speed (1 for normal, 2 for 2x, 5 for 5x. Default is 2):\n> ").strip()
        if speed_input.isdigit():
            playback_speed = int(speed_input)
        
    run_smart_mapper(video_input, root_dir, csv_input, playback_speed, load_existing)

if __name__ == '__main__':
    main()

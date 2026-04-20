# Utility script that accumulates vehicle detections into a heatmap image for manual ROI planning.
import cv2
import numpy as np
from ultralytics import YOLO
import yt_dlp
import os
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

def generate_heatmap(video_source, root_dir, output_filename):
    # 1. Load Model (Robust pathing for your YOLO model)
    model_path = os.path.join(root_dir, 'src', 'models', 'yolov8n.pt')
    if not os.path.exists(model_path):
        model_path = os.path.join(root_dir, 'main', 'src', 'models', 'yolov8n.pt')
    
    print("Loading YOLO Model...")
    model = YOLO(model_path)

    # 2. Handle Video Source
    final_video_path = video_source
    if "youtube.com" in video_source or "youtu.be" in video_source:
        print("Extracting YouTube stream...")
        final_video_path = get_youtube_stream(video_source)
    elif not video_source.startswith(('http', 'https')):
        final_video_path = os.path.join(root_dir, video_source)

    cap = cv2.VideoCapture(final_video_path)
    if not cap.isOpened():
        print(f"❌ Error: Could not open video at {final_video_path}")
        return

    # Initialize empty array for accumulating "heat"
    heatmap_accum = None
    print(f"\n🔥 Generating Heatmap: {output_filename}... Let it run for a few minutes.")
    print("Press 'q' on the video window to Save and Exit.\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Video ended.")
            break

        # Setup the heatmap array once we know the frame dimensions
        if heatmap_accum is None:
            heatmap_accum = np.zeros((frame.shape[0], frame.shape[1]), dtype=np.float32)

        # Inference
        results = model.predict(frame, verbose=False, conf=0.25)
        detections = results[0].boxes.data

        # Each detected vehicle increments the pixels under its box so repeated parking patterns brighten over time.
        # Add Heat
        for det in detections:
            x1, y1, x2, y2, conf, cls = det
            if int(cls) in [2, 3, 5, 7]: # Vehicles
                # Accumulate heat where the vehicle is detected
                heatmap_accum[int(y1):int(y2), int(x1):int(x2)] += 1.0

        # Create the visual heatmap overlay
        heatmap_norm = cv2.normalize(heatmap_accum, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
        _, heat_mask = cv2.threshold(heatmap_norm, 5, 255, cv2.THRESH_BINARY)
        
        # Apply JET colormap (Blue=Low, Red=High)
        heatmap_color = cv2.applyColorMap(heatmap_norm, cv2.COLORMAP_JET)
        heatmap_color = cv2.bitwise_and(heatmap_color, heatmap_color, mask=heat_mask)
        
        # Blend the heatmap with the original frame
        overlay = cv2.addWeighted(heatmap_color, 0.6, frame, 1.0, 0, frame)

        # Add On-Screen HUD for Professional Look
        cv2.putText(overlay, "GENERATING HEATMAP...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(overlay, f"Output: {output_filename}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay, "Press 'q' to Save and Exit", (20, frame.shape[0] - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        cv2.imshow("Heatmap Calibration Tool", overlay)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    # 3. Save the final image for ROI mapping
    output_dir = os.path.join(root_dir, 'data')
    os.makedirs(output_dir, exist_ok=True)
    save_path = os.path.join(output_dir, output_filename)
    
    cv2.imwrite(save_path, overlay)
    print(f"\n✅ SUCCESS: Heatmap saved to: {save_path}")
    print("You can now load this image in your ROI Selector tool!")

def main():
    root_dir = Path(__file__).resolve().parents[1]
    
    print("=======================================")
    print(" Parking Helper: Heatmap Calibration ")
    print("=======================================\n")
    
    video_input = input("1. Enter video file path (e.g., recordings/lot11.mp4) or YouTube URL:\n> ").strip()
    
    if not video_input:
        print("Invalid video input. Exiting.")
        return

    output_input = input("\n2. Enter name to save image as (e.g., lot11_heatmap.jpg):\n> ").strip()
    if not output_input:
        output_input = "default_heatmap.jpg"
    if not output_input.endswith('.jpg') and not output_input.endswith('.png'):
        output_input += ".jpg"
        
    generate_heatmap(video_input, root_dir, output_input)

if __name__ == '__main__':
    main()

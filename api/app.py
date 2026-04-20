# FastAPI entrypoint that wires together prediction, reservations, auth, and live-monitor routes.
from fastapi import FastAPI, HTTPException, UploadFile, File  # Web API and file upload types
from fastapi.middleware.cors import CORSMiddleware  # Browser / Streamlit Cloud → Render
from pydantic import BaseModel  # Validate structured JSON responses
import cv2  # Decode image bytes to BGR arrays
import numpy as np  # Buffer to array for OpenCV decode
from ultralytics import YOLO  # Vehicle detection neural network
import os  # Join paths and check file existence
from pathlib import Path  # Resolve project root relative to this file
import torch  # CUDA availability and device placement
from .reservations import router as reservations_router
from .live_routes import router as live_router
from .auth import router as auth_router


def _cors_allow_origins():  # CORS_ORIGINS=* or comma-separated list (e.g. https://yourapp.streamlit.app)
    raw = (os.environ.get("CORS_ORIGINS") or "*").strip()
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()] or ["*"]


# ============================================
# SECTION: Setup & Config
# FastAPI app, device, paths
# ============================================
# • Builds the Parking Helper FastAPI application and metadata
# • Picks GPU or CPU before any model work runs
# • Resolves project root so weight files can be found in two layouts
# • Defines candidate paths to yolov8n.pt and yolov8s.pt at the project root
# ============================================

app = FastAPI(  # Create FastAPI app with OpenAPI metadata
    title="Parking Helper API",  # Title shown in Swagger UI
    description="API for detecting parking lot occupancy using YOLO",  # Long description string
    version="1.0"  # Version tag for clients
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(reservations_router)
app.include_router(auth_router)
app.include_router(live_router)

model = None  # Global YOLO instance filled on startup
device = 'cuda' if torch.cuda.is_available() else 'cpu'  # GPU if available

root_dir = Path(__file__).resolve().parents[1]  # project root above api/

model_candidates = [
    os.path.join(root_dir, 'yolov8n.pt'),
    os.path.join(root_dir, 'yolov8s.pt'),
]


# ============================================
# SECTION: Load Model
# Direct .pt loading at startup
# ============================================
# • Chooses the first existing local path or falls back to Ultralytics default
# • Loads YOLO weights and moves the model to the chosen device
# • Prints success or logs errors without crashing the import
# • Leaves model None if loading fails so endpoints can guard safely
# ============================================

print("Loading YOLO model...")  # Log startup progress to console

model_path = next((path for path in model_candidates if os.path.exists(path)), None)

if model_path is None:  # Neither local file exists
    print("Model not found locally. Expected yolov8n.pt or yolov8s.pt in the project root.")  # Inform user of required files

try:  # Isolate load failures from crashing import
    if model_path is None:
        raise FileNotFoundError("Missing yolov8n.pt and yolov8s.pt in the project root.")
    model = YOLO(model_path)  # Construct Ultralytics model
    model.to(device)  # Move weights to GPU or CPU
    print(f"Model loaded successfully from {model_path} on {device.upper()}!")  # Confirm device placement
except Exception as e:  # Catch missing file or CUDA errors
    print(f"Error loading model: {e}")  # Print failure without raising


class PredictionOutput(BaseModel):  # Response schema for predict endpoint
    prediction: list  # List of detection dicts with bbox
    total_vehicles: int  # Count of vehicle detections
    status: str  # success or error label string


@app.get('/')  # Welcome route at root URL
def root():  # Simple discovery JSON for humans
    return {  # Static instructions object
        "message": "Welcome to the Parking Helper API!",  # Greeting string
        "instructions": "Open /docs in your browser to try the API."  # Swagger hint
    }


# ============================================
# SECTION: Health Endpoint
# GET /health — liveness and model flag
# ============================================
# • Reports that the API process is up and responding
# • Exposes whether the YOLO model finished loading
# • Gives a tiny JSON payload suitable for load balancers or scripts
# ============================================

@app.get('/health')  # Liveness probe for orchestration
def health():  # Minimal status for load balancers
    return {  # JSON health payload
        'status': 'healthy',  # Process is up
        'model_loaded': model is not None  # Inference ready flag
    }


# ============================================
# SECTION: Info Endpoint
# GET /info — model and API metadata
# ============================================
# • Describes the model family and expected input type
# • Gives a simple version string for clients to display
# • Documents that callers should send an image file for prediction
# ============================================

@app.get('/info')  # Static API capability metadata
def info():  # Describe expected inputs and version
    return {  # Fixed info dict for clients
        'model_type': 'YOLO26x (Ultralytics)',  # Model family name
        'features_expected': ['image_file'],  # Document multipart upload
        'version': '1.0'  # API semantic version string
    }


# ============================================
# SECTION: Predict Endpoint
# Returns full detection array with bboxes
# ============================================
# • Reads the uploaded image bytes from the multipart request
# • Decodes bytes to an OpenCV image and runs YOLO on the GPU or CPU
# • Keeps only vehicle classes: car, motorcycle, bus, truck
# • Returns every kept box with class id, score, and pixel bounding box
# • Adds total_vehicles and a success status for the Streamlit UI
# ============================================

@app.post('/predict', response_model=PredictionOutput)  # POST image returns detections
async def predict(file: UploadFile = File(...)):  # Async multipart handler
    if model is None:  # Guard when model failed to load
        raise HTTPException(status_code=500, detail="Model is not loaded on the server.")  # Internal error

    try:  # Isolate decode and inference errors
        contents = await file.read()  # raw upload bytes
        nparr = np.frombuffer(contents, np.uint8)  # bytes to array for OpenCV
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)  # decode image to BGR

        if img is None:  # decode failed for corrupt data
            raise HTTPException(status_code=400, detail="Invalid image file provided.")  # Bad request

        results = model.predict(img, verbose=False, conf=0.10, imgsz=1920, device=device)  # run YOLO

        detections = []  # Accumulate filtered vehicle boxes
        boxes_data = results[0].boxes.data if results[0].boxes is not None else []  # all raw boxes
        for det in boxes_data:  # Iterate each tensor row
            x1, y1, x2, y2, conf, cls = map(float, det[:6])  # unpack one detection
            if int(cls) in [2, 3, 5, 7]:  # vehicle COCO classes only
                detections.append({  # Build one detection dict
                    "class_id": int(cls),  # COCO class id integer
                    "confidence": round(conf, 2),  # Rounded score for JSON
                    "bbox": [int(x1), int(y1), int(x2), int(y2)]  # Integer pixel corners
                })

        return {  # Successful prediction payload
            'prediction': detections,  # Full list of vehicles
            'total_vehicles': len(detections),  # Count matches list length
            'status': 'success'  # Client success marker
        }

    except HTTPException:
        raise
    except Exception as e:  # Re-raise HTTP or wrap others
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")  # Generic server error detail

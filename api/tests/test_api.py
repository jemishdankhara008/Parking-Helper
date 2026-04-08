import requests
import os

API_URL = "http://localhost:8000"

# Use any small test image - we'll create one if none exists
TEST_IMAGE_PATH = "test_image.jpg"

def get_test_image():
    """Use existing image or create a tiny one for testing."""
    # Try to find an image in common locations
    candidates = [
        "data/lot11_heatmap.jpg",
        "test_image.jpg",
        "test_image.png",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    # Create a minimal valid JPEG if none found
    import struct
    minimal_jpg = (
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
        b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
        b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1e\x1f'
        b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
        b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b'
        b'\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x0f\xff\xd9'
    )
    with open("test_image.jpg", "wb") as f:
        f.write(minimal_jpg)
    return "test_image.jpg"


def test_health():
    r = requests.get(f"{API_URL}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    print("✅ /health passed")


def test_info():
    r = requests.get(f"{API_URL}/info")
    assert r.status_code == 200
    print("✅ /info passed")


def test_predict_valid():
    img_path = get_test_image()
    with open(img_path, "rb") as f:
        r = requests.post(
            f"{API_URL}/predict",
            files={"file": (os.path.basename(img_path), f, "image/jpeg")}
        )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "prediction" in data
    assert "status" in data
    assert "total_vehicles" in data
    print(f"✅ /predict valid image passed → {data['total_vehicles']} vehicles detected")


def test_predict_no_file():
    r = requests.post(f"{API_URL}/predict")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    print("✅ /predict no file handled correctly")


def test_predict_wrong_type():
    r = requests.post(
        f"{API_URL}/predict",
        files={"file": ("test.txt", b"not an image", "text/plain")}
    )
    assert r.status_code in [422, 500], f"Expected 422/500, got {r.status_code}"
    print("✅ /predict wrong file type handled correctly")


if __name__ == "__main__":
    print("🧪 Running API tests...\n")
    test_health()
    test_info()
    test_predict_valid()
    test_predict_no_file()
    test_predict_wrong_type()
    print("\n🎉 All tests passed!")
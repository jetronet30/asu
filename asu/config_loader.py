import json
import os
from pathlib import Path

class Config:
    def __init__(self, path="config.json"):
        self._load(path)
        self._prepare_dirs()
        self._cleanhls()

    def _load(self, path):
            path = Path(path)

            if not path.exists():
                raise FileNotFoundError(f"Config file not found: {path}")

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # assign values
            self.TCP_SERVER_IP = data.get("TCP_SERVER_IP", "127.0.0.1")
            self.TCP_SERVER_PORT = data.get("TCP_SERVER_PORT", 45000)
            self.CAMERA_URL_1 = data.get("CAMERA_URL_1")
            self.CAMERA_URL_2 = data.get("CAMERA_URL_2")
            self.SAVE_IMAGES_DIR = data.get("SAVE_IMAGES_DIR", "saved_images")
            self.HLS_DIR = data.get("HLS_DIR", "hls")
            self.VIDEO_ARCHIVE_DIR = data.get("VIDEO_ARCHIVE_DIR", "videoarchive")
            self.YOLO_MODEL_PATH = data.get("MODEL_PATH", "best.pt")
            self.TROCR_MODEL_PATH = data.get("TROCR_MODEL_PATH", "models/trocr-large-printed")

            # Camera 1
            self.OBJECT_MIN_CONFIDENCE_1 = data.get("OBJECT_MIN_CONFIDENCE_1", 0.5)
            self.OBJECT_MIN_WIDTH_1 = data.get("OBJECT_MIN_WIDTH_1", 450)
            self.OBJECT_MIN_HEIGHT_1 = data.get("OBJECT_MIN_HEIGHT_1", 100)
            
            # Camera 2
            self.OBJECT_MIN_CONFIDENCE_2 = data.get("OBJECT_MIN_CONFIDENCE_2", 0.5)
            self.OBJECT_MIN_WIDTH_2 = data.get("OBJECT_MIN_WIDTH_2", 450)
            self.OBJECT_MIN_HEIGHT_2 = data.get("OBJECT_MIN_HEIGHT_2", 100)
            

    def _prepare_dirs(self):
            os.makedirs(self.SAVE_IMAGES_DIR, exist_ok=True)
            os.makedirs(self.HLS_DIR, exist_ok=True)
            os.makedirs(self.VIDEO_ARCHIVE_DIR, exist_ok=True)

    def _cleanhls(self):
            for file in os.listdir(self.HLS_DIR):
                if file.endswith(".ts"):
                    os.remove(os.path.join(self.HLS_DIR, file))
       
config = Config()        


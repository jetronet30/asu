#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WAGON TRACKER v15.9 — პაკეტური ვერსია (aw_7)
ობიექტის დათვლის ლოგიკა სრულად ამოღებულია (COUNT + detected_count)
"""

import sys
import os
import cv2
import time
import signal
import logging
import numpy as np
import subprocess
from threading import Thread, Lock
from pathlib import Path

# ==================== OpenCV FFmpeg ====================
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|buffer_size;1024000|stimeout;5000000|"
    "analyzeduration;10000000|probesize;10000000"
)

# ==================== PyInstaller ====================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("WAGON_TRACKER")


# ==================== CONFIG ====================
MODEL_PATH = resource_path("best.pt")

TCP_IDENTIFIER = "5"
TCP_SERVER_IP = "192.168.1.30"
TCP_SERVER_PORT = 45000
RECONNECT_DELAY = 10
DETECTION_EVERY_N_FRAME = 1

MIN_CONFIDENCE = 0.5

OBJECT_MIN_WIDTH = 300
OBJECT_MIN_HEIGHT = 70

CAMERAS = [
    {
        "name": "cam 1",
        "url": "rtsp://admin:@192.168.1.12:554?rtsp_transport=tcp"
    }
]

HLS_DIR = "hls"

HLS_PLAYLIST_NAME = "playlist.m3u8"

SAVE_DIR = "number_sectors"


# ==================== GLOBAL FLAGS ====================
running = [True]
detection_enabled = [False]
detection_lock = Lock()
cameras = []


# ==================== RELATIVE IMPORTS ====================
from . import videorecorder
from . import tcpclient
from .image_saver import ImageSaver
from .wagon_counter import WagonCounter
from .hls_server import start_hls_server
from ultralytics import YOLO


# ==================== HELPERS ====================
image_saver = ImageSaver(SAVE_DIR)
wagon_counter = WagonCounter()


# ==================== CAMERA CLASS ====================
class Camera:
    def __init__(self, cfg, idx):
        self.cfg = cfg
        self.name = cfg["name"]
        self.latest_frame = None
        self.last_boxes = []
        self.frame_lock = Lock()
        self.data_lock = Lock()

        log.info(f"[{self.name}] YOLO მოდელის ჩატვირთვა...")
        self.model = YOLO(MODEL_PATH)
        self.model.fuse()

        Thread(target=self.run, daemon=True, name=f"CAM-{self.name}").start()

    def run(self):
        cap = None
        fc = 0

        while running[0]:
            try:
                if not cap or not cap.isOpened():
                    cap = cv2.VideoCapture(self.cfg["url"], cv2.CAP_FFMPEG)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 10)
                    cap.set(cv2.CAP_PROP_FPS, 15)
                    log.info(f"[{self.name}] RTSP TCP დაკავშირებული")

                ret, frame = cap.read()
                if not ret:
                    log.warning(f"[{self.name}] ფრეიმი ვერ მიიღო")
                    cap.release()
                    cap = None
                    time.sleep(3)
                    continue

                with self.frame_lock:
                    self.latest_frame = frame.copy()

                if detection_enabled[0] and videorecorder.video_writer is not None:
                    if hasattr(videorecorder.video_writer, "stdin"):
                        try:
                            videorecorder.video_writer.stdin.write(frame.tobytes())
                            videorecorder.video_writer.stdin.flush()
                        except (BrokenPipeError, IOError, ValueError) as e:
                            log.error(f"video_writer pipe გაწყდა: {e}")
                            videorecorder.video_writer = None

                with detection_lock:
                    currently_enabled = detection_enabled[0]

                if not currently_enabled:
                    time.sleep(0.01)
                    continue

                if fc % DETECTION_EVERY_N_FRAME != 0:
                    fc += 1
                    continue

                if detection_enabled[0] and len(self.last_boxes) > 0 and fc % (DETECTION_EVERY_N_FRAME * 1) != 0:
                    fc += 1
                    continue

                results = self.model(frame, conf=MIN_CONFIDENCE, imgsz=640, verbose=False)[0]

                with self.data_lock:
                    detected_objects = []
                    for box in results.boxes:
                        conf = float(box.conf.item())
                        if conf < MIN_CONFIDENCE:
                            continue

                        bx1, by1, bx2, by2 = map(int, box.xyxy[0])
                        detected_objects.append((bx1, by1, bx2, by2, conf))

                    self.last_boxes = detected_objects

                fc += 1
                time.sleep(0.001)

            except Exception as e:
                log.error(f"[{self.name}] Run შეცდომა: {e}")
                time.sleep(0.1)


def reset_all():
    """ბოქსების და მთვლელის გასუფთავება"""
    for cam in cameras:
        with cam.data_lock:
            cam.last_boxes = []
    wagon_counter.reset()


# ==================== HLS სტრიმინგი ====================
def log_ffmpeg_stderr(proc):
    for line in iter(proc.stderr.readline, b""):
        if line:
            log.error(f"FFmpeg HLS: {line.decode(errors='ignore').strip()}")


def stream_to_hls():
    os.makedirs(HLS_DIR, exist_ok=True)
    hls_playlist_path = os.path.join(HLS_DIR, HLS_PLAYLIST_NAME)

    command = [
        "ffmpeg", "-loglevel", "error", "-y", "-re",
        "-fflags", "genpts+discardcorrupt",          # nobuffer → genpts+discardcorrupt უფრო სტაბილურია
        "-flags", "low_delay",
        "-thread_queue_size", "512",
        "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", "1280x720", "-r", "15", "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",                       # ultrafast → veryfast (უფრო ზუსტი timing)
        "-tune", "zerolatency",
        "-profile:v", "main", "-level", "4.0", "-pix_fmt", "yuv420p",
        "-bf", "0",
        "-g", "30", "-keyint_min", "15",             # GOP 30 (2 წამი) → უკეთესი alignment
        "-sc_threshold", "0",
        "-b:v", "2800k", "-maxrate", "2800k", "-bufsize", "5600k",
        "-x264opts", "no-scenecut=1:force-cfr=1",    # force constant frame rate (მნიშვნელოვანია!)
        "-threads", "1",
        "-f", "hls",
        "-hls_time", "1",
        "-hls_list_size", "2",                       # ცოტა მეტი სეგმენტი playlist-ში
        "-hls_flags", "delete_segments+program_date_time+split_by_time",
        "-hls_delete_threshold", "3",
        "-hls_segment_type", "mpegts",
        "-strftime", "1",
        "-hls_segment_filename", os.path.join(HLS_DIR, "seg_%Y%m%d_%H%M%S.ts"),
        hls_playlist_path
    ]

    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    Thread(target=log_ffmpeg_stderr, args=(proc,), daemon=True).start()

    while running[0]:
        try:
            if not cameras or cameras[0].latest_frame is None:
                display_frame = np.zeros((720, 1280, 3), np.uint8)
                cv2.putText(
                    display_frame,
                    "NO SIGNAL - WAITING FOR CAMERA...",
                    (180, 360),
                    cv2.FONT_HERSHEY_DUPLEX,
                    2.5,
                    (0, 0, 255),
                    6
                )
            else:
                cam = cameras[0]
                with cam.frame_lock:
                    frame = cam.latest_frame.copy()

                display_frame = cv2.resize(frame, (1280, 720))

                with detection_lock:
                    det_enabled = detection_enabled[0]

                status_text = "ACTIVE" if det_enabled else "READY"
                status_color = (0, 255, 0) if det_enabled else (0, 255, 255)
                cv2.putText(
                    display_frame,
                    status_text,
                    (30, 60),
                    cv2.FONT_HERSHEY_COMPLEX,
                    2.2,
                    status_color,
                    3
                )

                if det_enabled:
                    with cam.data_lock:
                        large_boxes = []

                        for bx1, by1, bx2, by2, conf in cam.last_boxes:
                            h_orig, w_orig = frame.shape[:2]
                            gx1 = int(bx1 * 1280 / w_orig)
                            gy1 = int(by1 * 720 / h_orig)
                            gx2 = int(bx2 * 1280 / w_orig)
                            gy2 = int(by2 * 720 / h_orig)

                            width = gx2 - gx1
                            height = gy2 - gy1

                            is_large_enough = width >= OBJECT_MIN_WIDTH and height >= OBJECT_MIN_HEIGHT
                            if is_large_enough:
                                large_boxes.append((bx1, by1, bx2, by2, conf))

                            if is_large_enough:
                                box_color = (0, 255, 0)
                                label_color = (0, 200, 0)
                            else:
                                box_color = (255, 0, 0)
                                label_color = (255, 0, 0)

                            cv2.rectangle(display_frame, (gx1, gy1), (gx2, gy2), box_color, 3)
                            cv2.putText(
                                display_frame,
                                f"conf:{conf:.2f}",
                                (gx1, gy1 - 10),
                                cv2.FONT_HERSHEY_DUPLEX,
                                1.0,
                                label_color,
                                2
                            )
                            cv2.putText(
                                display_frame,
                                f"W:{width} H:{height}",
                                (gx1, gy2 + 25),
                                cv2.FONT_HERSHEY_DUPLEX,
                                1,
                                label_color,
                                2
                            )

                        current_detected = len(large_boxes) > 0
                        current_wagon_number = wagon_counter.update_detection(current_detected)

                        if current_wagon_number > 0:
                            cv2.putText(
                                display_frame,
                                f"WAGON: {current_wagon_number}",
                                (30, 120),
                                cv2.FONT_HERSHEY_COMPLEX,
                                1.6,
                                (255, 255, 255),
                                3
                            )

                        if current_detected and current_wagon_number > 0:
                            bx1, by1, bx2, by2, conf = large_boxes[0]
                            image_saver.save_crop(
                                frame,
                                bx1,
                                by1,
                                bx2,
                                by2,
                                f"{current_wagon_number}_{"sector"}",
                                conf
                            )

            yuv_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2YUV_I420)
            proc.stdin.write(yuv_frame.tobytes())
            proc.stdin.flush()
            time.sleep(0.001)

        except BrokenPipeError:
            log.error("HLS pipe გაწყდა")
            break
        except Exception as e:
            log.error(f"HLS სტრიმინგის შეცდომა: {e}")
            time.sleep(0.1)

    if proc.stdin:
        proc.stdin.close()
    proc.wait()
    log.info("HLS სტრიმინგი გაჩერდა")


# ==================== MAIN ====================
def stop_running(signum, frame):
    running[0] = False


def main():
    signal.signal(signal.SIGINT, stop_running)
    signal.signal(signal.SIGTERM, stop_running)

    log.info("=== WAGON TRACKER v15.9 (პაკეტი aw_7) STARTED ===")
    log.info("WagonCounter და ImageSaver ინტეგრირებულია")
    
    # HLS სერვერის გაშვება
    log.info("🚀 HLS სერვერის გაშვება...")
    hls_thread = start_hls_server()
    log.info("🌐 HLS სერვერი გაშვებულია: http://localhost:9091")

    global cameras
    cameras = [Camera(cfg, i) for i, cfg in enumerate(CAMERAS)]

    Thread(
        target=tcpclient.tcp_client,
        args=(
            TCP_IDENTIFIER,
            detection_enabled,
            detection_lock,
            reset_all,
            cameras,
            TCP_SERVER_IP,
            TCP_SERVER_PORT,
            RECONNECT_DELAY,
            running
        ),
        daemon=True
    ).start()

    Thread(target=stream_to_hls, daemon=True).start()

    log.info("სისტემა მზადაა! TCP: START / STOP")
    while running[0]:
        time.sleep(1)

    log.info("=== სისტემა გაჩერდა ===")


if __name__ == "__main__":
    main()

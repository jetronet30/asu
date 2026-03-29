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

from .config_loader import config
from . import videorecorder
from . import tcpclient
from .image_saver import ImageSaver
from .wagon_counter import WagonCounter
from .hls_server import start_hls_server
from ultralytics import YOLO


# ==================== OpenCV FFmpeg ====================
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|buffer_size;1024000|stimeout;5000000|"
    "analyzeduration;10000000|probesize;10000000"
)

# სურვილის შემთხვევაში შეგიძლია ეს ჩართო FFmpeg warning-ების შესამცირებლად:
# os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "0"


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
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("WAGON_TRACKER")


# ==================== CONFIG ====================
TCP_IDENTIFIER = "5"
RECONNECT_DELAY = 10
DETECTION_EVERY_N_FRAME = 1

CAMERAS = [
    {
        "name": "cam 1",
        "url": config.CAMERA_URL_1
    }
]

HLS_PLAYLIST_NAME = "playlist.m3u8"


# ==================== GLOBAL FLAGS ====================
running = [True]
detection_enabled = [False]
detection_lock = Lock()
cameras = []


# ==================== HELPERS ====================
image_saver = ImageSaver(config.SAVE_IMAGES_DIR)
wagon_counter = WagonCounter()


def is_detection_enabled():
    with detection_lock:
        return detection_enabled[0]


# ==================== CAMERA CLASS ====================
class Camera:
    def __init__(self, cfg, idx):
        self.cfg = cfg
        self.idx = idx
        self.name = cfg["name"]

        self.latest_frame = None
        self.detect_frame = None
        self.last_boxes = []
        self.last_detected_frame = None

        self.frame_lock = Lock()
        self.data_lock = Lock()

        self.frame_seq = 0
        self.detect_seq = 0

        log.info(f"[{self.name}] YOLO მოდელის ჩატვირთვა...")
        self.model = YOLO(config.YOLO_MODEL_PATH)
        self.model.fuse()

        Thread(target=self.capture_loop, daemon=True, name=f"CAP-{self.name}").start()
        Thread(target=self.detect_loop, daemon=True, name=f"DET-{self.name}").start()

    def capture_loop(self):
        cap = None

        while running[0]:
            try:
                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(self.cfg["url"], cv2.CAP_FFMPEG)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 10)
                    cap.set(cv2.CAP_PROP_FPS, 15)
                    log.info(f"[{self.name}] RTSP TCP დაკავშირებული")

                ret, frame = cap.read()
                if not ret or frame is None:
                    log.warning(f"[{self.name}] ფრეიმი ვერ მიიღო")
                    if cap is not None:
                        cap.release()
                    cap = None
                    time.sleep(3)
                    continue

                with self.frame_lock:
                    self.latest_frame = frame.copy()
                    self.detect_frame = frame.copy()
                    self.frame_seq += 1

                if is_detection_enabled() and videorecorder.video_writer is not None:
                    if hasattr(videorecorder.video_writer, "stdin") and videorecorder.video_writer.stdin:
                        try:
                            videorecorder.video_writer.stdin.write(frame.tobytes())
                            videorecorder.video_writer.stdin.flush()
                        except (BrokenPipeError, IOError, ValueError) as e:
                            log.error(f"video_writer pipe გაწყდა: {e}")
                            videorecorder.video_writer = None

            except Exception as e:
                log.error(f"[{self.name}] Capture შეცდომა: {e}")
                time.sleep(0.1)

        if cap is not None:
            cap.release()
            log.info(f"[{self.name}] კამერა დახურულია")

    def detect_loop(self):
        while running[0]:
            try:
                if not is_detection_enabled():
                    time.sleep(0.05)
                    continue

                with self.frame_lock:
                    frame = None if self.detect_frame is None else self.detect_frame.copy()
                    current_seq = self.frame_seq

                if frame is None:
                    time.sleep(0.01)
                    continue

                if current_seq == self.detect_seq:
                    time.sleep(0.005)
                    continue

                self.detect_seq = current_seq

                if DETECTION_EVERY_N_FRAME > 1 and current_seq % DETECTION_EVERY_N_FRAME != 0:
                    continue

                results = self.model(
                    frame,
                    conf=config.OBJECT_MIN_CONFIDENCE_1,
                    imgsz=640,
                    verbose=False
                )[0]

                detected_objects = []
                for box in results.boxes:
                    conf = float(box.conf.item())
                    if conf < config.OBJECT_MIN_CONFIDENCE_1:
                        continue

                    bx1, by1, bx2, by2 = map(int, box.xyxy[0])
                    detected_objects.append((bx1, by1, bx2, by2, conf))

                with self.data_lock:
                    self.last_boxes = detected_objects
                    self.last_detected_frame = frame.copy()

                time.sleep(0.001)

            except Exception as e:
                log.error(f"[{self.name}] Detection შეცდომა: {e}")
                time.sleep(0.1)


def reset_all():
    """ბოქსების და მთვლელის გასუფთავება"""
    for cam in cameras:
        with cam.data_lock:
            cam.last_boxes = []
            cam.last_detected_frame = None
    wagon_counter.reset()


# ==================== HLS სტრიმინგი ====================
def log_ffmpeg_stderr(proc):
    try:
        for line in iter(proc.stderr.readline, b""):
            if not line:
                break
            log.error(f"FFmpeg HLS: {line.decode(errors='ignore').strip()}")
    except Exception as e:
        log.error(f"FFmpeg stderr წაკითხვის შეცდომა: {e}")


def stream_to_hls():
    hls_playlist_path = os.path.join(config.HLS_DIR, HLS_PLAYLIST_NAME)

    command = [
        "ffmpeg", "-loglevel", "error", "-y", "-re",
        "-fflags", "genpts+discardcorrupt",
        "-flags", "low_delay",
        "-thread_queue_size", "512",
        "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", "1280x720", "-r", "15", "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-profile:v", "main", "-level", "4.0", "-pix_fmt", "yuv420p",
        "-bf", "0",
        "-g", "30", "-keyint_min", "15",
        "-sc_threshold", "0",
        "-b:v", "2800k", "-maxrate", "2800k", "-bufsize", "5600k",
        "-x264opts", "no-scenecut=1:force-cfr=1",
        "-threads", "1",
        "-f", "hls",
        "-hls_time", "1",
        "-hls_list_size", "2",
        "-hls_flags", "delete_segments+program_date_time+split_by_time",
        "-hls_delete_threshold", "3",
        "-hls_segment_type", "mpegts",
        "-strftime", "1",
        "-hls_segment_filename", os.path.join(config.HLS_DIR, "seg_%Y%m%d_%H%M%S.ts"),
        hls_playlist_path
    ]

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    Thread(target=log_ffmpeg_stderr, args=(proc,), daemon=True).start()

    while running[0]:
        try:
            if not cameras:
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
                det_enabled = is_detection_enabled()

                if det_enabled:
                    with cam.data_lock:
                        detected_frame = None if cam.last_detected_frame is None else cam.last_detected_frame.copy()
                        current_boxes = list(cam.last_boxes)

                    if detected_frame is not None:
                        frame = detected_frame
                    else:
                        with cam.frame_lock:
                            frame = None if cam.latest_frame is None else cam.latest_frame.copy()
                else:
                    with cam.frame_lock:
                        frame = None if cam.latest_frame is None else cam.latest_frame.copy()
                    current_boxes = []

                if frame is None:
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
                    display_frame = cv2.resize(frame, (1280, 720))

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
                        large_boxes = []
                        h_orig, w_orig = frame.shape[:2]

                        for bx1, by1, bx2, by2, conf in current_boxes:
                            gx1 = int(bx1 * 1280 / w_orig)
                            gy1 = int(by1 * 720 / h_orig)
                            gx2 = int(bx2 * 1280 / w_orig)
                            gy2 = int(by2 * 720 / h_orig)

                            width = gx2 - gx1
                            height = gy2 - gy1

                            is_large_enough = (
                                width >= config.OBJECT_MIN_WIDTH_1
                                and height >= config.OBJECT_MIN_HEIGHT_1
                            )

                            if is_large_enough:
                                large_boxes.append((bx1, by1, bx2, by2, conf))
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

                        # სურათი შეინახე მხოლოდ მაშინ, როცა არსებობს მწვანე box
                        if current_wagon_number > 0 and len(large_boxes) > 0:
                            bx1, by1, bx2, by2, conf = large_boxes[0]
                            image_saver.save_crop(
                                frame,
                                bx1,
                                by1,
                                bx2,
                                by2,
                                f"{current_wagon_number}_sector",
                                conf
                            )

            if proc.stdin is None:
                log.error("FFmpeg stdin მიუწვდომელია")
                break

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

    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass

    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

    log.info("HLS სტრიმინგი გაჩერდა")


# ==================== MAIN ====================
def stop_running(signum, frame):
    running[0] = False


def main():
    signal.signal(signal.SIGINT, stop_running)
    signal.signal(signal.SIGTERM, stop_running)

    log.info("=== WAGON TRACKER v15.9 (პაკეტი aw_7) STARTED ===")
    log.info("WagonCounter და ImageSaver ინტეგრირებულია")

    log.info("HLS სერვერის გაშვება...")
    start_hls_server()
    log.info("HLS სერვერი გაშვებულია: http://localhost:9091")

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
            config.TCP_SERVER_IP,
            config.TCP_SERVER_PORT,
            RECONNECT_DELAY,
            running
        ),
        daemon=True,
        name="TCP-CLIENT"
    ).start()

    Thread(target=stream_to_hls, daemon=True, name="HLS-STREAM").start()

    log.info("სისტემა მზადაა! TCP: START / STOP")
    while running[0]:
        time.sleep(1)

    log.info("=== სისტემა გაჩერდა ===")


if __name__ == "__main__":
    main()

import socket
import time
import json
import logging
from datetime import datetime

log = logging.getLogger("WAGON_TRACKER")

from .videorecorder import start_recording, stop_recording
from .image_saver import ImageSaver


image_saver = ImageSaver("number_sectors", clear_on_start=False)


def tcp_client(detection_enabled, detection_lock, reset_all_func, cameras, unique_json_path,
               tcp_ip, tcp_port, reconnect_delay, running):
    tcp_socket = None

    while running[0]:
        try:
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_socket.connect((tcp_ip, tcp_port))
            log.info(f"TCP დაკავშირებული: {tcp_ip}:{tcp_port}")

            while running[0]:
                data = tcp_socket.recv(1024)
                if not data:
                    break

                cmd = data.decode("utf-8").strip().upper()

                if cmd == "START":
                    with detection_lock:
                        detection_enabled[0] = True

                    reset_all_func()
                    image_saver.clear_directory()

                    if cameras and cameras[0].latest_frame is not None:
                        start_recording(cameras[0].latest_frame)

                    log.info(">>> DETECTION STARTED <<<")

                elif cmd == "STOP":
                    with detection_lock:
                        detection_enabled[0] = False

                    handle_stop(
                        detection_enabled,
                        detection_lock,
                        reset_all_func,
                        cameras,
                        unique_json_path,
                        tcp_socket
                    )

        except Exception as e:
            log.error(f"TCP გაწყდა: {e}")
            if tcp_socket:
                tcp_socket.close()
            tcp_socket = None
            time.sleep(reconnect_delay)


def handle_stop(detection_enabled, detection_lock, reset_all_func, cameras, unique_json_path, tcp_socket):
    stop_recording()
    log.info(">>> DETECTION STOPPED <<<")

    detection_data = []
    for cam in cameras:
        with cam.data_lock:
            entry = {
                "camera": cam.name,
                "boxes_count": len(cam.last_boxes),
                "timestamp": datetime.now().isoformat()
            }
            detection_data.append(entry)

    if detection_data:
        try:
            with open(unique_json_path, "w", encoding="utf-8") as f:
                json.dump(detection_data, f, ensure_ascii=False, indent=2)
            log.info(f"JSON შენახული: {len(detection_data)}")
        except Exception as e:
            log.error(f"JSON შეცდომა: {e}")

        if tcp_socket and tcp_socket.fileno() != -1:
            try:
                msg = json.dumps(detection_data, ensure_ascii=False) + "\n"
                tcp_socket.sendall(msg.encode("utf-8"))
                log.info("TCP: გაიგზავნა")
            except Exception as e:
                log.error(f"TCP გაგზავნა: {e}")

    reset_all_func()

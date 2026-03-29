import socket
import time
import logging
from pathlib import Path
from.config_loader import config
log = logging.getLogger("WAGON_TRACKER")

from .videorecorder import start_recording, stop_recording


def tcp_client(tcp_identifier, detection_enabled, detection_lock, reset_all_func, cameras,
               tcp_ip, tcp_port, reconnect_delay, running):
    """
    TCP კლიენტი, რომელიც ღებულობს ბრძანებებს ფორმატით:
        <tcp_identifier>_START/ID=some_id
        <tcp_identifier>_STOP/ID=some_id
    """
    tcp_socket = None

    while running[0]:
        try:
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_socket.connect((tcp_ip, tcp_port))
            log.info(f"TCP დაკავშირებული: {tcp_ip}:{tcp_port}")

            while running[0]:
                data = tcp_socket.recv(1024)
                if not data:
                    log.info("TCP კავშირი დაიხურა სერვერის მხრიდან")
                    break

                cmd = data.decode("utf-8", errors="replace").strip().upper()

                # START
                if cmd.startswith(tcp_identifier + "_START/ID="):
                    try:
                        train_id = cmd.split("/ID=", 1)[1].strip()
                        log.info(f"START მიღებული → ID = {train_id}")

                        with detection_lock:
                            detection_enabled[0] = True

                        reset_all_func()

                        if cameras and cameras[0].latest_frame is not None:
                            # თუ გინდა ID ჩაიწეროს ფაილის სახელში → videorecorder-ში უნდა იყოს მხარდაჭერა
                            # აქ უბრალოდ ვიწყებთ ჩაწერას (შეცვალე საჭიროებისამებრ)
                            start_recording(cameras[0].latest_frame, f"1_{train_id}")



                        folder = Path(config.SAVE_IMAGES_DIR)
                        for file in folder.glob("*.png"):
                            file.unlink()

                            

                        log.info(">>> DETECTION STARTED <<<")

                    except Exception:
                        log.warning(f"არასწორი START ფორმატი: {cmd}")

                # STOP
                elif cmd.startswith(tcp_identifier + "_STOP/ID="):
                    try:
                        train_id = cmd.split("/ID=", 1)[1].strip()
                        log.info(f"STOP მიღებული → ID = {train_id}")

                        with detection_lock:
                            detection_enabled[0] = False

                        stop_recording()
                        log.info(">>> DETECTION STOPPED <<<")

                        reset_all_func()

                    except Exception:
                        log.warning(f"არასწორი STOP ფორმატი: {cmd}")

                else:
                    log.debug(f"უცნობი ბრძანება: {cmd!r}")

        except Exception as e:
            log.error(f"TCP კავშირის შეცდომა: {e}", exc_info=True)
            if tcp_socket:
                try:
                    tcp_socket.close()
                except:
                    pass
            tcp_socket = None
            time.sleep(reconnect_delay)

        finally:
            if tcp_socket:
                try:
                    tcp_socket.close()
                except:
                    pass
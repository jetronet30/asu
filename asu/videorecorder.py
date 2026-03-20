import subprocess
from datetime import datetime
from pathlib import Path
import logging

log = logging.getLogger("WAGON_TRACKER")

archive_dir = Path("videoarchive")
archive_dir.mkdir(exist_ok=True)

video_writer = None
video_start_time = None


def start_recording(frame,name):
    global video_writer, video_start_time
    if frame is None or frame.size == 0:
        log.error("❌ ფრეიმი ცარიელია – ჩაწერა ვერ დაიწყო")
        return

    h, w = frame.shape[:2]

    video_path = archive_dir / f"{name}.mp4"

    cmd = [
        'ffmpeg', '-loglevel', 'error', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f"{w}x{h}", '-r', '20.0', '-i', '-',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '32',
        '-b:v', '1500k', '-maxrate', '2000k', '-bufsize', '3000k',
        '-profile:v', 'high', '-level', '4.0', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', '-avoid_negative_ts', 'make_zero',
        str(video_path)
    ]

    video_writer = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    video_start_time = datetime.now()
    log.info(f"🎥 ჩაწერა დაიწყო → {video_path}")


def stop_recording():
    global video_writer, video_start_time
    if video_writer is not None:
        try:
            if hasattr(video_writer, 'stdin'):
                video_writer.stdin.close()
                video_writer.wait()
        except Exception as e:
            log.error(f"ვიდეოს დასრულება: {e}")
        finally:
            video_writer = None
            video_start_time = None
    log.info("🎥 ჩაწერა გაჩერდა")
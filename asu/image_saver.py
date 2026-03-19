import cv2
import os
import shutil
from datetime import datetime


class ImageSaver:
    def __init__(self, save_dir="number_sectors", clear_on_start=True):
        self.save_dir = save_dir
        if clear_on_start:
            self.clear_directory()
        else:
            os.makedirs(self.save_dir, exist_ok=True)

    def clear_directory(self):
        """ფოლდერის გასუფთავება და თავიდან შექმნა"""
        if os.path.exists(self.save_dir):
            print(f"იშლება ძველი ფოლდერი: {self.save_dir}")
            shutil.rmtree(self.save_dir)

        os.makedirs(self.save_dir, exist_ok=True)
        print(f"შეიქმნა ახალი ფოლდერი: {self.save_dir}")

    def save_crop(self, frame, x1, y1, x2, y2, name, confidence):
        """ინახავს ობიექტის crop-ს"""
        h, w = frame.shape[:2]

        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(0, min(x2, w))
        y2 = max(0, min(y2, h))

        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{self.save_dir}/{name}_{timestamp}_{confidence:.2f}.png"
        cv2.imwrite(filename, crop)

        return filename

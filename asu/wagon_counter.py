class WagonCounter:
    """ვაგონების რიგობრივი ნომრების მმართველი კლასი"""

    def __init__(self):
        self.wagon_number = 0
        self.object_present = False
        self.no_object_frames = 0
        self.no_object_threshold = 8

    def update_detection(self, current_detected):
        """ანახლებს დეტექციის სტატუსს და აბრუნებს მიმდინარე ნომერს"""
        current_number = self.wagon_number

        if not self.object_present and current_detected:
            self.wagon_number += 1
            current_number = self.wagon_number
            print(f"ახალი ვაგონი #{self.wagon_number} შემოვიდა")

        if current_detected:
            self.object_present = True
            self.no_object_frames = 0
        else:
            self.no_object_frames += 1
            if self.no_object_frames >= self.no_object_threshold:
                self.object_present = False

        return current_number

    def reset(self):
        """ნულოვდებს ყველა მნიშვნელობას"""
        self.wagon_number = 0
        self.object_present = False
        self.no_object_frames = 0
        print("ვაგონების მთვლელი განულდა")

    def get_current_number(self):
        """აბრუნებს მიმდინარე ვაგონის ნომერს"""
        return self.wagon_number

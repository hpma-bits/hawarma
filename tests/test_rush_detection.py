"""
Unit test for rush order pixel-based detection

Position: Tests the _detect_rush_order method using testset images
          Verifies that rush orders (lower R value) are correctly identified

Input: Testset images from tests/testset/
Output: Test results showing detection accuracy

NOTE: Once file content is updated, must update the header comment accordingly
"""

import cv2
import unittest
from pathlib import Path


RUSH_DETECTION_POSITIONS = [
    (480, 195),
    (860, 195),
    (1230, 195),
    (1600, 195),
]
RUSH_RED_THRESHOLD = 180


def detect_rush_order(slot: int, screen: cv2.Mat) -> bool:
    """Simulates the rush detection logic from DetectionService"""
    if slot >= len(RUSH_DETECTION_POSITIONS):
        return False
    
    x, y = RUSH_DETECTION_POSITIONS[slot]
    h, w = screen.shape[:2]
    
    if 0 <= y < h and 0 <= x < w:
        red_value = int(screen[y, x, 2])
        return red_value < RUSH_RED_THRESHOLD
    
    return False


class TestRushDetection(unittest.TestCase):
    """Test cases for rush order detection using pixel color"""
    
    @classmethod
    def setUpClass(cls):
        cls.testset_dir = Path(__file__).parent / "testset"
    
    def test_order0_rush(self):
        """Test slot 0 rush order"""
        img = cv2.imread(str(self.testset_dir / "order0-2-12-rush.jpg"))
        self.assertTrue(detect_rush_order(0, img))
    
    def test_order0_normal(self):
        """Test slot 0 normal order"""
        img = cv2.imread(str(self.testset_dir / "order0-0-01-normal.jpg"))
        self.assertFalse(detect_rush_order(0, img))
    
    def test_order2_rush(self):
        """Test slot 2 rush order"""
        img = cv2.imread(str(self.testset_dir / "order2-2-11-rush.jpg"))
        self.assertTrue(detect_rush_order(2, img))
    
    def test_order2_normal(self):
        """Test slot 2 normal order"""
        img = cv2.imread(str(self.testset_dir / "order2-1-11-normal.jpg"))
        self.assertFalse(detect_rush_order(2, img))
    
    def test_all_testset_images(self):
        """Test all images in testset"""
        test_images = sorted(self.testset_dir.glob("order*.jpg"))
        
        correct = 0
        total = 0
        failures = []
        
        for img_path in test_images:
            parts = img_path.stem.split("-")
            slot = int(parts[0].replace("order", ""))
            if slot > 3:
                continue
            
            img = cv2.imread(str(img_path))
            is_actual_rush = "rush" in img_path.name.lower()
            is_detected_rush = detect_rush_order(slot, img)
            
            if is_detected_rush == is_actual_rush:
                correct += 1
            else:
                failures.append((img_path.name, is_detected_rush, is_actual_rush))
            total += 1
        
        print(f"\nAccuracy: {correct}/{total} = {correct/total*100:.1f}%")
        if failures:
            print("Failures:")
            for name, detected, actual in failures:
                print(f"  {name}: detected={detected}, actual={actual}")
        
        self.assertEqual(correct, total, f"Failed {len(failures)} tests")


if __name__ == "__main__":
    unittest.main()
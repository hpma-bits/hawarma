import unittest
from airtest.core.api import init_device, G
import timeit


class TestCaptureSpeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load test images once for all tests."""
        cls.device = init_device(
            platform="Android",
            uuid="127.0.0.1:16384",  # mumu
            cap_method="minicap",
            touch_method="adbtouch",
        )

    def _capture_once(self):
        """Capture a single screenshot."""
        return self.device.snapshot()

    def test_detection_speed(self):
        """
        Measures the average time to run caputure once.
        """
        count = 100
        total_time = timeit.timeit(self._capture_once, number=count)
        avg_time = total_time / count
        print(f"Average capture time over {count} runs: {avg_time:.4f} seconds")
        # Add a basic assertion to ensure the test runs and returns a value
        self.assertGreater(avg_time, 0)


if __name__ == "__main__":
    unittest.main()

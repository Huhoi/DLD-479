import subprocess
import threading
import time
import random
import signal
import sys
from typing import Optional

class ProcessManager:
    def __init__(self):
        self.droidbot_process: Optional[subprocess.Popen] = None
        self.rotation_process: Optional[subprocess.Popen] = None
        self.should_stop = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        self.should_stop = True
        self.cleanup()

    def run_droidbot(self):
        """Run DroidBot in a subprocess"""
        cmd = [
            "droidbot",
            "-a", "droidbot/APK/Amaze_File_Manager_v3.1.0-beta.1.apk",
            "-o", "droidbot/output",
            "-keep_env"
        ]
        self.droidbot_process = subprocess.Popen(cmd)
        self.droidbot_process.wait()

    def run_rotation(self):
        """Run continuous rotation in a subprocess"""
        while not self.should_stop:
            try:
                orientation = random.choice(["portrait", "landscape"])
                print(f"Rotating to {orientation}...")
                subprocess.run(
                    ["adb", "emu", "rotate", orientation],
                    check=True,
                    timeout=5
                )
                sleep_time = random.uniform(3, 8)
                end_time = time.time() + sleep_time
                while time.time() < end_time and not self.should_stop:
                    time.sleep(0.1)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                print(f"Rotation error: {e}")
                time.sleep(2)
            except KeyboardInterrupt:
                break

    def cleanup(self):
        """Clean up processes"""
        print("\nCleaning up processes...")
        if self.droidbot_process and self.droidbot_process.poll() is None:
            self.droidbot_process.terminate()
            try:
                self.droidbot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.droidbot_process.kill()
        
        # Reset to portrait
        subprocess.run(["adb", "emu", "rotate", "portrait"], timeout=5)

    def run(self):
        """Main execution"""
        print("Starting DroidBot with rotation...")
        print("Press Ctrl+C to stop")

        # Start DroidBot in a thread
        droidbot_thread = threading.Thread(target=self.run_droidbot)
        droidbot_thread.daemon = True
        droidbot_thread.start()

        # Run rotation in main thread (better signal handling)
        try:
            self.run_rotation()
        finally:
            self.cleanup()
            droidbot_thread.join(timeout=5)

if __name__ == "__main__":
    manager = ProcessManager()
    manager.run()
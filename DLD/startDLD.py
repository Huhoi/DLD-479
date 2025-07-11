import subprocess
import threading
import time
import random
import signal
import sys
import argparse
import os
from typing import Optional

class ProcessManager:
    def __init__(self, apk_path: str, output_dir: str = None, rotate: bool = True):
        self.apk_path = apk_path
        # Set default output directory to 'output/apk_filename' without extension
        apk_name = os.path.splitext(os.path.basename(apk_path))[0]
        self.output_dir = output_dir if output_dir else os.path.join("output", apk_name)
        self.rotate = rotate
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
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        cmd = [
            "droidbot",
            "-a", self.apk_path,
            "-o", self.output_dir
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
        
        if self.rotate:
            # Reset to portrait if rotation was enabled
            subprocess.run(["adb", "emu", "rotate", "portrait"], timeout=5)

    def run(self):
        """Main execution"""
        print(f"Starting DroidBot for APK: {self.apk_path}")
        print(f"Output directory: {self.output_dir}")
        if self.rotate:
            print("With random screen rotation enabled")
        else:
            print("With screen rotation disabled")
        print("Press Ctrl+C to stop")

        # Start DroidBot in a thread
        droidbot_thread = threading.Thread(target=self.run_droidbot)
        droidbot_thread.daemon = True
        droidbot_thread.start()

        # Run rotation in main thread if enabled
        try:
            if self.rotate:
                self.run_rotation()
            else:
                while droidbot_thread.is_alive() and not self.should_stop:
                    time.sleep(0.5)
        finally:
            self.cleanup()
            droidbot_thread.join(timeout=5)

def parse_args():
    parser = argparse.ArgumentParser(description='Run DroidBot with optional screen rotations.')
    parser.add_argument('apk_path', help='Path to the APK file to test')
    parser.add_argument('-o', '--output', default=None, 
                       help='Custom output directory (defaults to "output/apk_filename")')
    parser.add_argument('--no-rotate', action='store_false', dest='rotate', 
                       help='Disable random screen rotations')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    manager = ProcessManager(
        apk_path=args.apk_path,
        output_dir=args.output,
        rotate=args.rotate
    )
    manager.run()
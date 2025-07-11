import subprocess
import threading
import time
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
        """Run rotation using rotate.py script"""
        cmd = ["python", "rotate.py"]
        self.rotation_process = subprocess.Popen(cmd)
        self.rotation_process.wait()

    def cleanup(self):
        """Clean up processes"""
        print("\nCleaning up processes...")
        if self.droidbot_process and self.droidbot_process.poll() is None:
            self.droidbot_process.terminate()
            try:
                self.droidbot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.droidbot_process.kill()
        
        if self.rotation_process and self.rotation_process.poll() is None:
            self.rotation_process.terminate()
            try:
                self.rotation_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.rotation_process.kill()
        
        # Reset to portrait if rotation was enabled
        if self.rotate:
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

        # Start rotation in a separate process if enabled
        rotation_thread = None
        if self.rotate:
            rotation_thread = threading.Thread(target=self.run_rotation)
            rotation_thread.daemon = True
            rotation_thread.start()

        try:
            while droidbot_thread.is_alive() and not self.should_stop:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.should_stop = True
        finally:
            self.cleanup()
            droidbot_thread.join(timeout=5)
            if rotation_thread:
                rotation_thread.join(timeout=5)

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
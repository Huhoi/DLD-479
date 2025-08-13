import subprocess
import threading
import time
import argparse
import os
import shutil
from typing import Optional
import glob
import logging
from datetime import datetime
from droidbot.app import App
from droidbot.device import Device
from droidbot.input_event import KeyEvent
from dataloss import EnhancedDataLossDetector


class ProcessManager:
    def __init__(self, apk_path: str, output_dir: str = None, rotate: bool = True, power_cycle: bool = True, home_button: bool = False, timeout: int = 300):
        self.apk_path = apk_path
        apk_name = os.path.splitext(os.path.basename(apk_path))[0]
        self.output_dir = output_dir if output_dir else os.path.join("output", apk_name)
        self.rotate = rotate
        self.power_cycle = power_cycle
        self.timeout = timeout
        self.droidbot_process: Optional[subprocess.Popen] = None
        self.rotation_process: Optional[subprocess.Popen] = None
        self.data_loss_detector = None
        self.should_stop = False
        self.start_time = 0
        self.home_button = home_button

    def run_droidbot(self):
        """Run DroidBot in a subprocess"""
        os.makedirs(self.output_dir, exist_ok=True)
        
        cmd = [
            "droidbot",
            "-a", self.apk_path,
            "-o", self.output_dir,
            "-timeout", str(self.timeout)
        ]
        
        self.droidbot_process = subprocess.Popen(cmd)
        self.droidbot_process.wait()

    def run_rotation(self):
        """Run rotation using rotate.py script"""
        cmd = ["python", "DLD/rotate.py", self.output_dir]
        self.rotation_process = subprocess.Popen(cmd)
        self.rotation_process.wait()
        
    def run_home_button_sim(self):
        cmd = [
            "python", "DLD/home_button.py", 
            self.output_dir,]
        self.home_button_process = subprocess.Popen(cmd)
    
    def run_power_cycle(self):
        """Run power cycle simulation"""
        cmd = ["python", "DLD/power_cycle.py", self.output_dir]
        self.power_cycle_process = subprocess.Popen(cmd)
    

    def run_data_loss_detector(self):
        """Run the enhanced data loss detector"""
        # Initialize device and app objects
        device = Device(
            device_serial=None,
            output_dir=self.output_dir,
            grant_perm=True,
            enable_accessibility_hard=True,
            ignore_ad=True
        )
        
        app = App(self.apk_path)
        
        # Start data loss detector
        self.data_loss_detector = EnhancedDataLossDetector(
            device=device,
            app=app,
            output_dir=self.output_dir,
            interval=30  # Test every 30 seconds
        )
        self.data_loss_detector.start()

    def run_crash_analysis(self):
        """Run crash analysis after DroidBot finishes"""
        print("\nRunning crash analysis...")
        crash_script = os.path.join(os.path.dirname(__file__), "crash.py")
        if os.path.exists(crash_script):
            subprocess.run(["python", crash_script, self.output_dir])
        else:
            print(f"Warning: Crash analysis script not found at {crash_script}")

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
        
        if self.data_loss_detector:
            self.data_loss_detector.stop()
        
        # Reset to portrait if rotation was enabled
        if self.rotate:
            subprocess.run(["adb", "emu", "rotate", "portrait"], timeout=5)

    
    def run(self):
        """Main execution"""
        print(f"\n{'='*50}")
        print(f"Starting DroidBot for APK: {self.apk_path}")
        print(f"Output directory: {self.output_dir}")
        print(f"Timeout: {self.timeout} seconds")
        if self.rotate:
            print("With random screen rotation enabled")
        else:
            print("With screen rotation disabled")
        print("With enhanced data loss detection enabled")
        print("Press Ctrl+C to stop early")
        print(f"{'='*50}\n")

        self.start_time = time.time()

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

        # Start data loss detector
        data_loss_thread = threading.Thread(target=self.run_data_loss_detector)
        data_loss_thread.daemon = True
        data_loss_thread.start()


        # Start power cycle simulation if enabled
        power_cycle_thread = None
        if self.power_cycle:
            power_cycle_thread = threading.Thread(target=self.run_power_cycle)
            power_cycle_thread.daemon = True
            power_cycle_thread.start()
        
        home_button_thread = None
        if self.home_button:
            home_button_thread = threading.Thread(target=self.run_home_button_sim)
            home_button_thread.daemon = True
            home_button_thread.start()
            
        try:
            while droidbot_thread.is_alive() and not self.should_stop:
                elapsed = time.time() - self.start_time
                if elapsed > self.timeout:
                    print(f"\nTimeout reached ({self.timeout} seconds), stopping...")
                    self.should_stop = True
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.should_stop = True
        finally:
            self.cleanup()
            droidbot_thread.join(timeout=5)
            if rotation_thread:
                rotation_thread.join(timeout=5)
            if power_cycle_thread:
                power_cycle_thread.join(timeout=5)
            if home_button_thread:
                home_button_thread.join(timeout=5)
            if data_loss_thread:
                data_loss_thread.join(timeout=5)
            
            # Run crash analysis after cleanup
            self.run_crash_analysis()
            
        

def process_apk(apk_path: str, output_dir: str = None, rotate: bool = True, timeout: int = 300):
    """Process a single APK file"""
    manager = ProcessManager(
        apk_path=apk_path,
        output_dir=output_dir,
        rotate=rotate,
        timeout=timeout
    )
    manager.run()

def process_all_apks(apk_dir: str, output_parent_dir: str = "output", rotate: bool = True, timeout: int = 120):
    """Process all APK files in a directory"""
    apk_files = glob.glob(os.path.join(apk_dir, "*.apk"))
    
    if not apk_files:
        print(f"No APK files found in {apk_dir}")
        return
    
    print(f"Found {len(apk_files)} APK files to process")
    
    for apk_path in apk_files:
        process_apk(
            apk_path=apk_path,
            output_dir=os.path.join(output_parent_dir, os.path.splitext(os.path.basename(apk_path))[0]),
            rotate=rotate,
            timeout=timeout
        )

def parse_args():
    parser = argparse.ArgumentParser(
        description='Run DroidBot with optional screen rotations and data loss detection.',
        formatter_class=argparse.RawTextHelpFormatter  # Preserves formatting
    )
    parser.add_argument(
        '--apk-path', 
        default=None,
        help='Path to a specific APK file to test\n'
             '(default: process all in DLD/APK)'
    )
    parser.add_argument(
        '--apk-dir', 
        default="DLD/APK",
        help='Directory containing APKs to test\n'
             '(default: DLD/APK)'
    )
    parser.add_argument(
        '-o', '--output', 
        default="output",
        help='Parent output directory\n'
             '(default: "output")'
    )
    parser.add_argument(
        '--no-rotate', 
        action='store_false', 
        dest='rotate',
        help='Disable random screen rotations'
    )
    parser.add_argument(
        '-t', '--timeout', 
        type=int, 
        default=300,
        help='Timeout in seconds for each APK\n'
             '(default: 120)'
    )
    parser.add_argument(
        '--no-power-cycle', 
        action='store_false', 
        dest='power_cycle',
        help='Disable power cycle simulation'
    )
    parser.add_argument(
        '--max-home-actions', 
        type=int, 
        default=20,
        help='Maximum home button actions per test session'
    )
    return parser.parse_args()

def cleanDirectory(apk_path = None):
    dir_output = "output\\"
    folder_names = ["data_loss_events", 
                    "data_loss_logs", 
                    "data_loss_states",
                    "events",
                    "states",
                    "temp",
                    "views"]
    if not os.path.exists("output"):
        os.makedirs("output",exist_ok=True)
    if(apk_path):
        copy_apk = apk_path
        new_apk_path = copy_apk.split('\\')
        apk_file_name = new_apk_path[2].strip(".apk")
        for folder in folder_names:
            folder_output = dir_output + apk_file_name + '\\' + folder
            if os.path.exists(folder_output):
                shutil.rmtree(folder_output)
        
            os.makedirs(folder_output, exist_ok=True)
    else:
        pass
 
if __name__ == "__main__":
    
    args = parse_args()
    cleanDirectory(args.apk_path)
    if args.apk_path:
        # Process single APK
        process_apk(
            apk_path=args.apk_path,
            output_dir=None,  # Will use default subdirectory under args.output
            rotate=args.rotate,
            timeout=args.timeout
        )
    else:
        # Process all APKs in directory
        process_all_apks(
            apk_dir=args.apk_dir,
            output_parent_dir=args.output,
            rotate=args.rotate,
            timeout=args.timeout
        )
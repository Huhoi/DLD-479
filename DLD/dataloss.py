import os
import time
import json
import logging
from datetime import datetime
from droidbot.device import Device
from droidbot.app import App
from typing import Dict, Any, Optional, List
import cv2
import numpy as np
from PIL import Image
import io
import subprocess

class EnhancedDataLossDetector:
    def __init__(self, device: Device, app: App, output_dir: str, interval: int = 30):
        self.device = device
        self.app = app
        self.output_dir = output_dir
        self.interval = interval
        self.running = False
        self.last_state = None
        self.current_state = None
        self.test_count = 0
        self.data_loss_count = 0
        self.max_retries = 3
        self.retry_delay = 2
        
        try:
            self._setup_directories()
            self.logger = self._setup_logger()
            self.logger.info(f"Data Loss Detector initialized for {app.app_name}")
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger('EnhancedDataLossDetector_Fallback')
            self.logger.error(f"Initialization error: {str(e)}")

    def _setup_directories(self):
        """Create required output directories"""
        dirs = ["data_loss_logs", "data_loss_states", "data_loss_events"]
        for dir_name in dirs:
            os.makedirs(os.path.join(self.output_dir, dir_name), exist_ok=True)

    def _setup_logger(self) -> logging.Logger:
        """Configure logging system"""
        logger = logging.getLogger('EnhancedDataLossDetector')
        logger.setLevel(logging.INFO)
        
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            
        log_file = os.path.join(self.output_dir, "data_loss_logs", "detector.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(file_handler)
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
        logger.addHandler(console_handler)
        
        return logger

    def _take_screenshot(self, file_path: str) -> bool:
        """Capture screenshot using multiple methods"""
        methods = [
            self._screenshot_method_adb_exec,
            self._screenshot_method_adb_pull,
            self._screenshot_method_droidbot
        ]
        
        for attempt in range(self.max_retries):
            for method in methods:
                try:
                    if method(file_path):
                        return True
                except Exception as e:
                    self.logger.warning(f"Screenshot attempt {attempt+1} failed: {str(e)}")
                    time.sleep(self.retry_delay)
                    
        self.logger.error("All screenshot methods failed")
        return False

    def _screenshot_method_adb_exec(self, file_path: str) -> bool:
        """Method 1: Direct ADB exec-out"""
        with open(file_path, 'wb') as f:
            result = subprocess.run(
                ["adb", "-s", self.device.serial, "exec-out", "screencap", "-p"],
                stdout=f,
                stderr=subprocess.PIPE,
                timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode())
        return os.path.exists(file_path)

    def _screenshot_method_adb_pull(self, file_path: str) -> bool:
        """Method 2: ADB screencap + pull"""
        temp_file = f"/sdcard/screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        
        subprocess.run(
            ["adb", "-s", self.device.serial, "shell", "screencap", "-p", temp_file],
            check=True,
            timeout=10
        )
        
        subprocess.run(
            ["adb", "-s", self.device.serial, "pull", temp_file, file_path],
            check=True,
            timeout=10
        )
        
        subprocess.run(
            ["adb", "-s", self.device.serial, "shell", "rm", temp_file],
            timeout=5
        )
        
        return os.path.exists(file_path)

    def _screenshot_method_droidbot(self, file_path: str) -> bool:
        """Method 3: Droidbot's built-in method"""
        screenshot_data = self.device.take_screenshot()
        if not screenshot_data:
            raise RuntimeError("No screenshot data returned")
            
        with Image.open(io.BytesIO(screenshot_data)) as img:
            img.save(file_path, format='PNG')
        return True

    def _get_current_state(self) -> Optional[Dict[str, Any]]:
        """Capture current device state with error handling"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            state = self.device.get_current_state()
            
            if state is None:
                self.logger.warning("Failed to get device state")
                return None
                
            screenshot_path = os.path.join(
                self.output_dir, 
                "data_loss_states", 
                f"state_{timestamp}.png"
            )
            
            if not self._take_screenshot(screenshot_path):
                return None

            # Build state dictionary safely
            state_data = {
                "timestamp": timestamp,
                "screenshot": screenshot_path,
                "state_str": getattr(state, 'state_str', 'unknown'),
                "foreground_activity": getattr(state, 'foreground_activity', 'unknown'),
                "views": getattr(state, 'views', []),
                "app_package": self.app.package_name  # Use app's package name instead
            }

            return state_data
            
        except Exception as e:
            self.logger.error(f"State capture failed: {str(e)}")
            return None

    def _compare_states(self, state1: Dict[str, Any], state2: Dict[str, Any]) -> bool:
        """Compare two states for data loss"""
        try:
            # Check activity change
            current_activity = state2.get("foreground_activity", "")
            last_activity = state1.get("foreground_activity", "")
            
            if (current_activity != last_activity and 
                not current_activity.startswith(self.app.package_name)):
                self.logger.warning("Activity changed unexpectedly")
                return True
                
            # Check screenshot difference
            if self._compare_screenshots(state1["screenshot"], state2["screenshot"]):
                self.logger.warning("Visual difference detected")
                return True
                
            return False
        except Exception as e:
            self.logger.error(f"State comparison failed: {str(e)}")
            return False

    def _compare_screenshots(self, img1_path: str, img2_path: str) -> bool:
        """Compare two screenshots using OpenCV"""
        try:
            if not os.path.exists(img1_path) or not os.path.exists(img2_path):
                self.logger.warning("Screenshot files missing")
                return False
                
            img1 = cv2.imread(img1_path)
            img2 = cv2.imread(img2_path)
            
            if img1 is None or img2 is None:
                self.logger.warning("Could not read screenshot files")
                return False
                
            if img1.shape != img2.shape:
                self.logger.info("Different screenshot dimensions")
                return True
                
            # Calculate structural difference
            gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray1, gray2)
            _, threshold = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            change_percent = np.count_nonzero(threshold) / threshold.size
            
            return change_percent > 0.15  # 15% difference threshold
            
        except Exception as e:
            self.logger.error(f"Screenshot comparison failed: {str(e)}")
            return False

    def _save_incident_report(self, state_before: Dict[str, Any], state_after: Dict[str, Any]):
        """Save data loss incident with tagged screenshots"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Rename screenshots with before/after tags
            before_path = os.path.join(
                os.path.dirname(state_before["screenshot"]),
                f"{os.path.splitext(os.path.basename(state_before['screenshot']))[0]}_before.png"
            )
            after_path = os.path.join(
                os.path.dirname(state_after["screenshot"]),
                f"{os.path.splitext(os.path.basename(state_after['screenshot']))[0]}_after.png"
            )
            
            os.rename(state_before["screenshot"], before_path)
            os.rename(state_after["screenshot"], after_path)
            
            # Save metadata
            report_path = os.path.join(
                self.output_dir,
                "data_loss_events",
                f"incident_{timestamp}.json"
            )
            
            with open(report_path, 'w') as f:
                json.dump({
                    "timestamp": timestamp,
                    "before_state": {
                        "screenshot": before_path,
                        "activity": state_before.get("foreground_activity", "unknown"),
                        "state_str": state_before.get("state_str", "unknown")
                    },
                    "after_state": {
                        "screenshot": after_path,
                        "activity": state_after.get("foreground_activity", "unknown"),
                        "state_str": state_after.get("state_str", "unknown")
                    },
                    "app_package": self.app.package_name,
                    "test_count": self.test_count
                }, f, indent=2)
            
            self.logger.info(f"Saved incident report to {report_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save incident report: {str(e)}")

    def start(self):
        """Start the monitoring process"""
        self.running = True
        self.logger.info("Starting data loss monitoring")
        
        try:
            while self.running:
                start_time = time.time()
                
                # Capture current state
                self.current_state = self._get_current_state()
                if not self.current_state:
                    time.sleep(self.interval)
                    continue
                
                # Compare with previous state
                if self.last_state and self._compare_states(self.last_state, self.current_state):
                    self.data_loss_count += 1
                    self.logger.warning(f"Data loss detected! (Total: {self.data_loss_count})")
                    self._save_incident_report(self.last_state, self.current_state)
                
                # Update last state
                self.last_state = self.current_state
                self.test_count += 1
                
                # Adjust sleep time
                elapsed = time.time() - start_time
                sleep_time = max(0, self.interval - elapsed)
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            self.logger.info("Monitoring stopped by user")
        except Exception as e:
            self.logger.critical(f"Monitoring crashed: {str(e)}")
        finally:
            self.stop()

    def stop(self):
        """Clean up and generate final report"""
        self.running = False
        self._generate_final_report()
        self.logger.info("Monitoring stopped")

    def _generate_final_report(self):
        """Generate comprehensive final report"""
        report_path = os.path.join(self.output_dir, "data_loss_report.json")
        
        try:
            report_data = {
                "start_time": datetime.now().isoformat(),
                "total_checks": self.test_count,
                "data_loss_incidents": self.data_loss_count,
                "app_package": self.app.package_name,
                "device_serial": self.device.serial,
                "interval_setting": self.interval,
                "output_directory": self.output_dir
            }
            
            with open(report_path, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            self.logger.info(f"Final report saved to {report_path}")
        except Exception as e:
            self.logger.error(f"Failed to generate final report: {str(e)}")
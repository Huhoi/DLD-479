import os
import time
import json
import logging
import shutil
from datetime import datetime
from droidbot.device import Device
from droidbot.app import App
from typing import Dict, Any, Optional, List, Set
import cv2
import numpy as np
from PIL import Image
import io
import subprocess
from collections import deque
import glob

class EnhancedDataLossDetector:
    def __init__(self, device: Device, app: App, output_dir: str, interval: int = 30):
        self.device = device
        self.app = app
        self.output_dir = output_dir
        self.interval = interval
        self.running = False
        self.state_history = deque(maxlen=5)
        self.event_history = deque(maxlen=20)
        self.test_count = 0
        self.data_loss_count = 0
        self.max_retries = 3
        self.retry_delay = 2
        self.last_event_check_time = 0
        self.known_event_files: Set[str] = set()
        
        try:
            self._setup_directories()
            self.logger = self._setup_logger()
            self.logger.info(f"Enhanced Data Loss Detector initialized for {app.app_name}")
            self._load_existing_events()
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger('EnhancedDataLossDetector_Fallback')
            self.logger.error(f"Initialization error: {str(e)}")

    def _setup_directories(self):
        """Create required output directories"""
        dirs = [
            "data_loss_logs",
            "data_loss_events",
            "event_analysis",
            "states",
            "events"
        ]
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

    def _load_existing_events(self):
        """Load existing event files"""
        events_dir = os.path.join(self.output_dir, "events")
        if os.path.exists(events_dir):
            for event_file in glob.glob(os.path.join(events_dir, "*.json")):
                self.known_event_files.add(os.path.basename(event_file))

    def _get_new_events(self) -> List[Dict[str, Any]]:
        """Check for new event files"""
        events_dir = os.path.join(self.output_dir, "events")
        if not os.path.exists(events_dir):
            return []

        new_events = []
        current_files = set(os.listdir(events_dir))
        new_files = current_files - self.known_event_files

        for event_file in new_files:
            if not event_file.endswith('.json'):
                continue
                
            try:
                with open(os.path.join(events_dir, event_file), 'r') as f:
                    event_data = json.load(f)
                    event_data['file_name'] = event_file
                    new_events.append(event_data)
                self.known_event_files.add(event_file)
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"Failed to load event file {event_file}: {str(e)}")

        return new_events

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
        """ADB exec-out screenshot method"""
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
        """ADB pull screenshot method"""
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
        """Droidbot screenshot method"""
        screenshot_data = self.device.take_screenshot()
        if not screenshot_data:
            raise RuntimeError("No screenshot data returned")
            
        with Image.open(io.BytesIO(screenshot_data)) as img:
            img.save(file_path, format='PNG')
        return True

    def _get_current_state(self) -> Optional[Dict[str, Any]]:
        """Capture current device state"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            state = self.device.get_current_state()
            
            if state is None:
                self.logger.warning("Failed to get device state")
                return None
                
            screenshot_path = os.path.join(
                self.output_dir, 
                "states",
                f"state_{timestamp}.png"
            )
            
            if not self._take_screenshot(screenshot_path):
                return None

            state_data = {
                "timestamp": timestamp,
                "time": time.time(),
                "screenshot": screenshot_path,
                "state_str": getattr(state, 'state_str', 'unknown'),
                "foreground_activity": getattr(state, 'foreground_activity', 'unknown'),
                "views": getattr(state, 'views', []),
                "app_package": self.app.package_name
            }

            return state_data
            
        except Exception as e:
            self.logger.error(f"State capture failed: {str(e)}")
            return None

    def _is_rotated_version(self, img1: np.ndarray, img2: np.ndarray) -> bool:
        """Check if images are rotated versions"""
        try:
            # Check 90° rotation
            if img1.shape[0] == img2.shape[1] and img1.shape[1] == img2.shape[0]:
                rotated = cv2.rotate(img1, cv2.ROTATE_90_CLOCKWISE)
                diff = cv2.absdiff(rotated, img2)
                _, threshold = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                similarity = np.count_nonzero(threshold) / threshold.size
                if similarity < 0.05:
                    return True
                    
            # Check 180° rotation
            if img1.shape == img2.shape:
                rotated = cv2.rotate(img1, cv2.ROTATE_180)
                diff = cv2.absdiff(rotated, img2)
                _, threshold = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                similarity = np.count_nonzero(threshold) / threshold.size
                if similarity < 0.05:
                    return True
                    
            return False
        except Exception as e:
            self.logger.warning(f"Rotation check failed: {str(e)}")
            return False

    def _compare_content(self, img1: np.ndarray, img2: np.ndarray) -> bool:
        """Compare image content ignoring rotations"""
        try:
            if img1.shape != img2.shape:
                # Resize to compare content
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
                
            gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
            
            diff = cv2.absdiff(gray1, gray2)
            _, threshold = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            change_percent = np.count_nonzero(threshold) / threshold.size
            
            return change_percent > 0.15
        except Exception as e:
            self.logger.error(f"Content comparison failed: {str(e)}")
            return False

    def _compare_states(self, state1: Dict[str, Any], state2: Dict[str, Any]) -> bool:
        """Compare states while ignoring rotations"""
        try:
            # Check app foreground status
            current_activity = state2.get("foreground_activity", "")
            if not current_activity.startswith(self.app.package_name):
                self.logger.warning("App no longer in foreground")
                return True
                
            # Load screenshots
            if not os.path.exists(state1["screenshot"]) or not os.path.exists(state2["screenshot"]):
                return False
                
            img1 = cv2.imread(state1["screenshot"])
            img2 = cv2.imread(state2["screenshot"])
            
            if img1 is None or img2 is None:
                return False
                
            # Skip if only rotation changed
            if self._is_rotated_version(img1, img2):
                self.logger.info("Detected screen rotation - not data loss")
                return False
                
            # Check for actual content changes
            if self._compare_content(img1, img2):
                self.logger.warning("Significant content changes detected")
                return True
                
            return False
            
        except Exception as e:
            self.logger.error(f"State comparison failed: {str(e)}")
            return False

    def _save_incident_report(self, states: List[Dict[str, Any]]):
        """Save data loss incident report"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            incident_dir = os.path.join(self.output_dir, "data_loss_events", f"incident_{timestamp}")
            os.makedirs(incident_dir, exist_ok=True)
            
            state_files = []
            for i, state in enumerate(states):
                state_file = os.path.join(incident_dir, f"state_{i}.json")
                with open(state_file, 'w') as f:
                    json.dump(state, f, indent=2)
                state_files.append(state_file)
                
                if os.path.exists(state['screenshot']):
                    new_screenshot = os.path.join(incident_dir, f"screenshot_{i}.png")
                    shutil.copy2(state['screenshot'], new_screenshot)
                    state['screenshot'] = new_screenshot
                else:
                    state['screenshot'] = None
            
            report_path = os.path.join(incident_dir, "report.json")
            with open(report_path, 'w') as f:
                json.dump({
                    "timestamp": timestamp,
                    "states": state_files,
                    "app_package": self.app.package_name,
                    "test_count": self.test_count,
                    "data_loss_count": self.data_loss_count
                }, f, indent=2)
            
            self.logger.info(f"Saved incident report to {report_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save incident report: {str(e)}")

    def start(self):
        """Start monitoring"""
        self.running = True
        self.logger.info("Starting data loss monitoring")
        
        try:
            while self.running:
                start_time = time.time()
                
                # Check for new events
                new_events = self._get_new_events()
                for event in new_events:
                    event['time'] = time.time()
                    self.event_history.append(event)
                
                # Capture current state
                current_state = self._get_current_state()
                if current_state:
                    current_state['time'] = time.time()
                    self.state_history.append(current_state)
                    self.test_count += 1
                    
                    if len(self.state_history) > 1:
                        if self._compare_states(self.state_history[-2], current_state):
                            self.data_loss_count += 1
                            self.logger.warning(f"Data loss detected! (Total: {self.data_loss_count})")
                            self._save_incident_report(list(self.state_history))
                
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
        """Stop monitoring and generate report"""
        self.running = False
        self._generate_final_report()
        self.logger.info("Monitoring stopped")

    def _generate_final_report(self):
        """Generate final data loss report"""
        report_path = os.path.join(self.output_dir, "data_loss_report.json")
        
        try:
            incidents = []
            incident_dir = os.path.join(self.output_dir, "data_loss_events")
            if os.path.exists(incident_dir):
                for incident in os.listdir(incident_dir):
                    if incident.startswith("incident_"):
                        report_file = os.path.join(incident_dir, incident, "report.json")
                        if os.path.exists(report_file):
                            with open(report_file, 'r') as f:
                                incidents.append(json.load(f))
            
            report_data = {
                "start_time": datetime.now().isoformat(),
                "total_checks": self.test_count,
                "data_loss_incidents": self.data_loss_count,
                "incident_details": incidents,
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
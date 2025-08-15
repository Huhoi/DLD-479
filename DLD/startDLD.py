import subprocess
import threading
import time
import math
import argparse
import os
import shutil
import json
import logging
import glob
import signal
from typing import Optional
from datetime import datetime
from droidbot.app import App
from droidbot.device import Device
from droidbot.input_event import KeyEvent
from dataloss import EnhancedDataLossDetector
import re

def checkAdbPath():
    """
    Prepend <SDK>/platform-tools, <SDK>/emulator, <SDK>/cmdline-tools/latest/bin
    to PATH (for the current process) if ANDROID_SDK_ROOT/HOME is set.
    This helps both our code and 3rd-party libs (like droidbot) find adb.
    """
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not sdk:
        return
    paths = [
        os.path.join(sdk, "platform-tools"),
        os.path.join(sdk, "emulator"),
        os.path.join(sdk, "cmdline-tools", "latest", "bin"),
    ]
    existing = os.environ.get("PATH", "")
    prefix = os.pathsep.join(p for p in paths if os.path.isdir(p))
    if prefix:
        os.environ["PATH"] = prefix + os.pathsep + existing


def fixAdb() -> Optional[str]:
    cand = shutil.which("adb")
    if cand:
        return cand
    for env in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        sdk = os.environ.get(env)
        if not sdk:
            continue
        for c in (os.path.join(sdk, "platform-tools", "adb.exe"),
                  os.path.join(sdk, "platform-tools", "adb")):
            if os.path.exists(c):
                return c
    return None

def adbCheck(args, **kwargs):
    adb = fixAdb()
    if not adb:
        logger.warning("adb not found; skipping adb command: %s", " ".join(args))
        # Return a fake failed result so callers don’t crash
        return subprocess.CompletedProcess(args=[], returncode=1)
    return subprocess.run([adb] + args, **kwargs)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ProcessManager')

# List of event types that should trigger home button simulation
HOME_BUTTON_EVENTS = {
    "touch",
    "long_touch",
    "set_text",
    "spawn",
    "scroll",
    "swipe"
}

class PausableThread(threading.Thread):
    def __init__(self, target=None, name=None, daemon=False):
        # Do NOT pass target to super(); we manage calling it ourselves
        super().__init__(target=None, name=name, daemon=daemon)
        self._target_func = target
        self._pause_flag = threading.Event()
        self._resume_flag = threading.Event()
        self._pause_flag.set()   # start unpaused
        self._resume_flag.set()

    def pause(self):
        self._pause_flag.clear()

    def resume(self):
        self._pause_flag.set()
        self._resume_flag.set()

    def stop(self):
        self._resume_flag.clear()
        self._pause_flag.set()   # allow thread to exit wait()

    def run(self):
        # Wait until resumed or stop requested
        self._pause_flag.wait()
        if not self._resume_flag.is_set():
            return
        # Call the target ONCE; targets like run_droidbot() block until done
        if callable(self._target_func):
            try:
                self._target_func()
            except Exception:
                logger.exception("Error in thread target: %s", self.name)


class ProcessManager:
    def __init__(self, apk_path: str, output_dir: str = None, rotate: bool = True,
                 power_cycle: bool = True, home_button: bool = True, timeout: int = 300,
                 max_home_actions: int = 20):
        self.apk_path = apk_path
        apk_name = os.path.splitext(os.path.basename(apk_path))[0]
        self.output_dir = output_dir if output_dir else os.path.join("output", apk_name)
        self.rotate = rotate
        self.power_cycle = power_cycle
        self.timeout = timeout
        self.droidbot_process: Optional[subprocess.Popen] = None
        self.rotation_process: Optional[subprocess.Popen] = None
        self.power_cycle_process: Optional[subprocess.Popen] = None
        self.data_loss_detector = None
        self.should_stop = False
        self.start_time = 0
        self.home_button = home_button
        self.max_home_actions = max_home_actions
        self.home_action_count = 0
        self.last_home_time = 0
        self.min_home_interval = 30  # Minimum 30 seconds between home button actions
        self.seen_events = set()
        self.screenshot_dir = os.path.join(self.output_dir, "home_button_screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)

        self.crash_dir = os.path.join(self.output_dir, "crashes")
        os.makedirs(self.crash_dir, exist_ok=True)

        # Thread references
        self.droidbot_thread = None
        self.rotation_thread = None
        self.data_loss_thread = None
        self.power_cycle_thread = None

    def count_crashes(self) -> int:
        """
        Prefer the parsed count written by run_crash_analysis().
        Fallback to counting artifacts in crashes/.
        """
        # 1) If our crash summary exists, use it
        from_path = os.path.join(self.crash_dir, "crashes.json")
        try:
            if os.path.isfile(from_path):
                with open(from_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("count"), int):
                    return data["count"]
        except Exception:
            pass

        # 2) Else count textual artifacts as a loose fallback
        try:
            if os.path.isdir(self.crash_dir):
                return len([f for f in os.listdir(self.crash_dir)
                            if f.lower().endswith((".json", ".txt", ".log"))])
        except Exception:
            pass
        return 0

    def count_incidents(self) -> int:
        """
        Count data loss incidents as the number of incident folders in: output_dir>/data_loss_events/
        """
        base = os.path.join(self.output_dir, "data_loss_events")
        if not os.path.isdir(base):
            return 0

        n = 0
        with os.scandir(base) as it:
            for entry in it:
                if not entry.is_dir():
                    continue
                name_ok = entry.name.startswith("incident_")
                has_report = os.path.isfile(os.path.join(entry.path, "report.json"))
                if name_ok or has_report:
                    n += 1
        return n

    def parseUTGStats(self):
        """
        Return (num_reached_activities, app_num_total_activities) from utg.js/utg.json.
        Works with either pure JSON or a JS assignment like 'var utg = {...};'.
        Falls back to regex if JSON parsing fails. Returns (None, None) if missing.
        """
        candidates = [
            os.path.join(self.output_dir, "utg.js"),
            os.path.join(self.output_dir, "utg.json"),
        ]
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                # 1) First try strict JSON
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read().strip()

                # If it's a JS assignment, extract the {...} part
                if not txt.startswith("{"):
                    # Try to find the first '{' and the matching last '}'.
                    start = txt.find("{")
                    end = txt.rfind("}")
                    if start != -1 and end != -1 and end > start:
                        txt = txt[start:end + 1]

                data = json.loads(txt)

                nr = data.get("num_reached_activities")
                nt = data.get("app_num_total_activities")
                if isinstance(nr, int) and isinstance(nt, int):
                    return nr, nt
            except Exception:
                pass
        return None, None

    def activityCount(self, app_info: dict):
        acts = app_info.get("activities")
        if isinstance(acts, list):
            return len(acts)
        if isinstance(acts, dict):
            return len(acts.keys())
        return 0

    def print_end_summary(self):
        app_info = self.apkMetadata()
        app_label = (app_info.get("label")
                     or app_info.get("app_name")
                     or app_info.get("name")
                     or app_info.get("package")
                     or "Unknown")
        package = app_info.get("package") or "Unknown"

        incidents = self.count_incidents()
        crashes = self.count_crashes()

        reached, total = self.parseUTGStats()
        if isinstance(reached, int) and isinstance(total, int) and total > 0:
            pct = 100.0 * reached / total
            coverage_line = f"{reached}/{total} ({pct:.1f}%)"
            total_acts_line = str(total)
        else:
            total_acts = self.activityCount(app_info)
            coverage_line = "N/A"
            total_acts_line = str(total_acts)

        print("\n" + "=" * 60)
        print(f"App: {app_label} ({package})")
        print(f"# Activities (APK/UTG): {total_acts_line}")
        print(f"Activity coverage: {coverage_line}")
        print(f"Data Loss Incidents: {incidents}")
        print(f"Total Crashes: {crashes}")

    def enableAccessibility(self):
        """
        Ensure the DroidBot accessibility service is enabled.
        prevent crash if adb missing.
        """
        try:
            adbCheck(["shell", "settings", "put", "secure",
                      "enabled_accessibility_services",
                      "com.github.droidbotapp/.DroidBotAppAccessibilityService"],
                     check=False, timeout=5)
            adbCheck(["shell", "settings", "put", "secure", "accessibility_enabled", "1"],
                     check=False, timeout=5)
            adbCheck(["shell", "am", "force-stop", "com.github.droidbotapp"],
                     check=False, timeout=5)
            adbCheck(["shell", "monkey", "-p", "com.github.droidbotapp",
                      "-c", "android.intent.category.LAUNCHER", "1"],
                     check=False, timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Timed out enabling accessibility service")

    def apkMetadata(self):
        """
        Try to load app info from output/app.json (preferred), else parse the APK.
        Returns a dict including 'package', 'main_activity', 'label', and 'activities' (list) when possible.
        """
        app_json_path = os.path.join(self.output_dir, "app.json")

        # 1) Preferred: app.json from DroidBot
        if os.path.exists(app_json_path):
            try:
                with open(app_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Normalize keys we care about
                pkg = data.get("package")
                label = data.get("label") or data.get("app_name") or data.get("name")
                main_act = data.get("main_activity")
                acts = None
                # Activities can be list or dict depending on droidbot version
                for key in ("activities", "activity_list", "activities_list"):
                    if key in data:
                        if isinstance(data[key], list):
                            acts = data[key]
                        elif isinstance(data[key], dict):
                            acts = list(data[key].keys())
                        break
                return {
                    "package": pkg or "com.example.app",
                    "label": label,
                    "main_activity": main_act or "MainActivity",
                    "activities": acts or [],
                }
            except Exception as e:
                logger.error("Error loading app.json: %s", e)

        # 2) Fallback: parse the APK directly (androguard via droidbot.app.App)
        try:
            apk = App(self.apk_path)
            pkg = None
            label = None
            main_act = None
            acts = None

            # droidbot.App exposes androguard APK via apk.apk if present
            ag_apk = getattr(apk, "apk", None)

            # Package
            if hasattr(apk, "get_package_name"):
                pkg = apk.get_package_name()
            elif ag_apk and hasattr(ag_apk, "package"):
                pkg = ag_apk.package

            # App name / label
            if hasattr(apk, "get_app_name"):
                label = apk.get_app_name()
            elif ag_apk and hasattr(ag_apk, "get_app_name"):
                label = ag_apk.get_app_name()

            # Main activity
            if hasattr(apk, "get_main_activity"):
                main_act = apk.get_main_activity()
            elif ag_apk and hasattr(ag_apk, "get_main_activity"):
                main_act = ag_apk.get_main_activity()

            # Activities
            if ag_apk and hasattr(ag_apk, "get_activities"):
                try:
                    acts = ag_apk.get_activities() or []
                except Exception:
                    acts = None

            return {
                "package": pkg or "com.example.app",
                "label": label,
                "main_activity": main_act or "MainActivity",
                "activities": acts or [],
            }
        except Exception:
            logger.warning("app.json missing and APK parse failed; using defaults")
            return {"package": "com.example.app", "main_activity": "MainActivity", "activities": []}

    def take_screenshot(self, filename):
        """Take a screenshot and save to file"""
        try:
            # Create screenshot directory if needed
            os.makedirs(os.path.dirname(filename), exist_ok=True)

            # Take screenshot
            result = subprocess.run(
                ["adb", "shell", "screencap", "-p", "/sdcard/screen.png"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )

            if result.returncode != 0:
                logger.error(f"Screencap failed: {result.stderr.decode().strip()}")
                return False

            # Pull screenshot from device
            result = subprocess.run(
                ["adb", "pull", "/sdcard/screen.png", filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )

            if result.returncode != 0:
                logger.error(f"Pull screenshot failed: {result.stderr.decode().strip()}")
                return False

            return True

        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Screenshot failed: {e}")
            return False

    def terminate_subprocess(self, proc: subprocess.Popen, name: str):
        """Terminate a subprocess safely"""
        if proc and proc.poll() is None:  # Process is still running
            logger.info(f"Terminating {name} process (PID: {proc.pid})")

            # Try to terminate gracefully
            proc.terminate()
            try:
                proc.wait(timeout=5)
                logger.info(f"{name} process terminated successfully")
            except subprocess.TimeoutExpired:
                logger.warning(f"{name} process did not terminate, killing it")
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    logger.error(f"Failed to kill {name} process")

    def pause_threads_and_processes(self):
        """Pause all threads and terminate their subprocesses"""
        logger.info("Pausing threads and terminating subprocesses...")

        # Pause threads
        if self.droidbot_thread and self.droidbot_thread.is_alive():
            self.droidbot_thread.pause()

        if self.rotation_thread and self.rotation_thread.is_alive():
            self.rotation_thread.pause()

        if self.data_loss_thread and self.data_loss_thread.is_alive():
            self.data_loss_thread.pause()

        if self.power_cycle_thread and self.power_cycle_thread.is_alive():
            self.power_cycle_thread.pause()

        # Terminate subprocesses
        if self.rotation_process:
            self.terminate_subprocess(self.rotation_process, "rotation")
            self.rotation_process = None

        if self.power_cycle_process:
            self.terminate_subprocess(self.power_cycle_process, "power cycle")
            self.power_cycle_process = None

    def resume_threads_and_processes(self):
        """Resume threads and restart their subprocesses"""
        logger.info("Resuming threads and restarting subprocesses...")

        # Restart rotation if needed
        if self.rotate:
            if not self.rotation_process or self.rotation_process.poll() is not None:
                logger.info("Restarting rotation process")
                self.rotation_process = subprocess.Popen(
                    ["python", "DLD/rotate.py", self.output_dir],
                    start_new_session=True  # Prevent zombie processes
                )
            if self.rotation_thread and self.rotation_thread.is_alive():
                self.rotation_thread.resume()
            else:
                logger.warning("Rotation thread is not alive, not resuming")

        # Restart power cycle if needed
        if self.power_cycle:
            if not self.power_cycle_process or self.power_cycle_process.poll() is not None:
                logger.info("Restarting power cycle process")
                self.power_cycle_process = subprocess.Popen(
                    ["python", "DLD/power_cycle.py", self.output_dir],
                    start_new_session=True
                )
            if self.power_cycle_thread and self.power_cycle_thread.is_alive():
                self.power_cycle_thread.resume()
            else:
                logger.warning("Power cycle thread is not alive, not resuming")


        # Resume other threads
        if self.droidbot_thread and self.droidbot_thread.is_alive():
            self.droidbot_thread.resume()

        if self.data_loss_thread and self.data_loss_thread.is_alive():
            self.data_loss_thread.resume()

    def trigger_home_button(self, trigger_reason="manual"):
        """Simulate pressing home button and reopening app"""
        current_time = time.time()
        time_since_last = current_time - self.last_home_time

        # Check constraints
        if time_since_last < self.min_home_interval:
            #logger.info(f"Skipping home button (interval: {time_since_last:.1f}s < {self.min_home_interval}s)")
            return False

        if self.home_action_count >= self.max_home_actions:
            logger.info(f"Max home button actions ({self.max_home_actions}) reached")
            return False

        logger.info(f"=== Triggering home button simulation ({trigger_reason}) ===")

        try:
            before_path = os.path.join(self.screenshot_dir, f"before_{self.home_action_count}.png")
            if self.take_screenshot(before_path):
                logger.info(f"Saved pre-home screenshot to {before_path}")

            logger.info("Pressing home button...")
            adbCheck(["shell", "input", "keyevent", "KEYCODE_HOME"], check=False, timeout=5)

            time.sleep(0.5)
            app_info = self.apkMetadata()
            package = app_info.get("package", "")
            activity = app_info.get("main_activity", "")
            if package and activity:
                logger.info(f"Reopening app: {package}/{activity}")
                # Some app.json store fully qualified activity; if not, prefix with package
                comp = f"{package}/{activity if '.' in activity else package + '.' + activity}"
                adbCheck(["shell", "am", "start", "-n", comp], check=False, timeout=5)
            time.sleep(7)

            after_path = os.path.join(self.screenshot_dir, f"after_{self.home_action_count}.png")
            if self.take_screenshot(after_path):
                logger.info(f"Saved post-home screenshot to {after_path}")

            self.last_home_time = current_time
            self.home_action_count += 1
            logger.info(f"Home button simulation #{self.home_action_count} completed")
            return True
        except subprocess.SubprocessError as e:
            logger.error(f"Home button simulation failed: {e}")
            return False

    def check_events_for_home_trigger(self):
        """Check events directory for new events that should trigger home button"""
        events_dir = os.path.join(self.output_dir, "events")
        if not os.path.exists(events_dir):
            return False
        current = {e.name for e in os.scandir(events_dir) if e.is_file() and e.name.endswith(".json")}
        new_files = current - self.seen_events

        for name in new_files:
            try:
                with open(os.path.join(events_dir, name), "r", encoding="utf-8") as f:
                    data = json.load(f)
                etype = data.get("event", {}).get("event_type", "")
                if etype in HOME_BUTTON_EVENTS:
                    logger.info("Found trigger event: %s in %s", etype, name)
                    return True
            except Exception as e:
                logger.error("Error processing %s: %s", name, e)
            finally:
                self.seen_events.add(name)
        return False

    def run_droidbot(self):
        """Run DroidBot in a subprocess"""
        os.makedirs(self.output_dir, exist_ok=True)
        # Explicitly create events directory if it doesn't exist
        os.makedirs(os.path.join(self.output_dir, "events"), exist_ok=True)

        cmd = [
            "droidbot",
            "-a", self.apk_path,
            "-o", self.output_dir,
            "-timeout", str(self.timeout),
            "-is_emulator",
            "-grant_perm",
            "-accessibility_auto",
        ]

        logger.info(f"Starting DroidBot: {' '.join(cmd)}")
        self.droidbot_process = subprocess.Popen(
            cmd,
            start_new_session=True  # Prevent zombie processes
        )
        self.droidbot_process.wait()

    def run_rotation(self):
        """Run rotation using rotate.py script"""
        if not self.rotate:
            return

        cmd = ["python", "DLD/rotate.py", self.output_dir]
        logger.info(f"Starting rotation: {' '.join(cmd)}")
        self.rotation_process = subprocess.Popen(
            cmd,
            start_new_session=True
        )
        self.rotation_process.wait()

    def run_power_cycle(self):
        """Run power cycle simulation"""
        if not self.power_cycle:
            return

        cmd = ["python", "DLD/power_cycle.py", self.output_dir]
        logger.info(f"Starting power cycle: {' '.join(cmd)}")
        self.power_cycle_process = subprocess.Popen(
            cmd,
            start_new_session=True
        )
        self.power_cycle_process.wait()

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
        """
        Run crash.py, capture its stdout, save it, and extract total crash count.
        Writes:
          - crashes/crash_analysis.txt (full stdout)
          - crashes/crashes.json      ({"count": N, "source": "crash.py"})
        """
        crash_script = os.path.join(os.path.dirname(__file__), "DLD", "crash.py")
        if not os.path.exists(crash_script):
            # Try relative path if startDLD.py lives next to DLD/
            alt = os.path.join(os.path.dirname(__file__), "crash.py")
            crash_script = alt if os.path.exists(alt) else crash_script

        if not os.path.exists(crash_script):
            print(f"Warning: Crash analysis script not found at {crash_script}")
            return

        try:
            # Run and capture
            proc = subprocess.run(
                ["python", crash_script, self.output_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False
            )
            out_txt = proc.stdout or ""

            # Save full stdout
            os.makedirs(self.crash_dir, exist_ok=True)
            analysis_path = os.path.join(self.crash_dir, "crash_analysis.txt")
            with open(analysis_path, "w", encoding="utf-8") as f:
                f.write(out_txt)

            # Parse "Total crashes detected: N"
            m = re.search(r"Total crashes detected:\s*(\d+)", out_txt)
            count = int(m.group(1)) if m else 0

            # Save a simple JSON summary that count_crashes() will use
            with open(os.path.join(self.crash_dir, "crashes.json"), "w", encoding="utf-8") as f:
                json.dump({"count": count, "source": "crash.py"}, f, indent=2)

            logging.info("Crash analysis complete (count=%d). Output saved to %s", count, analysis_path)
        except Exception:
            logging.exception("Failed to run/parse crash analysis")

    def run_home_button_analysis(self):
        """Run home button analysis after DroidBot finishes"""
        print("\nRunning home button analysis...")
        crash_script = os.path.join(os.path.dirname(__file__), "home_button_data_loss.py")
        if os.path.exists(crash_script):
            subprocess.run(["python", crash_script, self.output_dir])
        else:
            print(f"Warning: Crash analysis script not found at {crash_script}")

    def cleanup(self):
        """Clean up all processes and threads"""
        logger.info("\nCleaning up all resources...")
        self.should_stop = True

        # Stop threads
        for thread in [self.droidbot_thread, self.rotation_thread,
                       self.data_loss_thread, self.power_cycle_thread]:
            if thread and thread.is_alive():
                thread.stop()  # Signal thread to stop
                thread.join(timeout=5)
                if thread.is_alive():
                    logger.warning(f"{thread.name} did not stop gracefully")

        # Terminate subprocesses
        for proc, name in [
            (self.droidbot_process, "DroidBot"),
            (self.rotation_process, "Rotation"),
            (self.power_cycle_process, "Power Cycle")
        ]:
            if proc:
                self.terminate_subprocess(proc, name)

        # Stop data loss detector
        if self.data_loss_detector:
            self.data_loss_detector.stop()


        # Reset to portrait if rotation was enabled
        if self.rotate:
            try:
                subprocess.run(["adb", "emu", "rotate", "portrait"], timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Failed to reset to portrait orientation")

        logger.info("Cleanup complete")

    def run(self):
        """Main execution"""
        print(f"\n{'='*50}")
        print(f"Starting DroidBot for APK: {self.apk_path}")
        print(f"Output directory: {self.output_dir}")
        print(f"Timeout: {self.timeout} seconds")
        print(f"Max home button actions: {self.max_home_actions}")
        if self.rotate:
            print("With random screen rotation enabled")
        else:
            print("With screen rotation disabled")
        if self.power_cycle:
            print("With power cycle simulation enabled")
        else:
            print("With power cycle simulation disabled")
        print("With enhanced data loss detection enabled")
        print("Press Ctrl+C to stop early")
        print(f"{'='*50}\n")
        self.enableAccessibility()
        self.start_time = time.time()

        # Initialize event tracking
        events_dir = os.path.join(self.output_dir, "events")
        if os.path.exists(events_dir):
            self.seen_events = set(os.listdir(events_dir))

        # Create and start threads
        self.droidbot_thread = PausableThread(target=self.run_droidbot, name="DroidBotThread")
        self.droidbot_thread.daemon = True
        self.droidbot_thread.start()

        if self.rotate:
            self.rotation_thread = PausableThread(target=self.run_rotation, name="RotationThread")
            self.rotation_thread.daemon = True
            self.rotation_thread.start()

        self.data_loss_thread = PausableThread(target=self.run_data_loss_detector, name="DataLossThread")
        self.data_loss_thread.daemon = True
        self.data_loss_thread.start()

        if self.power_cycle:
            self.power_cycle_thread = PausableThread(target=self.run_power_cycle, name="PowerCycleThread")
            self.power_cycle_thread.daemon = True
            self.power_cycle_thread.start()

        try:
            while self.droidbot_thread.is_alive() and not self.should_stop:
                elapsed = time.time() - self.start_time

                # Check timeout
                if elapsed > self.timeout:
                    print(f"\nTimeout reached ({self.timeout} seconds), stopping...")
                    self.should_stop = True
                    break

                # Check for events that should trigger home button
                if self.home_button and self.check_events_for_home_trigger() and (time.time() - self.last_home_time) >= self.min_home_interval:
                    print("\n=== Event detected that requires home button simulation ===")

                    # Pause threads and terminate subprocesses
                    self.pause_threads_and_processes()

                    # Perform home button simulation
                    self.trigger_home_button(trigger_reason="event")

                    # Resume threads and restart subprocesses
                    self.resume_threads_and_processes()
                    print("Resumed normal operations")

                time.sleep(1)  # Check interval

        except KeyboardInterrupt:
            logger.info("\nCtrl+C detected, stopping...")
            self.should_stop = True
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            self.should_stop = True
        finally:
            # Run cleanup
            self.cleanup()

            # Run crash analysis after cleanup
            self.run_crash_analysis()
            if(self.home_button):
                self.run_home_button_analysis()
            logger.info("Processing complete")
            self.print_end_summary()


def process_apk(apk_path: str, output_dir: str = None, rotate: bool = True,
                power_cycle: bool = True, home_button: bool = True,
                timeout: int = 300, max_home_actions: int = 20):
    """Process a single APK file"""
    manager = ProcessManager(
        apk_path=apk_path,
        output_dir=output_dir,
        rotate=rotate,
        power_cycle=power_cycle,
        home_button=home_button,
        timeout=timeout,
        max_home_actions=max_home_actions
    )
    manager.run()

def process_all_apks(apk_dir: str, output_parent_dir: str = "output", rotate: bool = True,
                     power_cycle: bool = True, home_button: bool = True,
                     timeout: int = 120, max_home_actions: int = 20):
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
            power_cycle=power_cycle,
            home_button=home_button,
            timeout=timeout,
            max_home_actions=max_home_actions
        )

def parse_args():
    parser = argparse.ArgumentParser(
        description='Run DroidBot with optional screen rotations, power cycles, and data loss detection.',
        formatter_class=argparse.RawTextHelpFormatter
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
        '--no-power-cycle',
        action='store_false',
        dest='power_cycle',
        help='Disable power cycle simulation'
    )
    parser.add_argument(
        '--no-home-button',
        action='store_false',
        dest='home_button',
        help='Disable home button simulation'
    )
    parser.add_argument(
        '-t', '--timeout',
        type=int,
        default=120,
        help='Timeout in seconds for each APK\n'
             '(default: 120)'
    )
    parser.add_argument(
        '--max-home-actions',
        type=int,
        default=99,
        help='Maximum home button actions per test session'
    )
    return parser.parse_args()

def cleanDirectory(apk_path = None):
    dir_output = "output/"
    folder_names = ["data_loss_events",
                    "data_loss_logs",
                    "events",
                    "states",
                    "temp",
                    "views",
                    "home_button_screenshots"]
    if not os.path.exists("output"):
        os.makedirs("output", exist_ok=True)

    # Reset to portrait orientation before starting new test
    # subprocess.run(["adb", "emu", "rotate", "portrait"], timeout=5)
    # Reset to portrait orientation before starting new test
    try:
        subprocess.run(["adb", "emu", "rotate", "portrait"], timeout=5, check=False)
    except FileNotFoundError:
        logger.warning("adb not found on PATH; skipping portrait reset. Add platform-tools to PATH or set ANDROID_SDK_ROOT.")
    except subprocess.TimeoutExpired:
        logger.warning("Failed to reset to portrait orientation (timeout)")


    if apk_path:
        apk_file_name = os.path.splitext(os.path.basename(os.path.normpath(apk_path)))[0]
        for folder in folder_names:
            folder_output = os.path.join(dir_output, apk_file_name, folder)
            if os.path.exists(folder_output):
                shutil.rmtree(folder_output)
            os.makedirs(folder_output, exist_ok=True)
    else:
        file_paths = glob.glob(os.path.join('DLD', 'APK', '*.apk'))
        # apk_dir = file_paths = glob.glob('DLD/APK/*')
        # apk_names = [os.path.basename(path) for path in file_paths]
        apk_names = [os.path.splitext(os.path.basename(p))[0] for p in file_paths]
        for apk in apk_names:
            for folder in folder_names:
                # folder_output = dir_output + apk.strip(".apk") + '/' + folder
                folder_output = os.path.join(dir_output, apk, folder)
                if os.path.exists(folder_output):
                    shutil.rmtree(folder_output)
                os.makedirs(folder_output, exist_ok=True)

if __name__ == "__main__":
    checkAdbPath()
    args = parse_args()
    cleanDirectory(args.apk_path)
    if args.apk_path:
        process_apk(
            apk_path=args.apk_path,
            output_dir=None,
            rotate=args.rotate,
            power_cycle=args.power_cycle,
            home_button=args.home_button,
            timeout=args.timeout
        )
    else:
        process_all_apks(
            apk_dir=args.apk_dir,
            output_parent_dir=args.output,
            rotate=args.rotate,
            power_cycle=args.power_cycle,
            home_button=args.home_button,
            timeout=args.timeout
        )
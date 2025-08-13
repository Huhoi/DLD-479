import subprocess
import time
import os
import json
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('HomeButtonSimulator')

# List of event types that should trigger home button simulation
HOME_BUTTON_EVENTS = {
    "touch", 
    "long_touch", 
    "set_text",
    "spawn",
    "scroll",
    "swipe"
}

class HomeButtonEventHandler(FileSystemEventHandler):
    def __init__(self, events_dir, output_dir, min_interval=10, max_actions=5):
        """
        Initialize home button event handler
        :param events_dir: Directory to monitor for events
        :param output_dir: DroidBot output directory (to find app info)
        :param min_interval: Minimum seconds between home button simulations
        :param max_actions: Maximum home button actions per test session
        """
        self.events_dir = events_dir
        self.output_dir = output_dir
        self.min_interval = 10
        self.max_actions = 20
        self.last_action_time = 0
        self.action_count = 0
        self.app_info = self._load_app_info()
        
        logger.info(f"Home button settings: Min interval={min_interval}s, Max actions={max_actions}")
        logger.info(f"App info: {self.app_info['package']}/{self.app_info['main_activity']}")
        
        # Process existing events
        self._process_existing_events()
    
    def _load_app_info(self):
        """Load app information from DroidBot's app.json"""
        app_json_path = os.path.join(self.output_dir, "app.json")
        if not os.path.exists(app_json_path):
            logger.error(f"app.json not found at {app_json_path}")
            return {
                "package": "com.example.app",
                "main_activity": "MainActivity"
            }
        
        try:
            with open(app_json_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading app.json: {e}")
            return {
                "package": "com.example.app",
                "main_activity": "MainActivity"
            }
    
    def _process_existing_events(self):
        """Process all existing event files"""
        if os.path.exists(self.events_dir):
            for event_file in sorted(os.listdir(self.events_dir)):
                if event_file.endswith('.json'):
                    self._process_event_file(event_file)
    
    def on_created(self, event):
        if event.src_path.endswith('.json'):
            self._process_event_file(os.path.basename(event.src_path))
    
    def _process_event_file(self, event_file):
        """Check if the event should trigger home button simulation"""
        try:
            with open(os.path.join(self.events_dir, event_file), 'r') as f:
                event_data = json.load(f)
            
            event_type = event_data.get("event", {}).get("event_type", "")
            if event_type in HOME_BUTTON_EVENTS:
                self._simulate_home_button(event_file)
        except (json.JSONDecodeError, KeyError, IOError) as e:
            logger.error(f"Error processing {event_file}: {e}")
    
    def _simulate_home_button(self, event_file):
        """Simulate pressing home button and reopening app"""
        current_time = time.time()
        time_since_last = current_time - self.last_action_time
        
        # Check interval constraint
        if time_since_last < self.min_interval:
            logger.info(f"Skipping home button (interval: {time_since_last:.1f}s < {self.min_interval}s) "
                        f"triggered by {event_file}")
            return
        
        # Check max actions constraint
        if self.action_count >= self.max_actions:
            logger.info(f"Max home button actions ({self.max_actions}) reached, skipping {event_file}")
            return
        
        logger.info(f"Simulating home button press (triggered by {event_file}, "
                    f"interval: {time_since_last:.1f}s)...")
        
        try:
            if self.action_count != 0:
                # Step 1: Press home button to exit app
                logger.info("Pressing home button...")
                subprocess.run(
                    ["adb", "shell", "input", "keyevent", "KEYCODE_HOME"],
                    check=True,
                    timeout=5
                )
                
                # Wait briefly
                time.sleep(1)
                
                # Step 2: Reopen the app
                logger.info("Reopening the app...")
                package = self.app_info["package"]
                activity = self.app_info["main_activity"]
                subprocess.run(
                    ["adb", "shell", "am", "start", "-n", f"{package}/{package}.{activity}"],
                    check=True,
                    timeout=5
                )
                
                # Wait for app to relaunch
                time.sleep(3)
            
            # Update tracking
            self.last_action_time = current_time
            self.action_count += 1
            if self.action_count != 1:
                logger.info(f"Home button simulation #{self.action_count} completed successfully")
            
        except subprocess.SubprocessError as e:
            logger.error(f"Home button simulation failed: {e}")

def home_button_on_event(output_dir, min_interval=30, max_actions=5):
    """Monitor DroidBot's events folder and simulate home button press on specific events"""
    events_dir = os.path.join(output_dir, "events")
    if not os.path.exists(events_dir):
        logger.error(f"Events directory not found at {events_dir}")
        return
    
    logger.info("Starting event-synchronized home button simulation...")
    logger.info(f"Trigger events: {', '.join(sorted(HOME_BUTTON_EVENTS))}")
    logger.info(f"Settings: Min interval={min_interval}s, Max actions={max_actions}")
    logger.info("Press Ctrl+C to stop")
    
    # Create observer to watch for new event files
    event_handler = HomeButtonEventHandler(
        events_dir, 
        output_dir,
        min_interval,
        max_actions
    )
    observer = Observer()
    observer.schedule(event_handler, path=events_dir, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("\nHome button monitoring stopped")
    
    observer.join()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Simulate home button press on specific DroidBot events with configurable interval.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('output_dir', help='DroidBot output directory containing events folder')
    parser.add_argument('--min-interval', type=int, default=30,
                        help='Minimum seconds between home button actions')
    parser.add_argument('--max-actions', type=int, default=5,
                        help='Maximum home button actions per test session')
    args = parser.parse_args()
    
    home_button_on_event(
        args.output_dir,
        args.min_interval,
        args.max_actions
    )
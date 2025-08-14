import subprocess
import time
import os
import json
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('PowerCycleTester')

# List of event types that should trigger power cycle simulation
POWER_CYCLE_EVENTS = {
    "manual", 
    "exit", 
    "long_touch", 
    "set_text",
    "spawn",
    "key"
}

class PowerCycleEventHandler(FileSystemEventHandler):
    def __init__(self, events_dir, power_off_duration=1, min_interval=10, max_cycles=99):
        self.events_dir = events_dir
        self.power_off_duration = power_off_duration       
        self.last_power_cycle_time = 0
        self.power_cycle_count = 0
        self.min_interval = min_interval
        self.max_cycles = 3  # Max power cycles per test
        
        # Process existing events
        self._process_existing_events()
    
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
        """Check if the event should trigger a power cycle"""
        try:
            with open(os.path.join(self.events_dir, event_file), 'r') as f:
                event_data = json.load(f)
            
            event_type = event_data.get("event", {}).get("event_type", "")
            if event_type in POWER_CYCLE_EVENTS:
                self._simulate_power_cycle(event_file)
        except (json.JSONDecodeError, KeyError, IOError) as e:
            logger.error(f"Error processing {event_file}: {e}")
    
    def _simulate_power_cycle(self, event_file):
        """Simulate power button press to turn screen off/on"""
        current_time = time.time()
        
        # Rate limiting: Only allow power cycle every 30 seconds
        if current_time - self.last_power_cycle_time < 30:
            #logger.info(f"Skipping power cycle (rate limited) triggered by {event_file}")
            return
        
        # Max power cycles per test
        if self.power_cycle_count >= self.max_cycles:
            logger.info(f"Max power cycles ({self.max_cycles}) reached, skipping")
            return
        
        logger.info(f"Simulating power button press (triggered by {event_file})...")
        
        try:
            if self.power_cycle_count != 0:
                # Step 1: Turn screen off
                logger.info("Turning screen off...")
                subprocess.run(
                    ["adb", "shell", "input", "keyevent", "KEYCODE_POWER"],
                    check=True,
                    timeout=5
                )
                
                # Wait for device to sleep
                time.sleep(3)
                
                # Step 2: Turn screen back on
                logger.info("Turning screen on...")
                subprocess.run(
                    ["adb", "shell", "input", "keyevent", "KEYCODE_POWER"],
                    check=True,
                    timeout=5
                )
                
                
                
                # Step 3: Unlock device if needed (swipe up)
                logger.info("Unlocking device...")
                subprocess.run(
                    ["adb", "shell", "input", "swipe", "500", "1500", "500", "500", "300"],
                    check=True,
                    timeout=5
                )
                
            
            
            # Update tracking
            self.last_power_cycle_time = current_time
            self.power_cycle_count += 1
            if self.power_cycle_count != 1:
                logger.info(f"Power cycle #{self.power_cycle_count} completed successfully")
            
        except subprocess.SubprocessError as e:
            logger.error(f"Power cycle simulation failed: {e}")
            # Step 2: Turn screen back on
            
            
def power_cycle_on_event(output_dir, power_off_duration=10):
    """Monitor DroidBot's events folder and simulate power cycles on specific events"""
    events_dir = os.path.join(output_dir, "events")
    if not os.path.exists(events_dir):
        logger.error(f"Events directory not found at {events_dir}")
        return
    
    logger.info("Starting event-synchronized power cycle simulation...")
    logger.info(f"Will simulate power button press on these events: {', '.join(sorted(POWER_CYCLE_EVENTS))}")
    logger.info(f"Max power cycles per test: 3, Min interval: 30 seconds")
    logger.info("Press Ctrl+C to stop")
    
    # Create observer to watch for new event files
    event_handler = PowerCycleEventHandler(events_dir, power_off_duration)
    observer = Observer()
    observer.schedule(event_handler, path=events_dir, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("\nPower cycle monitoring stopped")
    
    observer.join()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Simulate power button press on specific DroidBot events.')
    parser.add_argument('output_dir', help='DroidBot output directory containing events folder')
    parser.add_argument('--power-off-duration', type=int, default=10,
                        help='Duration in seconds to keep screen off (default: 10)')
    args = parser.parse_args()
    
    power_cycle_on_event(args.output_dir, args.power_off_duration)
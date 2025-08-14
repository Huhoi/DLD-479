import subprocess
import time
import os
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# List of event types that should trigger rotation
ROTATION_EVENTS = {
    "key",
    "manual", 
    "exit", 
    "touch",  
    "long_touch", 
    "set_text",
    "select",
    "unselect",
    "intent",
    "spawn"
}


class DroidBotEventHandler(FileSystemEventHandler):
    def __init__(self, events_dir):
        self.events_dir = events_dir
        self.last_rotation_time = 0
        self.current_orientation = "portrait"  # Start in portrait mode
        # Wait for directory to be created
        self._wait_for_events_dir()
        # Rotate for all existing events first
        self._rotate_for_existing_events()
    
    def _wait_for_events_dir(self, timeout=30):
        """Wait for events directory to be created"""
        start_time = time.time()
        while not os.path.exists(self.events_dir):
            if time.time() - start_time > timeout:
                raise FileNotFoundError(f"Events directory not created within {timeout} seconds")
            time.sleep(1)
    
    def _rotate_for_existing_events(self):
        """Rotate for all existing event files"""
        try:
            for event_file in sorted(os.listdir(self.events_dir)):
                if event_file.endswith('.json'):
                    self._process_event_file(event_file)
        except FileNotFoundError:
            print(f"Events directory not found yet, will process new events as they arrive")
    
    def on_created(self, event):
        if event.src_path.endswith('.json'):
            self._process_event_file(os.path.basename(event.src_path))
    
    def _process_event_file(self, event_file):
        """Check if the event should trigger rotation"""
        try:
            with open(os.path.join(self.events_dir, event_file), 'r') as f:
                event_data = json.load(f)
            
            event_type = event_data.get("event", {}).get("event_type", "")
            if event_type in ROTATION_EVENTS:
                self._rotate_device(event_file)
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            print(f"Error processing {event_file}: {e}")
    
    def _rotate_device(self, event_file):
        """Perform a single clockwise rotation with rate limiting"""
        current_time = time.time()
        if current_time - self.last_rotation_time < 5:
            #print(f"Skipping rotation (rate limited) triggered by {event_file}")
            return
        
        # Get next orientation in cycle
        if self.current_orientation == "portrait":
            new_orientation, description = "landscape", "90° (Landscape)"
        elif self.current_orientation == "landscape":
            new_orientation, description = "landscape", "270° (Reverse Landscape)"
        else:  # reverse landscape or other
            new_orientation, description = "portrait", "0° (Portrait)"
        
        print(f"Rotating to {description} (triggered by {event_file})...")
        
        try:
            # Single rotation command
            subprocess.run(
                ["adb", "emu", "rotate", new_orientation],
                check=True,
                timeout=5
            )
            
            # For reverse landscape, rotate twice (but still counts as one rotation)
            if description == "270° (Reverse Landscape)":
                time.sleep(1)  # Short delay between rotations
                subprocess.run(
                    ["adb", "emu", "rotate", new_orientation],
                    check=True,
                    timeout=5
                )
            
            self.current_orientation = new_orientation
            self.last_rotation_time = current_time
            print(f"Successfully rotated to {description}")
        except subprocess.SubprocessError as e:
            print(f"Rotation failed: {e}")

def rotate_on_event(output_dir):
    """Monitor DroidBot's events folder and rotate on specific events"""
    events_dir = os.path.join(output_dir, "events")
    
    print("Starting event-synchronized rotation...")
    print(f"Will rotate clockwise on these events: {', '.join(sorted(ROTATION_EVENTS))}")
    print("Max rotation rate: once every 5 seconds")
    print("Press Ctrl+C to stop")
    
    # Create observer to watch for new event files
    event_handler = DroidBotEventHandler(events_dir)
    observer = Observer()
    observer.schedule(event_handler, path=events_dir, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nResetting to portrait...")
        subprocess.run(["adb", "emu", "rotate", "portrait"], timeout=5)
    
    observer.join()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Rotate device clockwise on specific DroidBot events (max once every 5s).')
    parser.add_argument('output_dir', help='DroidBot output directory containing events folder')
    args = parser.parse_args()
    
    rotate_on_event(args.output_dir)
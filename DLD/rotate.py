import subprocess
import time
import random
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class DroidBotEventHandler(FileSystemEventHandler):
    def __init__(self, events_dir):
        self.events_dir = events_dir
        self.processed_events = set()
        self.orientations = [
            ("portrait", "0° (Portrait)"),
            ("landscape", "90° (Landscape)"),
            ("landscape", "270° (Reverse Landscape)")  # Achieved via double rotation
        ]
        # Initialize with existing event files
        self._init_processed_events()
    
    def _init_processed_events(self):
        """Track already existing event files so we don't rotate for them"""
        if os.path.exists(self.events_dir):
            for f in os.listdir(self.events_dir):
                if f.endswith('.json'):
                    self.processed_events.add(f)
    
    def on_created(self, event):
        if event.src_path.endswith('.json') and os.path.basename(event.src_path) not in self.processed_events:
            self.processed_events.add(os.path.basename(event.src_path))
            self.rotate_device()
    
    def rotate_device(self):
        """Perform the actual rotation"""
        # Choose random orientation
        orientation, description = random.choice(self.orientations)
        print(f"Rotating to {description} (triggered by new DroidBot event)...")
        
        try:
            # Single rotation command
            subprocess.run(
                ["adb", "emu", "rotate", orientation],
                check=True,
                timeout=5
            )
            
            # For reverse landscape, rotate twice
            if description == "270° (Reverse Landscape)":
                time.sleep(0.5)  # Short delay between rotations
                subprocess.run(
                    ["adb", "emu", "rotate", orientation],
                    check=True,
                    timeout=5
                )
            
            print(f"Successfully rotated to {description}")
        except subprocess.SubprocessError as e:
            print(f"Rotation failed: {e}")

def rotate_on_event(output_dir):
    """Monitor DroidBot's events folder and rotate on new events"""
    events_dir = os.path.join(output_dir, "events")
    if not os.path.exists(events_dir):
        print(f"Error: Events directory not found at {events_dir}")
        return
    
    print("Starting event-synchronized rotation...")
    print("Will rotate after each new DroidBot event")
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
    
    parser = argparse.ArgumentParser(description='Rotate device synchronized with DroidBot events.')
    parser.add_argument('output_dir', help='DroidBot output directory containing events folder')
    args = parser.parse_args()
    
    rotate_on_event(args.output_dir)
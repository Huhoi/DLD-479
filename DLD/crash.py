import os
import json
import argparse
from PIL import Image
import imagehash

def detect_crashes(output_dir, similarity_threshold=5):
    """
    Detect app crashes by checking if homescreen appears again after initial state.
    
    Args:
        output_dir: Path to the output directory (e.g., "output/apkName")
        similarity_threshold: Maximum hash difference to consider states similar (fixed at 5)
        
    Returns:
        List of event indices where crashes were detected
    """
    states_path = os.path.join(output_dir, "states")
    events_path = os.path.join(output_dir, "events")
    
    # Get all state and event files
    state_files = sorted([f for f in os.listdir(states_path) if f.endswith('.png') or f.endswith('.jpg')])
    event_files = sorted([f for f in os.listdir(events_path) if f.endswith('.json')])
    
    if not state_files or not event_files:
        print(f"No state or event files found in {output_dir}")
        return []
    
    # Load initial state
    initial_state_file = os.path.join(states_path, state_files[0])
    initial_hash = imagehash.average_hash(Image.open(initial_state_file))
    
    crash_points = []
    
    # Compare all subsequent states to initial state
    for i, state_file in enumerate(state_files[1:], 1):
        current_state_file = os.path.join(states_path, state_file)
        current_hash = imagehash.average_hash(Image.open(current_state_file))
        
        # If state is similar to initial state (homescreen), potential crash
        if current_hash - initial_hash <= similarity_threshold:
            print(f"Potential crash detected at state {i} ({state_file})")
            
            # Find the corresponding event
            if i < len(event_files):
                event_file = os.path.join(events_path, event_files[i])
                with open(event_file) as f:
                    event_data = json.load(f)
                for event in event_data:
                    print(f"{event} : {event_data[event]}")
            
            crash_points.append(i)
    
    return crash_points

def parse_args():
    parser = argparse.ArgumentParser(description='Detect app crashes from DroidBot output.')
    parser.add_argument('output_dir', help='Path to the output directory (e.g., "output/apkName")')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    
    if not os.path.exists(args.output_dir):
        print(f"Error: output directory not found at {args.output_dir}")
        exit(1)
    
    crashes = detect_crashes(args.output_dir)  # Threshold is now fixed at 5
    
    if crashes:
        print(f"\nDetected {len(crashes)} potential crash(es) at positions: {crashes}")
    else:
        print("\nNo crashes detected")
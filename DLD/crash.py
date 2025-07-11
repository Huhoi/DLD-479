import os
import json
from PIL import Image
import imagehash

def detect_crashes(states_path, events_path, similarity_threshold=5):
    """
    Detect app crashes by checking if homescreen appears again after initial state.
    
    Args:
        states_path: Path to the states directory
        events_path: Path to the events directory
        similarity_threshold: Maximum hash difference to consider states similar
        
    Returns:
        List of event indices where crashes were detected
    """
    # Get all state and event files
    state_files = sorted([f for f in os.listdir(states_path) if f.endswith('.png') or f.endswith('.jpg')])
    event_files = sorted([f for f in os.listdir(events_path) if f.endswith('.json')])
    
    if not state_files or not event_files:
        print("No state or event files found")
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

if __name__ == "__main__":
    states_path = "DLD/output/states"
    events_path = "DLD/output/events"
    
    if not os.path.exists(states_path) or not os.path.exists(events_path):
        print("Error: states or events directory not found")
        exit(1)
    
    crashes = detect_crashes(states_path, events_path)
    
    if crashes:
        print(f"\nDetected {len(crashes)} potential crash(es) at positions: {crashes}")
    else:
        print("\nNo crashes detected")
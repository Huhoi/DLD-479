import os
import json
import argparse
from PIL import Image
import imagehash
from datetime import datetime

def detect_crashes(output_dir, similarity_threshold=5):
    """
    Detect app crashes by checking if homescreen appears again after initial state.
    
    Args:
        output_dir: Path to the output directory (e.g., "output/apkName")
        similarity_threshold: Maximum hash difference to consider states similar (fixed at 5)
        
    Returns:
        Dictionary containing crash information and metadata
    """
    states_path = os.path.join(output_dir, "states")
    events_path = os.path.join(output_dir, "events")
    
    # Initialize result dictionary
    result = {
        "metadata": {
            "output_dir": output_dir,
            "analysis_time": datetime.now().isoformat(),
            "similarity_threshold": similarity_threshold
        },
        "crashes": []
    }
    
    # Get all state and event files
    state_files = sorted([f for f in os.listdir(states_path) if f.endswith('.png') or f.endswith('.jpg')])
    event_files = sorted([f for f in os.listdir(events_path) if f.endswith('.json')])
    
    if not state_files or not event_files:
        print(f"No state or event files found in {output_dir}")
        return result
    
    # Load initial state
    initial_state_file = os.path.join(states_path, state_files[0])
    initial_hash = imagehash.average_hash(Image.open(initial_state_file))
    
    # Compare all subsequent states to initial state
    for i, state_file in enumerate(state_files[1:], 1):
        current_state_file = os.path.join(states_path, state_file)
        current_hash = imagehash.average_hash(Image.open(current_state_file))
        
        # If state is similar to initial state (homescreen), potential crash
        if current_hash - initial_hash <= similarity_threshold:
            print(f"Potential crash detected at state {i} ({state_file})")
            
            crash_info = {
                "state_index": i,
                "state_file": state_file,
                "hash_difference": int(current_hash - initial_hash),
                "events": []
            }
            
            # Find the corresponding event
            if i < len(event_files):
                event_file = os.path.join(events_path, event_files[i])
                with open(event_file) as f:
                    event_data = json.load(f)
                for event in event_data:
                    print(f"{event} : {event_data[event]}")
                    crash_info["events"].append({
                        "event_type": event,
                        "event_data": event_data[event]
                    })
            
            result["crashes"].append(crash_info)
    
    return result

def save_results(results, output_dir):
    """Save crash results to a JSON file"""
    output_file = os.path.join(output_dir, "crash_logs.json")
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=4)
    print(f"\nCrash results saved to {output_file}")

def parse_args():
    parser = argparse.ArgumentParser(description='Detect app crashes from DroidBot output.')
    parser.add_argument('output_dir', help='Path to the output directory (e.g., "output/apkName")')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    
    if not os.path.exists(args.output_dir):
        print(f"Error: output directory not found at {args.output_dir}")
        exit(1)
    
    results = detect_crashes(args.output_dir)  # Threshold is now fixed at 5
    
    if results["crashes"]:
        print(f"\nDetected {len(results['crashes'])} potential crash(es)")
        save_results(results, args.output_dir)
    else:
        print("\nNo crashes detected")
        # Still save empty result for record keeping
        save_results(results, args.output_dir)
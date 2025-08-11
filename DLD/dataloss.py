import os
import json
from PIL import Image
import imagehash
from datetime import datetime

class StateLossDetector:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.events_dir = os.path.join(output_dir, "events")
        self.states_dir = os.path.join(output_dir, "states")
        self.results = {
            "metadata": {
                "analysis_time": datetime.now().isoformat(),
                "tool": "honeynet/droidbot",
                "analysis_type": "UI state loss detection"
            },
            "issues": {
                "disappeared_dialogs": [],
                "edittext_value_changes": [],
                "activity_stack_changes": [],
                "view_visibility_changes": [],
                "state_hash_mismatches": 0
            },
            "statistics": {
                "total_event_state_pairs": 0,
                "state_transitions_analyzed": 0
            }
        }
        self.previous_state = None
        self.previous_views = {}

    def analyze(self):
        """Main analysis workflow"""
        if not os.path.exists(self.events_dir) or not os.path.exists(self.states_dir):
            raise FileNotFoundError("DroidBot output directories not found")

        event_files = sorted([f for f in os.listdir(self.events_dir) if f.endswith('.json')])
        state_files = sorted([f for f in os.listdir(self.states_dir) if f.endswith(('.png', '.jpg'))])

        # Pair events with subsequent states
        for i in range(min(len(event_files), len(state_files)-1)):
            event_file = event_files[i]
            state_file = state_files[i+1]  # State after event
            
            try:
                event_path = os.path.join(self.events_dir, event_file)
                state_path = os.path.join(self.states_dir, state_file)
                
                with open(event_path) as f:
                    event_data = json.load(f)
                
                current_state = self._analyze_state(state_path)
                self.results["statistics"]["total_event_state_pairs"] += 1
                
                if self.previous_state:
                    self._compare_states(event_data, current_state)
                
                self.previous_state = current_state
                
            except Exception as e:
                print(f"Error processing {event_file}/{state_file}: {str(e)}")
        
        return self.results

    def _analyze_state(self, state_path):
        """Analyze a single state screenshot"""
        state_hash = imagehash.average_hash(Image.open(state_path))
        return {
            "file": os.path.basename(state_path),
            "hash": str(state_hash),
            "timestamp": os.path.basename(state_path).split('_')[1].split('.')[0]
        }

    def _compare_states(self, event_data, current_state):
        """Compare consecutive states for anomalies"""
        self.results["statistics"]["state_transitions_analyzed"] += 1
        
        # 1. Check for significant visual changes that might indicate state loss
        hash_diff = imagehash.hex_to_hash(self.previous_state["hash"]) - \
                   imagehash.hex_to_hash(current_state["hash"])
        
        if hash_diff > 10:  # Threshold for significant visual change
            self.results["issues"]["state_hash_mismatches"] += 1
            self.results["issues"]["state_hash_mismatches"].append({
                "event": event_data.get("event", {}).get("event_type"),
                "previous_state": self.previous_state["file"],
                "current_state": current_state["file"],
                "hash_difference": int(hash_diff),
                "timestamp": current_state["timestamp"]
            })

        # 2. Check for specific UI element changes if available in event data
        if "view" in event_data.get("event", {}):
            current_view = event_data["event"]["view"]
            view_id = current_view.get("resource_id") or current_view.get("signature")
            
            if view_id in self.previous_views:
                previous_view = self.previous_views[view_id]
                
                # Detect disappeared dialogs
                if (previous_view.get("class", "").lower().endswith("dialog") and 
                    not current_view.get("visible", True)):
                    self.results["issues"]["disappeared_dialogs"].append({
                        "view": view_id,
                        "event": event_data["event"]["event_type"],
                        "timestamp": current_state["timestamp"]
                    })
                
                # Detect EditText value changes
                if (previous_view.get("class", "").lower() == "android.widget.edittext" and
                    previous_view.get("text") != current_view.get("text")):
                    self.results["issues"]["edittext_value_changes"].append({
                        "view": view_id,
                        "previous_text": previous_view.get("text"),
                        "current_text": current_view.get("text"),
                        "timestamp": current_state["timestamp"]
                    })
            
            self.previous_views[view_id] = current_view

def save_results(results, output_dir):
    """Save analysis results to JSON file"""
    output_file = os.path.join(output_dir, "state_loss_analysis.json")
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"State loss analysis saved to {output_file}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Detect UI state loss in DroidBot output')
    parser.add_argument('output_dir', help='Path to DroidBot output directory')
    args = parser.parse_args()
    
    try:
        detector = StateLossDetector(args.output_dir)
        results = detector.analyze()
        
        # Print summary
        print("\nUI State Loss Analysis Summary")
        print(f"Analyzed {results['statistics']['state_transitions_analyzed']} state transitions")
        print("\nDetected Issues:")
        print(f"Disappeared dialogs: {len(results['issues']['disappeared_dialogs'])}")
        print(f"EditText value changes: {len(results['issues']['edittext_value_changes'])}")
        print(f"Significant state changes: {results['issues']['state_hash_mismatches']}")
        
        save_results(results, args.output_dir)
        
    except Exception as e:
        print(f"Error during analysis: {str(e)}")
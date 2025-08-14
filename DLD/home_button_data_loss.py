import os
import json
import argparse
from PIL import Image
import imagehash
from datetime import datetime

def detect_data_loss(output_dir, similarity_threshold=10):
    """
    Detect potential data loss by comparing before/after screenshots of home button actions.
    
    Args:
        output_dir: Path to the output directory (e.g., "output/apk_name")
        similarity_threshold: Maximum hash difference to consider states similar
        
    Returns:
        Dictionary containing data loss information, metadata, and counters
    """
    screenshots_path = os.path.join(output_dir, "home_button_screenshots")
    
    # Initialize result dictionary with counters
    result = {
        "metadata": {
            "output_dir": output_dir,
            "analysis_time": datetime.now().isoformat(),
            "similarity_threshold": similarity_threshold
        },
        "statistics": {
            "total_actions_analyzed": 0,
            "potential_data_loss": 0,
            "data_loss_rate": 0.0
        },
        "actions": []
    }
    
    # Get all before screenshots
    before_files = sorted([f for f in os.listdir(screenshots_path) 
                         if f.startswith('before_') and f.endswith('.png')])
    
    if not before_files:
        print(f"No home button screenshots found in {screenshots_path}")
        return result
    
    # Process each home button action
    for before_file in before_files:
        # Extract action number
        action_num = before_file.split('_')[1].split('.')[0]
        after_file = f"after_{action_num}.png"
        after_path = os.path.join(screenshots_path, after_file)
        before_path = os.path.join(screenshots_path, before_file)
        
        if not os.path.exists(after_path):
            print(f"Missing after image for action {action_num}")
            continue
        
        # Open images
        before_img = Image.open(before_path)
        after_img = Image.open(after_path)
        
        # Calculate image hashes
        before_hash = imagehash.average_hash(before_img)
        after_hash = imagehash.average_hash(after_img)
        hash_diff = before_hash - after_hash
        
        # Determine if potential data loss
        is_potential_data_loss = hash_diff > similarity_threshold
        
        # Create action entry
        action_info = {
            "action_index": int(action_num),
            "before_image": before_file,
            "after_image": after_file,
            "hash_difference": int(hash_diff),
            "is_potential_data_loss": is_potential_data_loss
        }
        
        result["actions"].append(action_info)
        result["statistics"]["total_actions_analyzed"] += 1
        
        if is_potential_data_loss:
            result["statistics"]["potential_data_loss"] += 1
            print(f"Potential data loss detected in action {action_num} (diff: {hash_diff})")
    
    # Calculate data loss rate
    if result["statistics"]["total_actions_analyzed"] > 0:
        result["statistics"]["data_loss_rate"] = round(
            result["statistics"]["potential_data_loss"] / result["statistics"]["total_actions_analyzed"],
            4
        )
    
    return result
def save_results(results, output_dir):
    """Save data loss results to a JSON file"""
    output_file = os.path.join(output_dir, "home_button_data_loss.json")
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=4)
    print(f"\nData loss results saved to {output_file}")

def parse_args():
    parser = argparse.ArgumentParser(description='Detect potential data loss from home button simulations.')
    parser.add_argument('output_dir', help='Path to the output directory (e.g., "output/apkName")')
    parser.add_argument('--threshold', type=int, default=10,
                        help='Hash difference threshold for potential data loss (default: 10)')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    
    if not os.path.exists(args.output_dir):
        print(f"Error: output directory not found at {args.output_dir}")
        exit(1)
    
    # Check if screenshots directory exists
    screenshots_dir = os.path.join(args.output_dir, "home_button_screenshots")
    if not os.path.exists(screenshots_dir):
        print(f"Error: home_button_screenshots directory not found in {args.output_dir}")
        exit(1)
    
    results = detect_data_loss(args.output_dir, args.threshold)
    
    # Print summary statistics
    print("\nHome Button Data Loss Analysis Summary")
    print(f"\tTotal actions analyzed: {results['statistics']['total_actions_analyzed']}")
    print(f"\tPotential data loss detected: {results['statistics']['potential_data_loss']}")
    print(f"\tData loss rate: {results['statistics']['data_loss_rate'] * 100:.2f}%")
    
    # Save results regardless of findings
    save_results(results, args.output_dir)
import subprocess
import time
import random

def rotate_emulator():
    """Rotate emulator using physical rotation commands"""
    orientations = [
        ("portrait", "0° (Portrait)"),
        ("landscape", "90° (Landscape)"),
        ("landscape", "270° (Reverse Landscape)")  # Achieved via double rotation
    ]
    
    print("Starting physical rotation...")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            # Choose random orientation
            orientation, description = random.choice(orientations)
            print(f"Rotating to {description}...")
            
            # Single rotation command
            subprocess.run(
                ["adb", "emu", "rotate", orientation],
                check=True,
                timeout=5
            )
            
            # For reverse landscape, rotate twice
            if description == "270° (Reverse Landscape)":
                time.sleep(5)
                subprocess.run(
                    ["adb", "emu", "rotate", orientation],
                    check=True,
                    timeout=5
                )
            
            print(f"Successfully rotated to {description}")
            time.sleep(random.uniform(3, 8))  # Random delay 3-8 seconds
            
    except KeyboardInterrupt:
        print("\nResetting to portrait...")
        subprocess.run(["adb", "emu", "rotate", "portrait"])

if __name__ == "__main__":
    rotate_emulator()
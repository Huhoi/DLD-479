# Prerequisite
- Need to have Python 3.9 (3.13 does not work. IDK about other versions)
- Android emulator needs to on Android SDK/API 31 or older
- Can use android studio or another emulator just need to have the emulator running
- Need to use androguard version 3.4.0a1

# Python Packages
 - Ensure the following has been installed before running:
    - pip install Pillow imagehash
    - pip install androguard==3.4.0a1
    - pip install watchdog
    - pip install opencv-python
    - pip install numpy
    - pip install e .
      - Run this inside the droidbot folder (cd droidbot)

# How to Run
- Have emulator running
- Be in the root of the project
- Run Either of the Following (DO NOT RUN start.py in droidbot):
  - ***python DLD/startDLD.py --apk-path apkFileDirectory --no-home-button*** (To simulate both rotate and power_cycle)
  - ***python DLD/startDLD.py --apk-path apkFileDirectory --no-rotate --no-power-cycle*** (to simulate only home-button)
  - Add -t <time-in-seconds> to add how long you wish to run the program for (default to 120 seconds).
- Ctrl + C to stop.
- Output should be in "output/**apk_name**"

# Possible Conflicts and Fixes
## Missing Environment Variables
On windows, before running `startDLD.py`, make sure `adb` is available on your PATH.
You can add it with the following command:
```
$env:ANDROID_SDK_ROOT = "C:\Users\YOUR-USERNAME\AppData\Local\Android\Sdk"
$env:PATH = "$env:ANDROID_SDK_ROOT\platform-tools;$env:ANDROID_SDK_ROOT\emulator;$env:ANDROID_SDK_ROOT\cmdline-tools\latest\bin;$env:PATH"

# Check version and if its setup
adb version
```

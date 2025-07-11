# Prerequisite
- Need to have Python 3.9 (3.13 does not work. IDK about other versions)
- Android emulator needs to on Android SDK/API 31 or older
- Can use android studio or another emulator just need to have the emulator running
- Need to use androguard version 3.4.0a1 (pip install androguard==3.4.0a1)

# Python Packages
- pip install Pillow imagehash
- cd droidbot
    - pip install e .
- (Maybe make an install.py?)

# How to Run
- Have emulator running
- Be in the root of the project
- Run ***DLD/startDLD.py apk_path***  (NOT start.py in droidbot)
- Ctrl + C to stop.
- Output should be in "output/**apk_name**"

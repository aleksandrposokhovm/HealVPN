import os

# Emulate handlers.py logic
current_dir = "/Users/aleksandrposokhov/Life/02_Business/01_HealVPN/bot"
LOGO_PATH = os.path.normpath(os.path.join(
    current_dir,
    "..", "website", "assets", "logo_horizontal.png"
))

print(f"Computed LOGO_PATH: {LOGO_PATH}")
print(f"Exists: {os.path.exists(LOGO_PATH)}")

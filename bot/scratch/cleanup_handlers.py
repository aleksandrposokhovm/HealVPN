import sys

path = '/Users/aleksandrposokhov/Life/02_Business/01_HealVPN/bot/handlers.py'
with open(path, 'r') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    # If we see the mess my script made, we skip and insert clean version
    if 'if query.message.photo:' in line and i + 1 < len(lines) and 'if query.message.photo:' in lines[i+1]:
        # This is the double nested mess
        continue 
    # Actually, I'll just rebuild the key parts
    new_lines.append(line)

# Wait, this is too complex.
# I'll just use a simple regex to remove the double if and fix the else.
content = "".join(lines)
import re

# Fix the specific mess: if query.message.photo:\n    if query.message.photo:
content = re.sub(r'if query\.message\.photo:\s+if query\.message\.photo:', 'if query.message.photo:', content)

with open(path, 'w') as f:
    f.write(content)

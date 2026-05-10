import sys
import re

path = '/Users/aleksandrposokhov/Life/02_Business/01_HealVPN/bot/handlers.py'
with open(path, 'r') as f:
    content = f.read()

def wrap_edit(match):
    indent = match.group(1)
    call_type = match.group(2) # edit_message_caption
    args = match.group(3)
    
    # Try to extract caption/text and reply_markup
    # This is a bit simplified but should work for our cases
    return f"""{indent}if query.message.photo:
{indent}    await query.edit_message_caption({args})
{indent}else:
{indent}    # Convert caption to text for edit_message_text
{indent}    await query.edit_message_text({args.replace('caption=', 'text=')})"""

# Find all await query.edit_message_caption(...)
# This regex matches the whole call including multi-lines
pattern = r'(\s+)await query\.(edit_message_caption)\((.*?)\)'
# We need DOTALL to match multi-line arguments
new_content = re.sub(pattern, wrap_edit, content, flags=re.DOTALL)

with open(path, 'w') as f:
    f.write(new_content)
print("Success")

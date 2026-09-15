import re
import os
import html
import urllib.request
import hashlib
import json
from datetime import datetime

# Get the exact directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define absolute paths based on the script's location
images_folder = os.path.join(BASE_DIR, 'images')
feed_path = os.path.join(BASE_DIR, 'feed.xml')
metadata_path = os.path.join(BASE_DIR, 'feed_metadata.json')

# Create the images directory inside paradigmal-bulten if it doesn't exist
os.makedirs(images_folder, exist_ok=True)

# Read the generated feed.xml
try:
    with open(feed_path, 'r', encoding='utf-8') as f:
        content = f.read()
except FileNotFoundError:
    print(f"feed.xml not found at {feed_path}. Exiting.")
    exit(1)

# Find all raw image URLs in the XML content
# FIXED: Added `instagram\.com/p/[^"\'<>\s]+/media` to catch single-image and video poster endpoints
img_urls = re.findall(r'(https?://[^"\'<>\s]*(?:scontent|cdninstagram|fbcdn|instagram\.com/p/[^"\'<>\s]+/media)[^"\'<>\s]*)', content)

for raw_url in set(img_urls):
    try:
        # Clean up XML/HTML entities that the regex might have over-captured
        clean_raw = raw_url
        if clean_raw.endswith('&quot;'):
            clean_raw = clean_raw[:-6]
        if clean_raw.endswith('&lt;'):
            clean_raw = clean_raw[:-4]
            
        # 1. Decode HTML entities to restore the real URL signature
        clean_url = html.unescape(clean_raw)
        
        # 2. Create a unique filename based on the cleaned URL
        filename = hashlib.md5(clean_url.encode()).hexdigest() + '.jpg'
        filepath = os.path.join(images_folder, filename)
        
        # 3. Download the image if it doesn't already exist locally
        if not os.path.exists(filepath):
            print(f"Downloading {filename}...")
            req = urllib.request.Request(
                clean_url, 
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'
                }
            )
            with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())
        
        # 4. Replace using the CLEANED raw string in the XML
        content = content.replace(clean_raw, f'images/{filename}')
        
    except Exception as e:
        print(f"Failed to download image {clean_raw}: {e}")


# Save the updated feed.xml
with open(feed_path, 'w', encoding='utf-8') as f:
    f.write(content)

# Write timestamp metadata for display in HTML
timestamp_data = {
    'last_updated': datetime.utcnow().isoformat() + 'Z',
    'last_updated_readable': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
}

with open(metadata_path, 'w', encoding='utf-8') as f:
    json.dump(timestamp_data, f)

print("Finished processing images.")
print(f"Timestamp saved: {timestamp_data['last_updated_readable']}")

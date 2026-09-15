import re
import os
import html
import urllib.request
import hashlib
import json
import tempfile
from PIL import Image
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

# Get the exact directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define absolute paths based on the script's location
images_folder = os.path.join(BASE_DIR, 'images')
feed_path = os.path.join(BASE_DIR, 'feed.xml')
metadata_path = os.path.join(BASE_DIR, 'feed_metadata.json')

# Create the images directory inside paradigmal-bulten if it doesn't exist
os.makedirs(images_folder, exist_ok=True)

MAX_IMAGE_SIZE = 1600
JPEG_QUALITY = 80


def optimize_image(filepath):
    with Image.open(filepath) as image:
        image.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE), Image.Resampling.LANCZOS)
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')

        fd, temp_path = tempfile.mkstemp(suffix='.jpg', dir=images_folder)
        os.close(fd)
        try:
            image.save(temp_path, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True)
            os.replace(temp_path, filepath)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


def remove_unreferenced_images(feed_content):
    referenced_names = {
        match.group(1)
        for match in re.finditer(r'images/([^"\'<>\s]+)', feed_content)
    }
    removed_count = 0
    removed_bytes = 0

    for entry in os.scandir(images_folder):
        if not entry.is_file() or entry.name in referenced_names:
            continue
        removed_bytes += entry.stat().st_size
        os.remove(entry.path)
        removed_count += 1

    return removed_count, removed_bytes

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
        downloaded = False
        
        # 3. Download the image if it doesn't already exist locally
        if not os.path.exists(filepath):
            print(f"Downloading {filename}...")
            request_url = quote(clean_url, safe=':/?&=%;,+-._~')
            req = urllib.request.Request(
                request_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'
                }
            )
            with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())
            downloaded = True

        if downloaded:
            optimize_image(filepath)
        
        # 4. Replace using the CLEANED raw string in the XML
        content = content.replace(clean_raw, f'images/{filename}')
        
    except Exception as e:
        print(f"Failed to download image {clean_raw}: {e}")


# Save the updated feed.xml
with open(feed_path, 'w', encoding='utf-8') as f:
    f.write(content)

removed_count, removed_bytes = remove_unreferenced_images(content)
print(f"Removed {removed_count} unreferenced images ({removed_bytes / 1024 / 1024:.2f} MB).")

# Write timestamp metadata for display in HTML (using Turkey timezone UTC+3)
turkey_tz = ZoneInfo('Europe/Istanbul')
now_turkey = datetime.now(turkey_tz)

timestamp_data = {
    'last_updated': now_turkey.isoformat(),
    'last_updated_readable': now_turkey.strftime('%Y-%m-%d %H:%M:%S %Z')
}

with open(metadata_path, 'w', encoding='utf-8') as f:
    json.dump(timestamp_data, f)

print("Finished processing images.")
print(f"Timestamp saved: {timestamp_data['last_updated_readable']}")

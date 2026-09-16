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
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import time
import sys

# Get the exact directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define absolute paths based on the script's location
images_folder = os.path.join(BASE_DIR, 'images')
feed_path = os.path.join(BASE_DIR, 'feed.xml')
metadata_path = os.path.join(BASE_DIR, 'feed_metadata.json')
processed_urls_path = os.path.join(BASE_DIR, '.processed_urls')

# Create the images directory inside paradigmal-bulten if it doesn't exist
os.makedirs(images_folder, exist_ok=True)

MAX_IMAGE_SIZE = 1600
JPEG_QUALITY = 80
MAX_WORKERS = 5  # Number of concurrent download threads
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds, increases exponentially


# Thread-safe lock for file operations
content_lock = Lock()


def load_processed_urls():
    """Load the set of already processed image URLs."""
    try:
        with open(processed_urls_path, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()


def save_processed_urls(urls):
    """Save the set of processed image URLs for next run."""
    with open(processed_urls_path, 'w', encoding='utf-8') as f:
        for url in sorted(urls):
            f.write(url + '\n')


def download_with_retry(url, filepath, max_retries=MAX_RETRIES):
    """
    Download image with exponential backoff retry logic.
    Returns True if successful, False otherwise.
    """
    for attempt in range(max_retries):
        try:
            request_url = quote(url, safe=':/?&=%;,+-._~')
            req = urllib.request.Request(
                request_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
                    'Timeout': '10'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())
            return True
            
        except urllib.error.HTTPError as e:
            # Don't retry on 404, 403, etc. - these won't change
            if e.code in [403, 404, 410]:
                raise
            # Retry on 500, 502, 503, 429 (rate limiting)
            if attempt < max_retries - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                print(f"  Retry attempt {attempt + 1}/{max_retries} for {os.path.basename(filepath)} (HTTP {e.code}), waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < max_retries - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                print(f"  Retry attempt {attempt + 1}/{max_retries} for {os.path.basename(filepath)}, waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise


def optimize_image(filepath):
    """Resize and optimize image for web."""
    try:
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
    except Exception as e:
        print(f"  Failed to optimize image {filepath}: {e}")


def download_and_process_image(url_info):
    """
    Worker function to download and process a single image.
    Returns tuple: (clean_raw, filename, success)
    """
    clean_raw, clean_url = url_info
    filename = hashlib.md5(clean_url.encode()).hexdigest() + '.jpg'
    filepath = os.path.join(images_folder, filename)
    
    # Check if already exists
    if os.path.exists(filepath):
        return (clean_raw, filename, True)
    
    try:
        print(f"Downloading {filename}...")
        download_with_retry(clean_url, filepath)
        optimize_image(filepath)
        return (clean_raw, filename, True)
        
    except Exception as e:
        print(f"Failed to download image {clean_raw}: {e}")
        # Clean up partial file if it exists
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass
        return (clean_raw, filename, False)


def remove_unreferenced_images(feed_content):
    """Remove images that are no longer referenced in the feed."""
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


# ============================================
# Main execution
# ============================================

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

# Clean and deduplicate URLs
urls_to_download = []
for raw_url in set(img_urls):
    # Clean up XML/HTML entities that the regex might have over-captured
    clean_raw = raw_url
    if clean_raw.endswith('&quot;'):
        clean_raw = clean_raw[:-6]
    if clean_raw.endswith('&lt;'):
        clean_raw = clean_raw[:-4]
        
    # Decode HTML entities to restore the real URL signature
    clean_url = html.unescape(clean_raw)
    urls_to_download.append((clean_raw, clean_url))

# Load previously processed URLs
processed_urls = load_processed_urls()

# Filter out URLs that have already been processed
new_urls = [(clean_raw, clean_url) for clean_raw, clean_url in urls_to_download if clean_url not in processed_urls]

print(f"Found {len(urls_to_download)} total unique images")
print(f"Already processed: {len(processed_urls)} images")
print(f"New images to download: {len(new_urls)}")

# Check if there are any new images to process
has_new_images = len(new_urls) > 0

# Download only new images in parallel
if has_new_images:
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all download tasks
        futures = {
            executor.submit(download_and_process_image, url_info): url_info 
            for url_info in new_urls
        }
        
        # Process completed downloads and update content
        for future in as_completed(futures):
            try:
                clean_raw, filename, success = future.result()
                if success:
                    with content_lock:
                        content = content.replace(clean_raw, f'images/{filename}')
            except Exception as e:
                url_info = futures[future]
                print(f"Worker error processing {url_info[1]}: {e}")
    
    print("All downloads completed.")
    
    # Save the updated feed.xml only if there were new images
    with open(feed_path, 'w', encoding='utf-8') as f:
        f.write(content)
else:
    print("No new images to download. Skipping image processing.")

# Always remove unreferenced images and update cleanup logs
removed_count, removed_bytes = remove_unreferenced_images(content)
print(f"Removed {removed_count} unreferenced images ({removed_bytes / 1024 / 1024:.2f} MB).")

# Update processed URLs with all current URLs (including already processed ones)
all_processed = processed_urls | {url for _, url in urls_to_download}
save_processed_urls(all_processed)

# Always update timestamp metadata (signals workflow is active)
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

# Exit with status indicating if new images were processed
sys.exit(0 if has_new_images else 42)

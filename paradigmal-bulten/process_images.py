import re
import os
import html
import urllib.request
import hashlib
import json
import tempfile
from PIL import Image
from datetime import datetime
from urllib.parse import quote, urlparse, parse_qs, urlencode
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

# Create the images directory inside paradigmal-bulten if it doesn't exist
os.makedirs(images_folder, exist_ok=True)

MAX_IMAGE_SIZE = 1600
JPEG_QUALITY = 80
MAX_WORKERS = 5  # Number of concurrent download threads
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds, increases exponentially


# Thread-safe lock for file operations
content_lock = Lock()


def load_metadata():
    """Load metadata including processed image filenames."""
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_metadata(metadata):
    """Save metadata including processed image filenames."""
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)


def normalize_url(url):
    """
    Normalize URL for consistent comparison.
    Handles lowercase, trailing whitespace, and URL encoding inconsistencies.
    """
    return url.lower().strip()


def get_image_filename(url):
    """Generate the consistent filename for an image URL."""
    return hashlib.md5(normalize_url(url).encode()).hexdigest() + '.jpg'


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
    filename = get_image_filename(clean_url)
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


def remove_unreferenced_images(feed_content, original_urls):
    """Remove images that are no longer referenced in the feed."""
    # Check for both local image references AND original raw URLs
    referenced_names = {
        match.group(1)
        for match in re.finditer(r'images/([^"\'<>\s]+)', feed_content)
    }
    
    # Also keep images if their original URLs are still in the feed
    for url in original_urls:
        if url in feed_content:
            # Extract the filename that was generated from this URL
            filename = get_image_filename(url)
            referenced_names.add(filename)
    
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

# Load metadata and previously processed image filenames
metadata = load_metadata()
processed_filenames = set(metadata.get('processed_image_filenames', []))

# Filter out URLs that have already been processed (by checking if filename exists)
new_urls = [
    (clean_raw, clean_url) for clean_raw, clean_url in urls_to_download 
    if get_image_filename(clean_url) not in processed_filenames
]

print(f"Found {len(urls_to_download)} total unique images")
print(f"Already processed: {len(processed_filenames)} images")
print(f"New images to download: {len(new_urls)}")

# Check if there are any new images to process
has_new_images = len(new_urls) > 0

# Download only new images in parallel
if has_new_images:
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_and_process_image, url_info): url_info 
            for url_info in new_urls
        }
        
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
removed_count, removed_bytes = remove_unreferenced_images(content, {url for _, url in urls_to_download})
print(f"Removed {removed_count} unreferenced images ({removed_bytes / 1024 / 1024:.2f} MB).")

# Update metadata with all current image filenames (including already processed ones)
# Generate filenames for all discovered URLs
all_processed_filenames = {get_image_filename(url) for _, url in urls_to_download}
combined_filenames = processed_filenames | all_processed_filenames

# Always update timestamp metadata (signals workflow is active)
turkey_tz = ZoneInfo('Europe/Istanbul')
now_turkey = datetime.now(turkey_tz)

metadata['last_updated'] = now_turkey.isoformat()
metadata['last_updated_readable'] = now_turkey.strftime('%Y-%m-%d %H:%M:%S %Z')
metadata['processed_image_filenames'] = sorted(list(combined_filenames))
metadata['total_processed_count'] = len(combined_filenames)

save_metadata(metadata)

print("Finished processing images.")
print(f"Timestamp saved: {metadata['last_updated_readable']}")
print(f"Total images tracked: {metadata['total_processed_count']}")

# Exit with status indicating if new images were processed
sys.exit(0 if has_new_images else 42)

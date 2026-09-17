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
    parsed = urlparse(url.lower().strip())
    # Reconstruct without query string for all Meta/Instagram CDNs
    cdn_domains = ['cdninstagram.com', 'scontent', 'fbcdn.net']
    if any(cdn in parsed.netloc for cdn in cdn_domains):
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
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
            if e.code in [403, 404, 410]:
                raise
            if attempt < max_retries - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
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
    
    if os.path.exists(filepath):
        return (clean_raw, filename, True)
    
    try:
        print(f"Downloading {filename}...")
        download_with_retry(clean_url, filepath)
        optimize_image(filepath)
        return (clean_raw, filename, True)
        
    except Exception as e:
        print(f"Failed to download image {clean_raw}: {e}")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass
        return (clean_raw, filename, False)


def remove_unreferenced_images(feed_content, original_urls):
    """Remove images that are no longer referenced in the feed."""
    referenced_names = {
        match.group(1)
        for match in re.finditer(r'images/([^"\'<>\s]+)', feed_content)
    }
    
    for url in original_urls:
        if url in feed_content:
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

try:
    with open(feed_path, 'r', encoding='utf-8') as f:
        content = f.read()
except FileNotFoundError:
    print(f"feed.xml not found at {feed_path}. Exiting.")
    sys.exit(1)

# --- CAROUSEL STRIPPER ---
# Remove all but the first image tag from each feed item to prevent carousel bloat
def limit_images_per_item(match):
    item_html = match.group(0)
    img_tags = re.findall(r'<img[^>]+>', item_html, re.IGNORECASE)
    
    if len(img_tags) > 1:
        first_img = img_tags[0]
        placeholder = "___FIRST_IMG_PLACEHOLDER___"
        # Temporarily protect the first image
        item_html = item_html.replace(first_img, placeholder, 1)
        
        # Erase all remaining image tags in this item
        item_html = re.sub(r'<img[^>]+>', '', item_html, flags=re.IGNORECASE)
        
        # Restore the protected first image
        item_html = item_html.replace(placeholder, first_img, 1)
        
    return item_html

content = re.sub(r'<item>.*?</item>|<entry>.*?</entry>', limit_images_per_item, content, flags=re.DOTALL | re.IGNORECASE)
# -------------------------

# Find all raw image URLs in the cleaned XML content
img_urls = re.findall(r'(https?://[^"\'<>\s]*(?:scontent|cdninstagram|fbcdn|instagram\.com/p/[^"\'<>\s]+/media)[^"\'<>\s]*)', content)

urls_to_download = []
for raw_url in set(img_urls):
    clean_raw = raw_url
    if clean_raw.endswith('&quot;'):
        clean_raw = clean_raw[:-6]
    if clean_raw.endswith('&lt;'):
        clean_raw = clean_raw[:-4]
        
    clean_url = html.unescape(clean_raw)
    urls_to_download.append((clean_raw, clean_url))

metadata = load_metadata()
processed_filenames = set(metadata.get('processed_image_filenames', []))

new_urls = []
for clean_raw, clean_url in urls_to_download:
    filename = get_image_filename(clean_url)
    filepath = os.path.join(images_folder, filename)

    if os.path.exists(filepath):
        content = content.replace(clean_raw, f'images/{filename}')
    else:
        new_urls.append((clean_raw, clean_url))

print(f"Found {len(urls_to_download)} total unique images")
print(f"Already processed (cached): {len(urls_to_download) - len(new_urls)} images")
print(f"New images to download: {len(new_urls)}")

has_new_images = len(new_urls) > 0

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
else:
    print("No new images to download.")

# Save the updated feed.xml
with open(feed_path, 'w', encoding='utf-8') as f:
    f.write(content)

removed_count, removed_bytes = remove_unreferenced_images(content, {url for _, url in urls_to_download})
print(f"Removed {removed_count} unreferenced images ({removed_bytes / 1024 / 1024:.2f} MB).")

all_processed_filenames = {get_image_filename(url) for _, url in urls_to_download}
combined_filenames = processed_filenames | all_processed_filenames

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

sys.exit(0)

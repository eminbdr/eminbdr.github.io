import re
import os
import urllib.request
import hashlib

# Get the exact directory where this script is located (the paradigmal-bulten folder)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define absolute paths based on the script's location
images_folder = os.path.join(BASE_DIR, 'images')
feed_path = os.path.join(BASE_DIR, 'feed.xml')

# Create the images directory inside paradigmal-bulten if it doesn't exist
os.makedirs(images_folder, exist_ok=True)

# Read the generated feed.xml
try:
    with open(feed_path, 'r', encoding='utf-8') as f:
        content = f.read()
except FileNotFoundError:
    print(f"feed.xml not found at {feed_path}. Exiting.")
    exit(1)

# Find all image URLs (specifically targeting Instagram/Facebook CDNs)
img_urls = re.findall(r'(https?://[^"\'<>\s]*(?:scontent|cdninstagram|fbcdn)[^"\'<>\s]*)', content)

for url in set(img_urls):
    try:
        # Create a unique filename based on the URL
        filename = hashlib.md5(url.encode()).hexdigest() + '.jpg'
        filepath = os.path.join(images_folder, filename)
        
        # Download the image if we haven't already
        if not os.path.exists(filepath):
            print(f"Downloading {filename}...")
            # Use a standard User-Agent to avoid getting blocked during download
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())
        
        # Replace the remote URL in the XML with the relative local path
        # Note: We keep 'images/{filename}' here because index.html and feed.xml 
        # are right next to the images folder, so standard relative links work perfectly.
        content = content.replace(url, f'images/{filename}')
        
    except Exception as e:
        print(f"Failed to download {url}: {e}")

# Save the updated feed.xml
with open(feed_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Finished processing images in the paradigmal-bulten folder.")

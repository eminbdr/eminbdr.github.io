import re
import os
import urllib.request
import hashlib

# Create an images directory if it doesn't exist
os.makedirs('images', exist_ok=True)

# Read the generated feed.xml
try:
    with open('feed.xml', 'r', encoding='utf-8') as f:
        content = f.read()
except FileNotFoundError:
    print("feed.xml not found. Exiting.")
    exit(1)

# Find all image URLs (specifically targeting Instagram/Facebook CDNs)
# It looks for URLs starting with http and containing scontent or cdninstagram
img_urls = re.findall(r'(https?://[^"\'<>\s]*(?:scontent|cdninstagram|fbcdn)[^"\'<>\s]*)', content)

for url in set(img_urls):
    try:
        # Create a unique filename based on the URL
        filename = hashlib.md5(url.encode()).hexdigest() + '.jpg'
        filepath = os.path.join('images', filename)
        
        # Download the image if we haven't already
        if not os.path.exists(filepath):
            print(f"Downloading {filename}...")
            # Use a standard User-Agent to avoid getting blocked during download
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())
        
        # Replace the remote URL in the XML with the local path
        content = content.replace(url, f'images/{filename}')
        
    except Exception as e:
        print(f"Failed to download {url}: {e}")

# Save the updated feed.xml
with open('feed.xml', 'w', encoding='utf-8') as f:
    f.write(content)

print("Finished processing images.")

#!/bin/bash
set -e

# Define dynamic local paths
BASE_DIR="$(pwd)"
FEED_DIR="$BASE_DIR/paradigmal-bulten"
RAW_DIR="$BASE_DIR/.raw_feeds"
RSS_BRIDGE_DIR="$BASE_DIR/rss-bridge"

echo "Initializing build environment..."
mkdir -p "$RAW_DIR"
mkdir -p "$FEED_DIR"

# Clone RSS-Bridge locally if it doesn't exist
if [ ! -d "$RSS_BRIDGE_DIR" ]; then
    echo "RSS-Bridge not found locally. Cloning..."
    git checkout "source_branch"
    echo "Pulling latest changes from source_branch..."
    git clone --depth 1 https://github.com/RSS-Bridge/rss-bridge.git "$RSS_BRIDGE_DIR"
    
    # NEW: Delete the nested .git folder to prevent submodule crashes in GitHub Actions
    rm -rf "$RSS_BRIDGE_DIR/.git"
fi

# 1. DIRECT RSS FEEDS (cURL)
DIRECT_FEEDS=(
)

i=0
for url in "${DIRECT_FEEDS[@]}"; do
    echo "Fetching Direct Feed: $url"
    curl -sL "$url" > "$RAW_DIR/direct_$i.xml" || true
    i=$((i+1))
done

# JSON'dan sadece kullanıcı adlarını (anahtarları) çek
INSTAGRAM_USERS=($(jq -r '.instagram | keys[]' "$BASE_DIR/sources.json"))

j=0
for user in "${INSTAGRAM_USERS[@]}"; do
    echo "Fetching Instagram Feed: @$user"
    php "$RSS_BRIDGE_DIR/index.php" action=display bridge=Instagram context=Username u="$user" media_type=all format=Mrss > "$RAW_DIR/insta_$j.xml" &
    j=$((j+1))
done
wait

# 3. MERGE ALL FEEDS
echo "Merging feeds..."
php -r "
  \$master = new SimpleXMLElement('<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel><title>Unified Feed</title></channel></rss>');
  \$targetDom = dom_import_simplexml(\$master->channel);

  foreach (glob('$RAW_DIR/*.xml') as \$file) {
      libxml_use_internal_errors(true);
      \$xml = simplexml_load_file(\$file);
      if (!\$xml) continue;

      \$channelTitle = (string)(\$xml->channel->title ?? \$xml->title ?? 'News Source');
      \$items = \$xml->xpath('//item | //entry');

      if (\$items) {
          foreach (\$items as \$item) {
              \$domNode = dom_import_simplexml(\$item);
              \$srcNode = \$domNode->ownerDocument->createElement('sourceTitle', htmlspecialchars(\$channelTitle));
              \$domNode->appendChild(\$srcNode);

              \$imported = \$targetDom->ownerDocument->importNode(\$domNode, true);
              \$targetDom->appendChild(\$imported);
          }
      }
  }
  \$master->asXML('$FEED_DIR/feed.xml');
"

# 4. RUN PYTHON IMAGE PROCESSOR
echo "Processing Images..."
if command -v python3 &>/dev/null; then
    python3 "$BASE_DIR/process_images.py"
else
    python "$BASE_DIR/process_images.py"
fi

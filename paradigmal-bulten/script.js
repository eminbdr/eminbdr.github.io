// Restore layout preference on load (defaults to List View)
if (localStorage.getItem("preferred_view") === "card") {
  document.getElementById("news-feed").classList.add("card-view");
  document.getElementById("view-toggle-btn").innerText = "Liste Görünümü";
}

// Define available views
const views = ["list", "card", "scroll"];
let currentViewIndex = 0;

// Restore layout preference on load (defaults to List View)
const savedView = localStorage.getItem("preferred_view") || "list";
currentViewIndex =
  views.indexOf(savedView) !== -1 ? views.indexOf(savedView) : 0;
applyView(views[currentViewIndex]);

function toggleView() {
  // Cycle to the next view index
  currentViewIndex = (currentViewIndex + 1) % views.length;
  const newView = views[currentViewIndex];

  applyView(newView);
  localStorage.setItem("preferred_view", newView);
}

function applyView(viewMode) {
  const feed = document.getElementById("news-feed");
  const btn = document.getElementById("view-toggle-btn");

  // Reset classes
  feed.classList.remove("card-view", "scroll-view");

  if (viewMode === "card") {
    feed.classList.add("card-view");
    btn.innerText = "Kaydırma Görünümü"; // Indicates next mode
  } else if (viewMode === "scroll") {
    feed.classList.add("scroll-view");
    btn.innerText = "Liste Görünümü"; // Indicates next mode
  } else {
    // List view is default (no extra class)
    btn.innerText = "Kart Görünümü"; // Indicates next mode
  }
}

let activeFilters = new Set();
let sourceColors = {};

// 1. Önce merkezi yapılandırmayı çek (Hata yakalama eklendi ve yol düzeltildi)
fetch("sources.json", { cache: "no-store" })
  .then((res) => {
    if (!res.ok) throw new Error("sources.json dosyası bulunamadı (404)");
    return res.json();
  })
  .then((config) => {
    const sourceData = config.instagram || {};

    // 2. Metadata'yı çek
    fetch(`https://raw.githubusercontent.com/eminbdr/eminbdr.github.io/refs/heads/master/paradigmal-bulten/feed_metadata.json`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : {}))
      .then((metadata) => {
        if (metadata.last_updated_readable) {
          document.getElementById("update-time").textContent =
            `Last updated: ${metadata.last_updated_readable}`;
        }

        // 3. XML Feed'i çek
        return fetch(`https://raw.githubusercontent.com/eminbdr/eminbdr.github.io/refs/heads/master/paradigmal-bulten/feed.xml`, { cache: "no-store" });
      })
      .then((response) => {
        if (!response.ok) throw new Error("feed.xml dosyası bulunamadı");
        return response.text();
      })
      .then((str) => new window.DOMParser().parseFromString(str, "text/xml"))
      .then((xmlDoc) => {
        const items = Array.from(xmlDoc.querySelectorAll("item, entry"));
        if (items.length === 0) {
          document.getElementById("news-feed").innerHTML =
            "<p style='padding: 20px;'>No articles found.</p>";
          return;
        }

        // Tarihe göre sırala
        items.sort((a, b) => {
          const dateA =
            new Date(
              a.querySelector("pubDate, published, updated")?.textContent,
            ).getTime() || 0;
          const dateB =
            new Date(
              b.querySelector("pubDate, published, updated")?.textContent,
            ).getTime() || 0;
          return dateB - dateA;
        });

        // EKSİK OLAN SATIR EKLENDİ: Benzersiz kaynakları XML'den çek
        const uniqueSources = [
          ...new Set(
            items.map(
              (el) =>
                el.querySelector("sourceTitle")?.textContent || "News Source",
            ),
          ),
        ];

        // Create a wrapper for the toggle button and the filter list
        const filterWrapper = document.createElement("div");
        filterWrapper.className = "filter-wrapper";

        // Create the toggle button
        const filterToggleBtn = document.createElement("button");
        filterToggleBtn.className = "filter-toggle-btn";
        filterToggleBtn.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
          </svg>
          Kaynakları Filtrele
        `;

        // Create the actual filter bar container
        const filterBar = document.createElement("div");
        filterBar.className = "filter-bar collapsed"; // Start hidden

        // Toggle visibility on click
        filterToggleBtn.onclick = () => {
          filterBar.classList.toggle("collapsed");
        };

        filterWrapper.appendChild(filterToggleBtn);
        filterWrapper.appendChild(filterBar);
        // Butonları ve renkleri oluştur
        uniqueSources.forEach((source) => {
          const displaySourceName = source
            .replace(" - Instagram", "")
            .replace("@", "")
            .trim();

          // Rengi JSON'dan dinamik olarak al, yoksa varsayılan kullan
          const color = sourceData[displaySourceName]?.color || "#555555";
          sourceColors[source] = color;
          activeFilters.add(source); // Başlangıçta hepsi seçili olsun

          const btn = document.createElement("button");
          btn.className = "filter-btn";
          btn.style.backgroundColor = color;
          btn.innerText = displaySourceName;

          // Toggle logic
          btn.onclick = () => {
            if (activeFilters.has(source)) {
              activeFilters.delete(source);
              btn.classList.add("inactive");
            } else {
              activeFilters.add(source);
              btn.classList.remove("inactive");
            }
            applyFilters();
          };
          filterBar.appendChild(btn);
        });

        // Filtre barını sayfaya ekle
        const feedContainer = document.getElementById("news-feed");
        feedContainer.parentNode.insertBefore(filterWrapper, feedContainer);

        // Feed HTML'ini oluştur
        let feedHtml = "";
        items.forEach((el) => {
          const title = el.querySelector("title")?.textContent || "No title";
          const link =
            el.querySelector("link")?.getAttribute("href") ||
            el.querySelector("link")?.textContent ||
            "#";
          const sourceName =
            el.querySelector("sourceTitle")?.textContent || "News Source";
          const displaySourceName = sourceName
            .replace(" - Instagram", "")
            .replace("@", "")
            .trim();
          const contentText =
            el.querySelector("content, summary, description")?.textContent ||
            "";

          let imageUrl = "";
          const imgMatch = contentText.match(/<img[^>]+src=["']([^"']+)["']/i);
          const posterMatch = contentText.match(/poster=["']([^"']+)["']/i);

          if (imgMatch) imageUrl = imgMatch[1];
          else if (posterMatch) imageUrl = posterMatch[1];
          else {
            const media = el.querySelector("[url], enclosure[type^='image']");
            if (media)
              imageUrl =
                media.getAttribute("url") || media.getAttribute("href");
          }

          const parsedSnippetDoc = new window.DOMParser().parseFromString(
            contentText,
            "text/html",
          );
          const snippetText = (parsedSnippetDoc.body.textContent || "").trim();

          let dateStr = "";
          const pubDateNode = el.querySelector("pubDate, published, updated");
          if (pubDateNode) {
            const d = new Date(pubDateNode.textContent);
            if (!isNaN(d.getTime())) {
              const today = new Date();
              dateStr =
                d.toDateString() === today.toDateString()
                  ? d.toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
            }
          }

          // İkonu JSON'dan dinamik olarak al
          const iconUrl = sourceData[displaySourceName]?.icon || null;
          const cardColor = sourceColors[sourceName];

          feedHtml += `
          <a href="${link}" target="_blank" data-source="${sourceName}" class="article-card" style="border-left: 5px solid ${cardColor}">
            ${iconUrl ? `<img src="${iconUrl}" class="source-logo-badge" alt="${displaySourceName}" onload="this.classList.add('loaded')" onerror="this.style.display='none'" />` : ""}
            ${imageUrl ? `<img src="${imageUrl}" class="card-img" onload="this.classList.add('loaded')" onerror="this.style.display='none'" loading="lazy" />` : ""}
            <div class="article-overlay">
              <div class="article-title">${title}</div>
              ${snippetText ? `<div class="article-snippet">${snippetText}</div>` : ""}
              <div class="article-meta">
                <span style="color: ${cardColor}; font-weight: bold;">${displaySourceName}</span>
                <span>${dateStr}</span>
              </div>
            </div>
          </a>
        `;
        });

        document.getElementById("news-feed").innerHTML = feedHtml;
      });
  })
  .catch((err) => {
    console.error("Error loading feed:", err);
    document.getElementById("news-feed").innerHTML =
      `<p style='padding: 20px;'>Unable to load feeds: ${err.message}</p>`;
  });

function applyFilters() {
  document.querySelectorAll(".article-card").forEach((card) => {
    if (activeFilters.has(card.getAttribute("data-source"))) {
      card.style.display = "";
    } else {
      card.style.display = "none";
    }
  });
}

// App Installation Button Logic
let deferredPrompt;
const installBtn = document.getElementById("installBtn");

window.addEventListener("beforeinstallprompt", (e) => {
  // Save the event
  deferredPrompt = e;
  installBtn.style.display = "block";
});

installBtn.addEventListener("click", async () => {
  // SCENARIO 1: The prompt was already used and destroyed because they previously canceled.
  if (!deferredPrompt) {
    alert(
      "IOS cihazlarda uygulamayı kurmak için en alt ortada ki paylaş tuşuna bastıktan sonra, Ana Ekrana ekle butonuna basın",
    );
    return;
  }

  // SCENARIO 2: First time clicking the button
  try {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;

    if (outcome === "dismissed") {
      // The user clicked cancel.
      // The prompt is now dead, so we must nullify it.
      deferredPrompt = null;

      // We purposefully DO NOT hide the install button here.
      // If they change their mind and click it again, it will trigger Scenario 1.
    } else {
      // The user installed the app.
      deferredPrompt = null;
      installBtn.style.display = "none";
    }
  } catch (err) {
    // Failsafe if the browser default prompt was interacted with independently
    deferredPrompt = null;
    alert("Please use your browser's menu to install the app.");
  }
});

window.addEventListener("appinstalled", () => {
  deferredPrompt = null;
  installBtn.style.display = "none";
  console.log("PWA was installed successfully");
});

// version update
let refreshing = false;
navigator.serviceWorker.addEventListener("controllerchange", () => {
  if (!refreshing) {
    refreshing = true;
    window.location.reload();
  }
});

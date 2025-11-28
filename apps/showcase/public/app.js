// State
let currentWebtoon = null;
let currentChapter = null;
let totalChapters = 0;
let uiVisible = true;
let touchStartY = 0;
let currentCharacters = [];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  loadWebtoons();
  setupReaderGestures();
  handleRouting();
});

// Handle browser back/forward
window.addEventListener('popstate', handleRouting);

function handleRouting() {
  const hash = window.location.hash;

  if (hash.startsWith('#/read/')) {
    const parts = hash.replace('#/read/', '').split('/');
    if (parts.length >= 2) {
      const webtoonId = parts[0];
      const chapterNum = parseInt(parts[1]);
      openChapter(webtoonId, chapterNum, false);
    }
  } else if (hash.startsWith('#/webtoon/')) {
    const webtoonId = hash.replace('#/webtoon/', '');
    openWebtoon(webtoonId, false);
  } else {
    showHome(false);
  }
}

// API calls
async function fetchAPI(endpoint) {
  const response = await fetch(`/api${endpoint}`);
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  return response.json();
}

// Load webtoons list
async function loadWebtoons() {
  const container = document.getElementById('webtoon-list');

  try {
    const webtoons = await fetchAPI('/webtoons');

    if (webtoons.length === 0) {
      container.innerHTML = `
        <div class="error-message" style="grid-column: 1 / -1;">
          <h2>No Webtoons Found</h2>
          <p>Upload webtoons to R2 to get started.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = webtoons.map(w => `
      <div class="webtoon-card" onclick="openWebtoon('${w.id}')">
        <img src="${w.cover}" alt="${w.title}" loading="lazy"
             onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 300 400%22><rect fill=%22%2316213e%22 width=%22300%22 height=%22400%22/><text x=%22150%22 y=%22200%22 fill=%22%23666%22 text-anchor=%22middle%22>No Cover</text></svg>'">
        <div class="webtoon-card-info">
          <h3>${w.title}</h3>
          <p>${w.chapters?.length || 0} chapters</p>
        </div>
      </div>
    `).join('');
  } catch (error) {
    container.innerHTML = `
      <div class="error-message" style="grid-column: 1 / -1;">
        <h2>Error Loading</h2>
        <p>${error.message}</p>
      </div>
    `;
  }
}

// Open webtoon detail
async function openWebtoon(webtoonId, pushState = true) {
  try {
    const webtoon = await fetchAPI(`/webtoon/${webtoonId}`);
    currentWebtoon = webtoon;

    document.getElementById('webtoon-title').textContent = webtoon.title;
    document.getElementById('webtoon-cover').src = `/api/image/${webtoonId}/assets/covers/series_cover.jpg`;
    document.getElementById('webtoon-premise').textContent = webtoon.premise || webtoon.description;

    const tagsContainer = document.getElementById('webtoon-tags');
    const tags = [webtoon.genre, ...(webtoon.tags || [])].filter(Boolean);
    tagsContainer.innerHTML = tags.map(t => `<span class="tag">${t}</span>`).join('');

    // Render characters section
    const charactersSection = document.getElementById('characters-section');
    const characters = webtoon.characters || [];
    currentCharacters = characters;
    if (characters.length > 0) {
      charactersSection.innerHTML = `
        <h2>Characters</h2>
        <div class="characters-grid">
          ${characters.map(char => `
            <div class="character-card" onclick="openCharacterDetail('${char.id}')">
              <img src="/api/image/${webtoonId}/assets/characters/${char.id}_portrait.png"
                   alt="${char.name}"
                   onerror="this.onerror=null; this.src='/api/image/${webtoonId}/assets/characters/${char.id}.png';">
              <div class="character-info">
                <h3>${char.name}</h3>
                <p>${char.description || ''}</p>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    } else {
      charactersSection.innerHTML = '';
    }

    const chapterList = document.getElementById('chapter-list');
    chapterList.innerHTML = `
      <h2>Chapters</h2>
      ${(webtoon.chapters || []).map((ch, idx) => `
        <div class="chapter-item" onclick="openChapter('${webtoonId}', ${idx + 1})">
          <span class="chapter-num">${idx + 1}</span>
          <div class="chapter-info">
            <h3>${ch.title || `Chapter ${idx + 1}`}</h3>
            <p>${ch.summary || ''}</p>
          </div>
        </div>
      `).join('')}
      <div class="more-chapters-notice">
        More chapters coming soon...
      </div>
    `;

    totalChapters = webtoon.chapters?.length || 0;

    showView('webtoon-view');
    if (pushState) {
      history.pushState(null, '', `#/webtoon/${webtoonId}`);
    }
  } catch (error) {
    alert(`Error loading webtoon: ${error.message}`);
  }
}

// Open chapter reader
async function openChapter(webtoonId, chapterNum, pushState = true) {
  const content = document.getElementById('reader-content');
  content.innerHTML = '<div class="loading">Loading chapter...</div>';

  showView('reader-view');

  try {
    const chapter = await fetchAPI(`/chapter/${webtoonId}/${chapterNum}`);
    currentWebtoon = { id: webtoonId, title: chapter.webtoon_title };
    currentChapter = chapterNum;
    totalChapters = chapter.total_chapters;

    document.getElementById('reader-webtoon-title').textContent = chapter.webtoon_title;
    document.getElementById('reader-chapter-title').textContent = chapter.chapter_title;
    document.getElementById('chapter-indicator').textContent = `${chapterNum} / ${totalChapters}`;

    // Update nav buttons
    document.getElementById('prev-chapter-btn').disabled = chapterNum <= 1;
    document.getElementById('next-chapter-btn').disabled = chapterNum >= totalChapters;

    // Render segments
    if (chapter.segments.length === 0) {
      content.innerHTML = `
        <div class="error-message">
          <h2>No Content</h2>
          <p>This chapter has no segments yet.</p>
        </div>
      `;
    } else {
      let currentSceneId = null;
      const segmentsHtml = chapter.segments.map((seg, idx) => {
        // Check if this is first segment of a new scene
        let sceneTitleHtml = '';
        if (seg.scene_id !== currentSceneId) {
          currentSceneId = seg.scene_id;
          if (seg.scene_title) {
            sceneTitleHtml = `<div class="scene-title">${seg.scene_title}</div>`;
          }
        }

        // Build text overlay HTML
        let overlayHtml = '';
        const hasOverlay = seg.narration || (seg.dialogues && seg.dialogues.length > 0) || seg.sfx;

        if (hasOverlay) {
          overlayHtml = '<div class="text-overlay">';

          // Narration box
          if (seg.narration) {
            overlayHtml += `<div class="narration">${seg.narration}</div>`;
          }

          // SFX
          if (seg.sfx) {
            overlayHtml += `<div class="sfx">${seg.sfx}</div>`;
          }

          // Speech bubbles
          if (seg.dialogues && seg.dialogues.length > 0) {
            seg.dialogues.forEach((dlg, i) => {
              const sideClass = i % 2 === 1 ? 'right' : '';
              const speaker = dlg.character_id || '';
              const text = dlg.text || '';
              overlayHtml += `
                <div class="speech-bubble ${sideClass}">
                  <div class="speaker">${speaker}</div>
                  <p class="text">${text}</p>
                </div>
              `;
            });
          }

          overlayHtml += '</div>';
        }

        if (seg.has_image && seg.image_url) {
          return `
            ${sceneTitleHtml}
            <div class="segment" data-id="${seg.id}">
              <img src="${seg.image_url}" alt="${seg.id}" loading="lazy">
            </div>
            ${overlayHtml}
          `;
        } else {
          return `
            ${sceneTitleHtml}
            <div class="segment" data-id="${seg.id}">
              <div class="segment-placeholder">
                <span>${seg.id} - Image not available</span>
              </div>
            </div>
            ${overlayHtml}
          `;
        }
      }).join('');

      // Add end-of-chapter navigation card
      const hasNext = chapterNum < totalChapters;
      const hasPrev = chapterNum > 1;
      const endCardHtml = `
        <div class="chapter-end-card">
          <div class="chapter-end-title">End of Chapter ${chapterNum}</div>
          <div class="chapter-end-subtitle">${chapter.chapter_title}</div>
          <div class="chapter-end-nav">
            ${hasPrev ? `<button class="chapter-end-btn secondary" onclick="prevChapter()">Previous Chapter</button>` : ''}
            ${hasNext ? `<button class="chapter-end-btn primary" onclick="nextChapter()">Next Chapter</button>` : `<button class="chapter-end-btn secondary" onclick="exitReader()">Back to Series</button>`}
          </div>
          ${hasNext ? '' : '<div class="chapter-end-complete">You\'ve reached the latest chapter!</div>'}
        </div>
      `;

      content.innerHTML = segmentsHtml + endCardHtml;
    }

    // Scroll to top
    window.scrollTo(0, 0);

    if (pushState) {
      history.pushState(null, '', `#/read/${webtoonId}/${chapterNum}`);
    }
  } catch (error) {
    content.innerHTML = `
      <div class="error-message">
        <h2>Error Loading Chapter</h2>
        <p>${error.message}</p>
      </div>
    `;
  }
}

// Navigation
function showView(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(viewId).classList.add('active');
}

function showHome(pushState = true) {
  showView('home-view');
  if (pushState) {
    history.pushState(null, '', '#/');
  }
}

function exitReader() {
  if (currentWebtoon) {
    openWebtoon(currentWebtoon.id);
  } else {
    showHome();
  }
}

function prevChapter() {
  if (currentWebtoon && currentChapter > 1) {
    openChapter(currentWebtoon.id, currentChapter - 1);
  }
}

function nextChapter() {
  if (currentWebtoon && currentChapter < totalChapters) {
    openChapter(currentWebtoon.id, currentChapter + 1);
  }
}

// Reader gestures
function setupReaderGestures() {
  const readerContent = document.getElementById('reader-content');

  // Tap to toggle UI
  readerContent.addEventListener('click', (e) => {
    // Only toggle if clicking on content area, not controls
    if (e.target.closest('.nav-btn, .back-btn, .menu-btn')) return;

    toggleReaderUI();
  });

  // Track scroll direction for auto-hide
  let lastScrollY = 0;
  let scrollTimeout;

  window.addEventListener('scroll', () => {
    if (!document.getElementById('reader-view').classList.contains('active')) return;

    const currentScrollY = window.scrollY;
    const scrollingDown = currentScrollY > lastScrollY;

    // Auto-hide UI when scrolling down
    if (scrollingDown && currentScrollY > 100) {
      setReaderUIVisible(false);
    }

    lastScrollY = currentScrollY;

    // Show UI when reaching top or bottom
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
      const scrollHeight = document.documentElement.scrollHeight;
      const viewportHeight = window.innerHeight;

      if (currentScrollY < 50 || currentScrollY + viewportHeight > scrollHeight - 50) {
        setReaderUIVisible(true);
      }
    }, 150);
  }, { passive: true });
}

function toggleReaderUI() {
  setReaderUIVisible(!uiVisible);
}

function setReaderUIVisible(visible) {
  uiVisible = visible;
  const header = document.getElementById('reader-header');
  const footer = document.getElementById('reader-footer');

  if (visible) {
    header.classList.remove('hidden');
    footer.classList.remove('hidden');
  } else {
    header.classList.add('hidden');
    footer.classList.add('hidden');
  }
}

function toggleReaderMenu() {
  // Could expand with settings, chapter list, etc.
  alert('Menu coming soon!');
}

// Character modal functions
function openCharacterDetail(charId) {
  const char = currentCharacters.find(c => c.id === charId);
  if (!char) return;

  const modal = document.getElementById('character-modal');
  const imgEl = document.getElementById('modal-character-img');
  const webtoonId = currentWebtoon?.id;

  // Try portrait first, fallback to reference sheet
  imgEl.src = `/api/image/${webtoonId}/assets/characters/${charId}_portrait.png`;
  imgEl.onerror = function() {
    this.onerror = null;
    this.src = `/api/image/${webtoonId}/assets/characters/${charId}.png`;
  };

  document.getElementById('modal-character-name').textContent = char.name;
  document.getElementById('modal-character-desc').textContent = char.description || '';

  // Build traits section
  const traitsEl = document.getElementById('modal-character-traits');
  let traitsHtml = '';

  if (char.visual_traits) {
    traitsHtml += `<div class="trait-item"><strong>Appearance:</strong> ${char.visual_traits}</div>`;
  }
  if (char.age) {
    traitsHtml += `<div class="trait-item"><strong>Age:</strong> ${char.age}</div>`;
  }
  if (char.main) {
    traitsHtml += `<div class="trait-item"><span class="trait-badge">Main Character</span></div>`;
  }

  traitsEl.innerHTML = traitsHtml;

  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeCharacterModal(event) {
  if (event && event.target !== event.currentTarget) return;
  const modal = document.getElementById('character-modal');
  modal.classList.remove('active');
  document.body.style.overflow = '';
}

// Close modal on escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeCharacterModal();
  }
});

// Service worker for offline support (optional)
if ('serviceWorker' in navigator) {
  // navigator.serviceWorker.register('/sw.js');
}

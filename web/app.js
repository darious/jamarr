const API_BASE = '/api';

const state = {
    artists: [],
    selectedArtist: null,
    albums: [],
    selectedAlbum: null,
    tracks: [],
    playQueue: [],
    playQueueIndex: -1
};

// DOM Elements
const allArtistsGridEl = document.getElementById('all-artists-grid');
const azHeaderEl = document.getElementById('az-header');
const albumGridEl = document.getElementById('album-grid');
const trackListEl = document.getElementById('track-list');
const tracksUl = document.getElementById('tracks');
const albumTitleEl = document.getElementById('album-title');

const scanBtn = document.getElementById('scan-btn');

// Artist Page Elements
const artistDetailsEl = document.getElementById('artist-details');
const artistHeroNameEl = document.getElementById('artist-hero-name');
const artistHeroBioEl = document.getElementById('artist-hero-bio');
const artistHeroImageEl = document.getElementById('artist-hero-image');
const topTracksListEl = document.getElementById('top-tracks-list');
const similarArtistsGridEl = document.getElementById('similar-artists-grid');
const artistAlbumsGridEl = document.getElementById('artist-albums-grid');
const playAlbumBtn = document.getElementById('play-album-btn');
const prevBtn = document.getElementById('prev-btn');
const nextBtn = document.getElementById('next-btn');

const queueIndicatorEl = document.getElementById('queue-indicator');
const queueCountEl = document.getElementById('queue-count');
const queueViewEl = document.getElementById('queue-view');
const queueListEl = document.getElementById('queue-list');

// Init
async function init() {
    await loadArtists();

    scanBtn.addEventListener('click', triggerScan);
    document.getElementById('refresh-meta-btn').addEventListener('click', triggerArtistRefresh);


    // Logo click -> All Artists
    document.querySelector('.logo').addEventListener('click', () => {
        history.pushState({ view: 'all-artists' }, '', '/');
        showAllArtists();
    });

    // Handle browser back/forward
    window.onpopstate = (event) => {
        if (event.state) {
            restoreView(event.state);
        } else {
            // Default to home if no state (e.g. initial load)
            showAllArtists();
        }
    };

    // Initial load handling
    const hash = window.location.hash;
    if (hash.startsWith('#artist=')) {
        const artistName = decodeURIComponent(hash.substring(8));
        // Wait for artists to load
    } else if (hash.startsWith('#album=')) {
        // Handle album deep link
        const parts = decodeURIComponent(hash.substring(7)).split(':');
        if (parts.length >= 2) {
            // Wait for artists to load
        }
    } else {
        history.replaceState({ view: 'all-artists' }, '', '/');
    }
}

// API Calls
async function loadArtists() {
    const res = await fetch(`${API_BASE}/artists?_=${new Date().getTime()}`);
    state.artists = await res.json();
    renderArtists();
}

async function loadAlbums(artist) {
    let url = `${API_BASE}/albums`;
    if (artist) {
        url += `?artist=${encodeURIComponent(artist)}`;
    }
    const res = await fetch(url);
    state.albums = await res.json();
    renderAlbums();
}

async function loadTracks(album, pushState = true) {
    const res = await fetch(`${API_BASE}/tracks?album=${encodeURIComponent(album.album)}&artist=${encodeURIComponent(album.artist_name)}`);
    if (!res.ok) throw new Error(`Failed to fetch tracks: ${res.statusText}`);
    state.tracks = await res.json();
    renderTracks(album);

    if (pushState) {
        const hash = `#album=${encodeURIComponent(album.artist_name)}:${encodeURIComponent(album.album)}`;
        history.pushState({
            view: 'album-tracks',
            artist: album.artist_name,
            album: album.album
        }, '', hash);
    }
}

async function triggerScan() {
    scanBtn.disabled = true;
    scanBtn.textContent = 'Scanning...';
    try {
        await fetch(`${API_BASE}/scan`, { method: 'POST' });
        setTimeout(async () => {
            await loadArtists();
            if (state.selectedArtist) {
                // Reload current artist details if open
                const updatedArtist = state.artists.find(a => a.name === state.selectedArtist.name);
                if (updatedArtist) showArtistDetails(updatedArtist);
            }
            scanBtn.disabled = false;
            scanBtn.textContent = 'Scan Library';
        }, 5000);
    } catch (e) {
        console.error(e);
        scanBtn.disabled = false;
        scanBtn.textContent = 'Scan Failed';
    }
}

async function triggerArtistRefresh() {
    if (!state.selectedArtist) return;

    const refreshBtn = document.getElementById('refresh-meta-btn');
    const originalText = refreshBtn.textContent;
    refreshBtn.disabled = true;
    refreshBtn.textContent = 'Refreshing...';

    try {
        await fetch(`${API_BASE}/scan_artist?artist_name=${encodeURIComponent(state.selectedArtist.name)}`, { method: 'POST' });

        // Poll/Wait for update (simulated by timeout for now, or just reload after a few seconds)
        // In a real app we might get a job ID and poll
        setTimeout(async () => {
            // Reload artist logic
            const res = await fetch(`${API_BASE}/artists?_=${new Date().getTime()}`);
            state.artists = await res.json(); // refresh all artists to get updated one

            const updatedArtist = state.artists.find(a => a.name === state.selectedArtist.name);
            if (updatedArtist) {
                showArtistDetails(updatedArtist, false); // Don't push state again
            }

            refreshBtn.disabled = false;
            refreshBtn.textContent = originalText;
        }, 3000); // 3 seconds should be enough for single artist fetch
    } catch (e) {
        console.error("Refresh failed", e);
        refreshBtn.disabled = false;
        refreshBtn.textContent = 'Failed';
        setTimeout(() => refreshBtn.textContent = originalText, 2000);
    }
}

// Rendering

function renderArtists() {
    allArtistsGridEl.innerHTML = '';
    azHeaderEl.innerHTML = '';

    // Sort by sort_name
    const sortedArtists = [...state.artists].sort((a, b) => {
        const nameA = (a.sort_name || a.name).toUpperCase();
        const nameB = (b.sort_name || b.name).toUpperCase();
        return nameA.localeCompare(nameB);
    });

    // Group by letter
    const groups = {};
    sortedArtists.forEach(artist => {
        let char = (artist.sort_name || artist.name).charAt(0).toUpperCase();
        if (!/[A-Z]/.test(char)) char = '0';
        if (!groups[char]) groups[char] = [];
        groups[char].push(artist);
    });

    const chars = Object.keys(groups).sort();

    // Render A-Z Header
    chars.forEach(char => {
        const a = document.createElement('a');
        a.href = `#group-${char}`;
        a.textContent = char === '0' ? '#' : char;
        a.className = 'az-link';
        a.onclick = (e) => {
            e.preventDefault();
            const target = document.getElementById(`group-${char}`);
            if (target) {
                target.scrollIntoView({ behavior: 'smooth' });
            }
        };
        azHeaderEl.appendChild(a);
    });

    // Render Grid
    chars.forEach(char => {
        // Section Container
        const section = document.createElement('div');
        section.className = 'artist-section';

        // Section Header (Anchor)
        const header = document.createElement('div');
        header.id = `group-${char}`;
        header.className = 'artist-section-header';
        header.textContent = char === '0' ? '#' : char;
        section.appendChild(header);

        // Grid Container
        const grid = document.createElement('div');
        grid.className = 'artist-section-grid';

        groups[char].forEach(artist => {
            const div = document.createElement('div');
            div.className = 'artist-card';

            const img = document.createElement('img');
            img.className = 'artist-card-img';
            img.src = artist.image_url || 'assets/default-artist.png';

            const name = document.createElement('div');
            name.className = 'artist-card-name';
            name.textContent = artist.name; // Display name (not sort name)

            div.appendChild(img);
            div.appendChild(name);

            div.onclick = () => {
                selectArtist(artist);
                showArtistDetails(artist);
            };
            grid.appendChild(div);
        });

        section.appendChild(grid);
        allArtistsGridEl.appendChild(section);
    });
}

function showAllArtists() {
    allArtistsGridEl.style.display = 'block';
    azHeaderEl.style.display = 'flex';
    artistDetailsEl.style.display = 'none';
    albumGridEl.style.display = 'none';
    trackListEl.style.display = 'none';
    queueViewEl.style.display = 'none'; // hide queue
    document.getElementById('refresh-meta-btn').style.display = 'none';
    state.selectedArtist = null;
    state.selectedAlbum = null;
}

function selectArtist(artist) {
    state.selectedArtist = artist;
}

function showArtistDetails(artist, pushState = true) {
    console.log("Showing Artist Details:", artist);
    if (!artist) return;

    state.selectedArtist = artist;
    state.selectedAlbum = null; // Clear selected album when showing artist details

    if (pushState) {
        history.pushState({ view: 'artist-details', data: artist.name }, '', `#artist=${encodeURIComponent(artist.name)}`);
    }

    // Update UI
    allArtistsGridEl.style.display = 'none';
    azHeaderEl.style.display = 'none';
    artistDetailsEl.style.display = 'block';
    albumGridEl.style.display = 'none';
    trackListEl.style.display = 'none';
    queueViewEl.style.display = 'none';

    // Show Refresh Button
    document.getElementById('refresh-meta-btn').style.display = 'inline-block';

    // Hero
    if (artistHeroNameEl) artistHeroNameEl.textContent = artist.name || 'Unknown Artist';
    if (artistHeroBioEl) artistHeroBioEl.textContent = artist.bio || 'No biography available.';
    if (artistHeroImageEl) artistHeroImageEl.src = artist.image_url || 'assets/default-artist.png';

    // Background blur (optional: set same image)
    const bgEl = document.querySelector('.artist-hero-bg');
    if (bgEl) {
        bgEl.style.backgroundImage = `url('${artist.image_url || 'assets/default-artist.png'}')`;
    }

    // Render External Links
    let linksEl = document.getElementById('artist-hero-links');
    if (!linksEl) {
        // Fallback for cached HTML: Create the container dynamically
        const infoEl = document.querySelector('.artist-hero-info');
        if (infoEl) {
            linksEl = document.createElement('div');
            linksEl.id = 'artist-hero-links';
            linksEl.className = 'artist-links';
            infoEl.appendChild(linksEl);
        }
    }

    if (linksEl) {
        linksEl.innerHTML = '';

        // Helper to create link
        const addLink = (url, type, iconFile) => {
            if (!url) return;
            const a = document.createElement('a');
            a.href = url;
            a.target = '_blank';
            a.title = type; // Tooltip
            const img = document.createElement('img');
            img.src = `assets/${iconFile}`;
            img.alt = type;
            img.className = 'artist-link-icon';
            a.appendChild(img);
            linksEl.appendChild(a);
        };

        addLink(artist.musicbrainz_url, 'MusicBrainz', 'logo-musicbrainz.svg');
        addLink(artist.wikipedia_url, 'Wikipedia', 'logo-wikipedia.svg');
        addLink(artist.qobuz_url, 'Qobuz', 'logo-qobuz.png');
        addLink(artist.spotify_url, 'Spotify', 'logo-spotify.svg');
    }

    // Top Tracks - Fetch all artist tracks first to check availability without switching view
    fetch(`${API_BASE}/tracks?artist=${encodeURIComponent(artist.name)}`)
        .then(res => res.json())
        .then(tracks => {
            // Update state.tracks so playTrack works, but DO NOT call renderTracks
            state.tracks = tracks;
            renderTopTracks(artist.top_tracks || []);
        });

    // Similar Artists
    renderSimilarArtists(artist.similar_artists || []);

    // Albums
    loadAlbums(artist.name);
}

function renderTopTracks(tracks, showAll = false) {
    topTracksListEl.innerHTML = '';
    if (!tracks || tracks.length === 0) {
        topTracksListEl.innerHTML = '<li>No top tracks available.</li>';
        return;
    }

    const initialCount = 5;
    const hasMore = tracks.length > initialCount;
    const tracksToShow = showAll ? tracks : tracks.slice(0, initialCount);

    tracksToShow.forEach((track, index) => {
        // Try to find matching track in local library (state.tracks loaded in showArtistDetails)
        // Match by title (case-insensitive)
        const localTrack = state.tracks.find(t => t.title.toLowerCase() === track.name.toLowerCase());
        const isAvailable = !!localTrack;

        const li = document.createElement('li');
        li.className = `top-track-item ${isAvailable ? '' : 'track-unavailable'}`;

        // Artwork
        let artHtml = '';
        if (isAvailable && localTrack.art_id) {
            artHtml = `<img src="/art/${localTrack.art_id}" class="top-track-art link-album" alt="Art" onclick="goToAlbum('${localTrack.album}')">`;
        } else {
            artHtml = `<div class="top-track-art-placeholder"></div>`;
        }

        // Play Button
        let playHtml = '';
        if (isAvailable) {
            playHtml = `
                <button class="play-btn small" onclick="playTrack(${localTrack.id}, this)">
                    <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                </button>`;
        } else {
            playHtml = `<div class="play-btn-placeholder"></div>`;
        }

        // Tech Meta
        let techHtml = '';
        if (isAvailable) {
            techHtml = `
            <div class="track-tech-meta">
                <span class="badge">${localTrack.codec}</span>
                <span class="badge">${formatSampleRate(localTrack.sample_rate_hz)}</span>
                <span class="badge">${localTrack.bit_depth}bit</span>
                <span class="badge">${formatBitrate(localTrack.bitrate)}</span>
            </div>`;
        }

        li.innerHTML = `
            ${artHtml}
            ${playHtml}
            <div class="track-info">
                <div class="track-name ${isAvailable ? 'link-album' : ''}" ${isAvailable ? `onclick="goToAlbum('${localTrack.album}')"` : ''}>
                    ${track.name}
                </div>
                <div class="track-meta">
                    <span class="${isAvailable ? 'link-album' : ''}" ${isAvailable ? `onclick="goToAlbum('${localTrack.album}')"` : ''}>
                        ${track.album}
                    </span>
                    ${track.date ? ` • ${track.date.substring(0, 4)}` : ''}
                    ${(state.selectedArtist && track.artist && state.selectedArtist.name !== track.artist) ? ` • <span class="track-feat-artist inline">${track.artist}</span>` : ''}
                </div>
            </div>
            ${techHtml}
            <div class="track-duration">${formatDuration(track.duration_ms / 1000)}</div>
        `;
        topTracksListEl.appendChild(li);
    });

    if (hasMore) {
        const toggleLi = document.createElement('li');
        toggleLi.className = 'show-more-item';
        toggleLi.innerHTML = `<button class="show-more-btn">${showAll ? 'Show Less' : `Show ${tracks.length - initialCount} more`}</button>`;
        toggleLi.onclick = () => {
            renderTopTracks(tracks, !showAll);
        };
        topTracksListEl.appendChild(toggleLi);
    }
}

function goToAlbum(albumName) {
    if (!state.selectedArtist) return;

    // Find album object
    loadAlbums(state.selectedArtist.name).then(() => {
        const album = state.albums.find(a => a.album === albumName);
        if (album) {
            loadTracks(album);
        } else {
            console.warn("Album not found:", albumName);
        }
    });
}

function renderSimilarArtists(similarArtists, showAll = false) {
    similarArtistsGridEl.innerHTML = '';
    if (!similarArtists || similarArtists.length === 0) {
        similarArtistsGridEl.innerHTML = '<p>No similar artists found.</p>';
        return;
    }

    const initialCount = 5;
    const hasMore = similarArtists.length > initialCount;
    const artistsToShow = showAll ? similarArtists : similarArtists.slice(0, initialCount);

    const renderItem = (artistName) => {
        // Check if in library
        const libraryArtist = state.artists.find(a => a.name.toLowerCase() === artistName.toLowerCase());

        const div = document.createElement('div');
        div.className = 'similar-artist-item';

        // Try to find image if in library, else use placeholder
        let imgHtml = '';
        if (libraryArtist && libraryArtist.image_url) {
            imgHtml = `<img src="${libraryArtist.image_url}" class="similar-artist-img" alt="${artistName}">`;
        } else {
            // Generic placeholder
            imgHtml = `
                <div class="similar-artist-placeholder">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="24px" height="24px">
                        <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
                    </svg>
                </div>
            `;
        }

        div.innerHTML = `
            ${imgHtml}
            <span class="similar-artist-name">${artistName}</span>
        `;

        if (libraryArtist) {
            div.onclick = () => {
                selectArtist(libraryArtist);
                showArtistDetails(libraryArtist);
            };
            div.style.cursor = 'pointer';
        } else {
            div.style.cursor = 'default';
            div.style.opacity = '0.6';
        }

        similarArtistsGridEl.appendChild(div);
    };

    artistsToShow.forEach(renderItem);

    if (hasMore) {
        const toggleDiv = document.createElement('div');
        toggleDiv.className = 'show-more-container';
        toggleDiv.innerHTML = `<button class="show-more-btn">${showAll ? 'Show Less' : 'Show more'}</button>`;
        toggleDiv.onclick = () => {
            renderSimilarArtists(similarArtists, !showAll);
        };
        similarArtistsGridEl.appendChild(toggleDiv);
    }
}

function renderAlbums() {
    // Determine target container
    const targetEl = state.selectedArtist ? artistAlbumsGridEl : albumGridEl;
    targetEl.innerHTML = '';

    // Helper to create a card
    const createCard = (album) => {
        const div = document.createElement('div');
        div.className = 'album-card';

        const artWrapper = document.createElement('div');
        artWrapper.className = 'album-art-wrapper';

        const img = document.createElement('img');
        img.src = album.art_id ? `/art/${album.art_id}` : 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIiBmaWxsPSIjMzMzIi8+PC9zdmc+';
        img.className = 'album-art';

        artWrapper.appendChild(img);

        if (album.is_hires) {
            const overlay = document.createElement('img');
            overlay.src = 'assets/logo-hires.png';
            overlay.className = 'hires-overlay';
            artWrapper.appendChild(overlay);
        }

        div.appendChild(artWrapper);

        const h3 = document.createElement('h3');
        h3.textContent = album.album;
        div.appendChild(h3);

        const p = document.createElement('p');
        p.textContent = album.artist_name;
        div.appendChild(p);

        // Add extra metadata if in artist view
        if (state.selectedArtist) {
            const metaDiv = document.createElement('div');
            metaDiv.className = 'album-card-meta';
            const year = album.year ? album.year.substring(0, 4) : 'Unknown';
            const count = album.track_count ? `${album.track_count} tracks` : '';
            const duration = album.total_duration ? formatDurationLong(album.total_duration) : '';
            metaDiv.textContent = `${year} • ${count} • ${duration}`;
            div.appendChild(metaDiv);
        }

        div.onclick = () => loadTracks(album);
        return div;
    };

    if (state.selectedArtist) {
        // Artist View: Sections (Blocks) containing Grids
        targetEl.className = 'artist-albums-container'; // Remove 'album-grid' class

        const mainAlbums = state.albums.filter(a => a.type === 'main' || !a.type);
        const guestAlbums = state.albums.filter(a => a.type === 'appears_on');

        const renderSection = (title, list) => {
            if (!list || list.length === 0) return;

            const h2 = document.createElement('h2');
            h2.className = 'section-title';
            h2.textContent = title;
            // Ensure headers have spacing
            h2.style.marginTop = '2rem';
            h2.style.marginBottom = '1rem';
            targetEl.appendChild(h2);

            const grid = document.createElement('div');
            grid.className = 'album-grid';
            list.forEach(a => grid.appendChild(createCard(a)));
            targetEl.appendChild(grid);
        };

        renderSection('Albums', mainAlbums);
        renderSection('Appears On', guestAlbums);

    } else {
        // Library View: Single Grid
        targetEl.className = 'album-grid';
        state.albums.forEach(a => targetEl.appendChild(createCard(a)));
    }
}

const albumArtLargeEl = document.getElementById('album-art-large');
const albumArtistEl = document.getElementById('album-artist');
const albumGenreEl = document.getElementById('album-genre');
const albumMetaEl = document.getElementById('album-meta');

function renderTracks(album) {
    state.selectedAlbum = album;
    albumTitleEl.textContent = album.album;
    albumArtistEl.textContent = album.artist_name;
    albumArtistEl.onclick = () => showArtistDetails({ name: album.artist_name }); // Use object mock for now or fetch?
    // Actually showArtistDetails expects an object with .name, .bio etc.
    // Ideally we should find the artist object first.

    albumArtistEl.onclick = async () => {
        const artist = state.artists.find(a => a.name === album.artist_name);
        if (artist) {
            selectArtist(artist);
            showArtistDetails(artist);
        } else {
            // Fallback if not loaded (should be loaded usually)
            // or just try to show details with minimal info then fetch?
            // showArtistDetails({name: album.artist_name});
            // But showArtistDetails calls top_tracks which might fail if not fully populated.
            // Best to rely on it being in state.artists as we load all on init.
            console.warn("Artist object not found for interaction");
        }
    };
    albumArtistEl.style.cursor = 'pointer';

    // Calculate stats
    const totalTracks = state.tracks.length;
    const totalDuration = state.tracks.reduce((acc, t) => acc + (t.duration_seconds || 0), 0);

    // Get metadata from first track
    const firstTrack = state.tracks[0] || {};
    const genre = firstTrack.genre || 'Unknown Genre';
    const date = firstTrack.date || 'Unknown Date';
    const label = firstTrack.label || 'Unknown Label';

    albumGenreEl.textContent = genre;
    albumMetaEl.textContent = `Released by ${label} • ${date} • ${totalTracks} Tracks • ${formatDurationLong(totalDuration)}`;

    albumArtLargeEl.src = album.art_id ? `/art/${album.art_id}` : 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIiBmaWxsPSIjMzMzIi8+PC9zdmc+';

    // Check if any track is hi-res
    const isHires = state.tracks.some(t => (t.bit_depth > 16 || t.sample_rate_hz > 44100));
    const container = document.getElementById('album-art-container');

    // Remove existing overlay if any
    const existingOverlay = container.querySelector('.hires-overlay-large');
    if (existingOverlay) existingOverlay.remove();

    if (isHires) {
        const overlay = document.createElement('img');
        overlay.src = 'assets/logo-hires.png';
        overlay.className = 'hires-overlay-large';
        container.appendChild(overlay);
    }

    tracksUl.innerHTML = '';

    // Group by disc
    const discs = {};
    state.tracks.forEach(track => {
        const disc = track.disc_no || 1;
        if (!discs[disc]) discs[disc] = [];
        discs[disc].push(track);
    });

    const discNums = Object.keys(discs).sort((a, b) => a - b);
    const showDiscHeader = discNums.length > 1;

    discNums.forEach(discNum => {
        if (showDiscHeader) {
            const header = document.createElement('li');
            header.className = 'disc-header';
            header.textContent = `Disc ${discNum}`;
            tracksUl.appendChild(header);
        }

        discs[discNum].forEach(track => {
            const li = document.createElement('li');
            li.setAttribute('data-track-id', track.id);
            li.innerHTML = `
                <button class="play-btn" onclick="playTrack(${track.id}, this)">
                    <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                </button>
                <div class="track-info">
                    <span class="track-num">${track.track_no}.</span>
                    <span class="track-title">
                        ${track.title}
                        ${(track.artist && track.artist !== album.artist_name) ? `<span class="track-feat-artist">${track.artist}</span>` : ''}
                    </span>
                </div>
                <div class="track-meta">
                    <span class="badge">${track.codec}</span>
                    <span class="badge">${formatSampleRate(track.sample_rate_hz)}</span>
                    <span class="badge">${track.bit_depth}bit</span>
                    <span class="badge">${formatBitrate(track.bitrate)}</span>
                    <span class="duration">${formatDuration(track.duration_seconds)}</span>
                </div>
            `;
            tracksUl.appendChild(li);
        });
    });

    albumGridEl.style.display = 'none';
    artistDetailsEl.style.display = 'none';
    allArtistsGridEl.style.display = 'none';
    azHeaderEl.style.display = 'none';
    trackListEl.style.display = 'block';
    queueViewEl.style.display = 'none'; // Ensure queue is hidden
    document.getElementById('refresh-meta-btn').style.display = 'none';
}

// Audio Player Logic
let currentAudio = null;
let currentBtn = null;
let currentTrackData = null;
let currentAlbumData = null;
let isRemotePlaying = false;
let remoteInterval = null;
let remoteStartTime = 0;
let remoteDuration = 0;

async function fetchRenderers() {
    try {
        const res = await fetch('/api/renderers');
        const list = await res.json();
        console.log("Fetched Renderers:", list);
        const select = document.getElementById('renderer-select');
        select.innerHTML = '';
        list.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r.udn;
            opt.textContent = r.name;
            select.appendChild(opt);
        });

        // Restore local state or keep default
        if (!state.activeRenderer) state.activeRenderer = 'local';
        select.value = state.activeRenderer;

        select.onchange = async () => {
            state.activeRenderer = select.value;
            await fetch('/api/player/renderer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ udn: state.activeRenderer })
            });
            // If switching renderer, stop playback?
            stopPlayback();
        };

    } catch (e) { console.error("Failed to fetch renderers", e); }
}

// Call init
// Call init
fetchRenderers();
setInterval(fetchRenderers, 10000); // Poll every 10s

document.getElementById('add-renderer-btn').onclick = async () => {
    const ip = prompt("Enter Device IP (e.g. REDACTED_IP):");
    if (ip) {
        try {
            const res = await fetch('/api/player/add_manual', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip })
            });
            if (res.ok) {
                alert("Device Found!");
                fetchRenderers();
            } else {
                alert("Device not found.");
            }
        } catch (e) { alert("Error adding device"); }
    }
};


// Player Elements
const playerBar = document.getElementById('player-bar');
const playerArt = document.getElementById('player-art');
const playerTitle = document.getElementById('player-title');
const playerArtist = document.getElementById('player-artist');
const playPauseBtn = document.getElementById('play-pause-btn');
const progressBar = document.getElementById('progress-bar');
const progressContainer = document.getElementById('progress-container');
const timeCurrent = document.getElementById('player-time-current');
const timeTotal = document.getElementById('player-time-total');
const volumeSlider = document.getElementById('volume-slider');
const closePlayerBtn = document.getElementById('close-player-btn');
const playerTechFormat = document.getElementById('player-tech-format');
const playerTechDetails = document.getElementById('player-tech-details');

// Event Listeners
playPauseBtn.addEventListener('click', togglePlayPause);
progressContainer.addEventListener('click', seekTo);
volumeSlider.addEventListener('input', setVolume);
closePlayerBtn.addEventListener('click', closePlayer);
playerArt.addEventListener('click', goToCurrentAlbum);
playerTitle.addEventListener('click', goToCurrentAlbum);
playerArtist.addEventListener('click', (e) => {
    if (e.target.classList.contains('link-artist')) goToCurrentArtist();
    else if (e.target.classList.contains('link-album')) goToCurrentAlbum();
    if (e.target.classList.contains('link-artist')) goToCurrentArtist();
    else if (e.target.classList.contains('link-album')) goToCurrentAlbum();
});
playAlbumBtn.addEventListener('click', playAlbum);
prevBtn.addEventListener('click', playPrev);
nextBtn.addEventListener('click', playNext);

queueIndicatorEl.addEventListener('click', () => {
    if (queueViewEl.style.display === 'block') {
        history.back();
    } else {
        showQueue();
    }
});

function updateQueueUI() {
    if (queueCountEl) {
        const total = state.playQueue ? state.playQueue.length : 0;
        const current = state.playQueueIndex >= 0 ? state.playQueueIndex + 1 : 0;
        queueCountEl.textContent = `${current} / ${total}`;
    }
}

function showQueue(pushState = true) {
    if (pushState) {
        history.pushState({ view: 'queue', playQueue: state.playQueue, playQueueIndex: state.playQueueIndex }, '', '#queue');
    }

    allArtistsGridEl.style.display = 'none';
    azHeaderEl.style.display = 'none';
    artistDetailsEl.style.display = 'none';
    albumGridEl.style.display = 'none';
    trackListEl.style.display = 'none';
    queueViewEl.style.display = 'block';
    renderQueue();
}

function renderQueue() {
    queueListEl.innerHTML = '';
    if (!state.playQueue || state.playQueue.length === 0) {
        queueListEl.innerHTML = '<li style="padding: 20px; color: #888;">Queue is empty</li>';
        return;
    }

    state.playQueue.forEach((track, index) => {
        const li = document.createElement('li');
        li.className = `queue-item ${index === state.playQueueIndex ? 'current-track' : ''}`; // Use queue-item instead of top-track-item for base layout

        // Artwork
        let artHtml = '';
        if (track.art_id) {
            artHtml = `<img src="/art/${track.art_id}" class="top-track-art" alt="Art">`;
        } else {
            artHtml = `<div class="top-track-art-placeholder"></div>`;
        }

        // Play Button
        let playHtml = `
            <button class="play-btn small ${index === state.playQueueIndex ? 'playing' : ''}" onclick="playTrack(${track.id}, this, false)">
                ${index === state.playQueueIndex
                ? '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>'
                : '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>'}
            </button>`;

        // Tech Meta
        let techHtml = `
            <div class="track-tech-meta">
                <span class="badge">${track.codec || 'FLAC'}</span>
                <span class="badge">${track.bit_depth || 16}bit</span>
                <span class="badge">${formatBitrate(track.bitrate)}</span>
            </div>`;

        li.innerHTML = `
            <span class="track-number">${index + 1}</span>
            ${artHtml}
            ${playHtml}
            <div class="track-info">
                <div class="track-name">${track.title || track.name}</div>
                <div class="track-meta">
                    <span>${track.album}</span>
                    ${track.date ? ` • ${track.date.substring(0, 4)}` : ''}
                    ${(track.artist) ? ` • <span class="track-feat-artist inline">${track.artist}</span>` : ''}
                </div>
            </div>
            ${techHtml}
            <div class="track-duration">${formatDuration(track.duration_seconds || track.duration_ms / 1000)}</div>
        `;

        queueListEl.appendChild(li);
    });
}

async function playTrack(trackId, btn, resetQueue = true) {
    // Find track data from state - Check if in current tracks or fallback to queue if navigating
    let currentTrackData = state.tracks.find(t => t.id === trackId);

    // If not found in current view list, check the queue (case where we navigated away but Next/Prev still works)
    if (!currentTrackData && state.playQueue.length > 0) {
        currentTrackData = state.playQueue.find(t => t.id === trackId);
    }

    if (!currentTrackData) return;

    // Queue Logic
    if (resetQueue) {
        // New playback context initiated by user
        if (state.tracks && state.tracks.length > 0) {
            state.playQueue = [...state.tracks];
            state.playQueueIndex = state.playQueue.findIndex(t => t.id === trackId);
        } else {
            // Fallback
            state.playQueue = [currentTrackData];
            state.playQueueIndex = 0;
        }
    } else {
        // Navigating existing queue (Next/Prev)
        // Ensure playQueueIndex matches current track just in case
        const idx = state.playQueue.findIndex(t => t.id === trackId);
        if (idx !== -1) state.playQueueIndex = idx;
    }

    if (state.selectedAlbum) {
        currentAlbumData = state.selectedAlbum;
    }

    // Toggle Logic
    if (currentAudio || isRemotePlaying) {
        // If clicking same button/track and it's the current one in the queue
        if (currentBtn === btn && state.playQueue[state.playQueueIndex].id === trackId) {
            togglePlayPause();
            return;
        }
        stopPlayback();
    }

    currentBtn = btn;

    // Update Player UI
    playerBar.style.display = 'flex';
    playerTitle.textContent = currentTrackData.title;
    playerArtist.innerHTML = `<span class="link-artist">${currentTrackData.artist}</span> — <span class="link-album">${currentTrackData.album}</span>`;
    playerArt.src = currentTrackData.art_id ? `/art/${currentTrackData.art_id}` : 'assets/default-art.png';
    playerTechFormat.textContent = currentTrackData.codec.toUpperCase();
    playerTechDetails.textContent = `${formatSampleRate(currentTrackData.sample_rate_hz)} • ${currentTrackData.bit_depth || 16}bit`;

    // Start Playback
    if (state.activeRenderer && state.activeRenderer !== 'local') {
        // Remote
        try {
            await fetch('/api/player/play', {
                method: 'POST',
                body: JSON.stringify({ track_id: trackId }),
                headers: { 'Content-Type': 'application/json' }
            });
            isRemotePlaying = true;
            updatePlayIcons(true);

            // Start Progress Simulation
            startRemoteProgress(currentTrackData.duration_seconds || 0);

        } catch (e) {
            console.error("Remote playback failed", e);
            stopPlayback();
        }
    } else {
        // Local
        currentAudio = new Audio(`${API_BASE}/stream/${trackId}`);
        currentAudio.volume = volumeSlider.value;

        currentAudio.play().then(() => {
            updatePlayIcons(true);
        }).catch(e => {
            console.error("Playback failed", e);
            updatePlayIcons(false);
        });

        // Audio Events
        currentAudio.addEventListener('timeupdate', updateProgress);
        currentAudio.addEventListener('loadedmetadata', () => {
            timeTotal.textContent = formatDuration(currentAudio.duration);
        });
        currentAudio.addEventListener('ended', onTrackEnded);
    }

    updatePlayIcons(true);
    updateQueueUI();
}

async function togglePlayPause() {
    if (state.activeRenderer && state.activeRenderer !== 'local') {
        if (isRemotePlaying) {
            await fetch('/api/player/pause', { method: 'POST' });
            isRemotePlaying = false;
            updatePlayIcons(false);
            clearInterval(remoteInterval);
        } else {
            await fetch('/api/player/resume', { method: 'POST' });
            isRemotePlaying = true;
            updatePlayIcons(true);
            // Resume progress simulation
            startRemoteProgress(remoteDuration, parseFloat(timeCurrent.textContent) || 0); // Hacky resume from UI text
        }
        return;
    }

    if (!currentAudio) return;

    if (currentAudio.paused) {
        currentAudio.play();
        updatePlayIcons(true);
    } else {
        currentAudio.pause();
        updatePlayIcons(false);
    }
}

function stopPlayback() {
    if (remoteInterval) clearInterval(remoteInterval);
    isRemotePlaying = false;

    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
    updatePlayIcons(false);
    currentBtn = null;
}

function startRemoteProgress(duration, startOffset = 0) {
    clearInterval(remoteInterval);
    remoteDuration = duration;
    remoteStartTime = Date.now();
    let initialOffset = (typeof startOffset === 'string') ? parseDuration(startOffset) : startOffset; // parseDuration needed?
    // Actually, startOffset comes in as seconds from resume OR 0.
    // parseDuration is not defined. I passed UI text in resume logic.
    // Better: Helper function

    // Simple resume logic for now: default to 0 if NaN.
    if (isNaN(initialOffset)) initialOffset = 0;

    timeTotal.textContent = formatDuration(duration);

    remoteInterval = setInterval(() => {
        if (!isRemotePlaying) return;
        const diff = (Date.now() - remoteStartTime) / 1000;
        const current = initialOffset + diff;

        if (current >= duration) {
            // End
            clearInterval(remoteInterval);
            isRemotePlaying = false;
            updatePlayIcons(false);
            playNext();
            return;
        }

        const percent = (current / duration) * 100;
        progressBar.style.width = `${percent}%`;
        timeCurrent.textContent = formatDuration(current);
    }, 1000);
}

// Helper for format reverse?
function parseDuration(str) {
    if (!str) return 0;
    const p = str.split(':');
    let s = 0, m = 1;
    while (p.length > 0) {
        s += m * parseInt(p.pop(), 10);
        m *= 60;
    }
    return s;
}

function closePlayer() {
    stopPlayback();
    playerBar.style.display = 'none';
}

function updatePlayIcons(isPlaying) {
    // Main Player Button
    if (isPlaying) {
        playPauseBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
    } else {
        playPauseBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
    }

    // List Item Button
    if (currentBtn) {
        if (isPlaying) {
            currentBtn.classList.add('playing');
            currentBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
        } else {
            currentBtn.classList.remove('playing');
            currentBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
        }
    }
}

function updateProgress() {
    if (!currentAudio) return;

    const percent = (currentAudio.currentTime / currentAudio.duration) * 100;
    progressBar.style.width = `${percent}%`;
    timeCurrent.textContent = formatDuration(currentAudio.currentTime);
}

function seekTo(e) {
    if (!currentAudio) return;

    const rect = progressContainer.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    currentAudio.currentTime = pos * currentAudio.duration;
}

function setVolume() {
    if (currentAudio) {
        currentAudio.volume = volumeSlider.value;
    }
}

function onTrackEnded() {
    updatePlayIcons(false);
    playNext();
}

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatSampleRate(hz) {
    if (!hz) return '';
    return `${(hz / 1000).toFixed(1)}kHz`;
}

function formatBitrate(bps) {
    if (!bps) return '';
    return `${Math.round(bps / 1000)}kbps`;
}

function formatDurationLong(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);

    if (h > 0) {
        return `${h}h ${m}m`;
    }
    return `${m}m ${s}s`;
}

function restoreView(viewState) {
    if (viewState.view === 'all-artists') {
        showAllArtists();
    } else if (viewState.view === 'artist-details') {
        const artist = state.artists.find(a => a.name === viewState.data);
        if (artist) {
            selectArtist(artist);
            showArtistDetails(artist, false); // Don't push state again
        }
    } else if (viewState.view === 'album-tracks') {
        const artist = state.artists.find(a => a.name === viewState.artist);
        if (artist) {
            selectArtist(artist);
            // We need to load albums to find the specific album object
            loadAlbums(artist.name).then(() => {
                const album = state.albums.find(a => a.album === viewState.album);
                if (album) {
                    loadTracks(album, false); // Don't push state
                } else {
                    console.warn(`RestoreView: Album '${viewState.album}' not found for artist '${viewState.artist}'. Layout might act weird.`);
                    // Fallback to artist view so we don't get stuck on queue
                    showArtistDetails(artist, false);
                }
            });
        } else {
            console.warn(`RestoreView: Artist '${viewState.artist}' not found.`);
            showAllArtists();
        }
    }
}

function goToCurrentAlbum() {
    if (currentAlbumData) {
        // Use existing state logic to show album tracks
        // We can reuse the logic from restoreView or hash handling
        // But simplest is to just render it if we have the object

        // We need 'trackListEl' etc to be available. They are likely global or in scope.
        // And we need to hide other views.

        // Re-implementing view switching logic briefly:
        renderTracks(currentAlbumData);
        trackListEl.style.display = 'block';
        artistDetailsEl.style.display = 'none';
        albumGridEl.style.display = 'none';
        allArtistsGridEl.style.display = 'none';
        azHeaderEl.style.display = 'none';

        // Update URL/History?
        // history.pushState... 
        // For now, just navigation.
    }
}

function goToCurrentArtist() {
    // Try to get artist name from album data or track data
    let artistName = null;

    if (currentAlbumData && currentAlbumData.artist_name) {
        artistName = currentAlbumData.artist_name;
    } else if (currentTrackData) {
        // Fallback to track artist
        artistName = currentTrackData.artist;
    }

    if (artistName) {
        // Find artist object in state by name
        const artist = state.artists.find(a => a.name === artistName);
        if (artist) {
            selectArtist(artist);
            showArtistDetails(artist);
        } else {
            console.warn("Artist not found in state:", artistName);
        }
    }
}



init().then(() => {
    // Check hash after artists are loaded
    const hash = window.location.hash;
    if (hash.startsWith('#artist=')) {
        const artistName = decodeURIComponent(hash.substring(8));
        const artist = state.artists.find(a => a.name === artistName);
        if (artist) {
            selectArtist(artist);
            showArtistDetails(artist, false);
            history.replaceState({ view: 'artist-details', data: artistName }, '', hash);
        }
    } else if (hash.startsWith('#album=')) {
        const parts = decodeURIComponent(hash.substring(7)).split(':');
        if (parts.length >= 2) {
            const artistName = parts[0];
            const albumName = parts.slice(1).join(':');

            const artist = state.artists.find(a => a.name === artistName);
            if (artist) {
                selectArtist(artist);
                loadAlbums(artistName).then(() => {
                    const album = state.albums.find(a => a.album === albumName);
                    if (album) {
                        loadTracks(album, false);
                        history.replaceState({
                            view: 'album-tracks',
                            artist: artistName,
                            album: albumName
                        }, '', hash);
                    }
                });
            }
        }
    }
});


async function playAlbum() {
    if (!state.tracks || state.tracks.length === 0) return;
    // Start with first track
    playTrack(state.tracks[0].id);
}

function playNext() {
    if ((state.playQueueIndex + 1) < state.playQueue.length) {
        state.playQueueIndex++;
        const nextTrack = state.playQueue[state.playQueueIndex];
        playTrack(nextTrack.id, null, false); // false = don't reset queue
    }
}

function playPrev() {
    if (state.playQueueIndex > 0) {
        state.playQueueIndex--;
        const prevTrack = state.playQueue[state.playQueueIndex];
        playTrack(prevTrack.id, null, false); // false = don't reset queue
    }
}

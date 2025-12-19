const API_BASE = '/api';

const state = {
    artists: [],
    selectedArtist: null,
    albums: [],
    selectedAlbum: null,
    tracks: []
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

// Init
async function init() {
    await loadArtists();

    scanBtn.addEventListener('click', triggerScan);


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
    const res = await fetch(`${API_BASE}/artists`);
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
    state.selectedArtist = null;
}

function selectArtist(artist) {
    state.selectedArtist = artist;
}

function showArtistDetails(artist, pushState = true) {
    if (!artist) return;

    if (pushState) {
        history.pushState({ view: 'artist-details', data: artist.name }, '', `#artist=${encodeURIComponent(artist.name)}`);
    }

    // Update UI
    allArtistsGridEl.style.display = 'none';
    azHeaderEl.style.display = 'none';
    artistDetailsEl.style.display = 'block';
    albumGridEl.style.display = 'none';
    trackListEl.style.display = 'none';

    // Hero
    if (artistHeroNameEl) artistHeroNameEl.textContent = artist.name || 'Unknown Artist';
    if (artistHeroBioEl) artistHeroBioEl.textContent = artist.bio || 'No biography available.';
    if (artistHeroImageEl) artistHeroImageEl.src = artist.image_url || 'assets/default-artist.png';

    // Background blur (optional: set same image)
    const bgEl = document.querySelector('.artist-hero-bg');
    if (bgEl) {
        bgEl.style.backgroundImage = `url('${artist.image_url || 'assets/default-artist.png'}')`;
    }

    // Top Tracks
    renderTopTracks(artist.top_tracks || []);

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
        const li = document.createElement('li');
        li.className = 'top-track-item';
        li.innerHTML = `
            <div class="track-number">${index + 1}</div>
            <div class="track-info">
                <div class="track-name">${track.name}</div>
                <div class="track-meta">${track.album} • ${track.date ? track.date.substring(0, 4) : ''}</div>
            </div>
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

    state.albums.forEach(album => {
        const div = document.createElement('div');
        div.className = 'album-card';

        const artWrapper = document.createElement('div');
        artWrapper.className = 'album-art-wrapper';

        const img = document.createElement('img');
        img.src = album.art_id ? `/art/${album.art_id}` : 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iIzMzMyIvPjwvc3ZnPg==';
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

        targetEl.appendChild(div);
    });
}

const albumArtLargeEl = document.getElementById('album-art-large');
const albumArtistEl = document.getElementById('album-artist');
const albumGenreEl = document.getElementById('album-genre');
const albumMetaEl = document.getElementById('album-meta');

function renderTracks(album) {
    state.selectedAlbum = album;
    albumTitleEl.textContent = album.album;
    albumArtistEl.textContent = album.artist_name;

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

    albumArtLargeEl.src = album.art_id ? `/art/${album.art_id}` : 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iIzMzMyIvPjwvc3ZnPg==';

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
            li.innerHTML = `
                <div class="track-info">
                    <span class="track-num">${track.track_no}.</span>
                    <span class="track-title">${track.title}</span>
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
                }
            });
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


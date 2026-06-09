// Global State
let activeTab = 'notes';
let activeNoteId = null;
let crawlerPollInterval = null;
let lastRetrievedChunks = [];

// API Base URL (defaults to relative paths, since we serve frontend from FastAPI)
const API_URL = "";

// Simple Markdown-to-HTML parser for LLM synthesis text
function parseMarkdown(md) {
    if (!md) return "";
    let html = md;
    
    // Parse markdown links [text](url) into HTML anchors with target="_blank"
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" class="synthesis-source-link"><i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 0.7rem; margin-right: 3px; color: var(--accent-color);"></i>$1</a>');
    
    // Replace headings
    html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
    
    // Replace bold
    html = html.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
    
    // Replace list items
    html = html.replace(/^\* (.*$)/gim, '<li>$1</li>');
    html = html.replace(/^- (.*$)/gim, '<li>$1</li>');
    
    // Group list items into <ul>
    // This is a naive regex but works fine for simple LLM structures
    html = html.replace(/(<li>.*<\/li>)+/gim, '<ul>$&</ul>');
    
    // Clean up empty lines
    html = html.replace(/\n\n/gim, '<p></p>');
    // Replace single newlines with break tags in non-html blocks
    html = html.split('<p></p>').map(para => {
        if (!para.startsWith('<h') && !para.startsWith('<ul')) {
            return `<p>${para.replace(/\n/g, '<br>')}</p>`;
        }
        return para;
    }).join('');

    return html;
}

// --- TAB NAVIGATION SYSTEM ---
function initTabs() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const tabId = item.getAttribute('data-tab');
            switchTab(tabId);
        });
    });
}

function switchTab(tabId) {
    activeTab = tabId;
    
    // Update active nav link
    document.querySelectorAll('.nav-item').forEach(item => {
        if (item.getAttribute('data-tab') === tabId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Update active panel view
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    
    const activePane = document.getElementById(`tab-${tabId}`);
    if (activePane) {
        activePane.classList.add('active');
    }

    // Trigger tab-specific loads
    if (tabId === 'notes') {
        loadNotes();
    } else if (tabId === 'sources') {
        loadSources();
    } else if (tabId === 'graph') {
        loadGraphData();
    } else if (tabId === 'settings') {
        loadSystemStatus();
    }
}

// --- SYSTEM DIAGNOSTICS & SETTINGS ---
async function loadSystemStatus() {
    try {
        const res = await fetch(`${API_URL}/api/status`);
        const status = await res.json();
        
        // Update stats
        document.getElementById('stat-sources').innerText = status.sources_count;
        document.getElementById('stat-chunks').innerText = status.chunks_count;
        
        // Update settings diagnostics
        document.getElementById('diag-device').innerText = status.device_used === 'cuda' ? 'PyTorch CUDA (GPU Accelerator)' : 'CPU Mode';
        document.getElementById('diag-pages').innerText = status.sources_count;
        document.getElementById('diag-chunks').innerText = status.chunks_count;
        
        // Update system status in sidebar footer
        const statusText = document.querySelector('.system-status .status-text');
        const statusIndicator = document.querySelector('.system-status .status-indicator');
        
        if (status.gemini_api_configured || status.openai_api_configured) {
            statusText.innerText = "LLM Cloud APIs Connected";
            statusIndicator.className = "status-indicator online";
        } else {
            statusText.innerText = "Local Model Active (Fallback)";
            statusIndicator.className = "status-indicator online"; // Still online since local works
        }
    } catch (err) {
        console.error("Failed to load status details:", err);
    }
}

async function saveSettings() {
    const geminiKey = document.getElementById('settings-gemini-key').value.strip();
    const openaiKey = document.getElementById('settings-openai-key').value.strip();
    
    try {
        const res = await fetch(`${API_URL}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gemini_key: geminiKey, openai_key: openaiKey })
        });
        const data = await res.json();
        if (data.status === 'success') {
            alert("API configuration keys applied successfully.");
            loadSystemStatus();
        }
    } catch (err) {
        alert("Error applying settings.");
    }
}

// --- NOTION WORKSPACE NOTES CRUD ---
async function loadNotes() {
    try {
        const res = await fetch(`${API_URL}/api/notes`);
        const data = await res.json();
        const listContainer = document.getElementById('notes-list');
        listContainer.innerHTML = '';
        
        if (data.notes.length === 0) {
            listContainer.innerHTML = '<div class="empty-state-small">No pages created yet.</div>';
            return;
        }
        
        data.notes.forEach(note => {
            const card = document.createElement('div');
            card.className = `note-item-card ${activeNoteId === note.id ? 'active' : ''}`;
            card.onclick = () => selectNote(note.id);
            
            const date = new Date(note.updated_at).toLocaleString();
            card.innerHTML = `
                <h4>${note.title || 'Untitled Page'}</h4>
                <span>Updated: ${date}</span>
            `;
            listContainer.appendChild(card);
        });
    } catch (err) {
        console.error("Error loading workspace notes:", err);
    }
}

async function selectNote(noteId) {
    activeNoteId = noteId;
    try {
        const res = await fetch(`${API_URL}/api/notes/${noteId}`);
        if (res.status === 444) {
            activeNoteId = null;
            return;
        }
        const note = await res.json();
        
        document.getElementById('editor-placeholder').classList.add('hidden');
        document.getElementById('editor-active').classList.remove('hidden');
        
        document.getElementById('note-title-input').value = note.title;
        document.getElementById('note-body-input').value = note.content;
        
        // Highlight active note in list
        document.querySelectorAll('.note-item-card').forEach(card => {
            card.classList.remove('active');
        });
        loadNotes();
    } catch (err) {
        console.error("Error retrieving note details:", err);
    }
}

async function createNewNote() {
    try {
        const res = await fetch(`${API_URL}/api/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'New Research Page', content: '' })
        });
        const data = await res.json();
        await loadNotes();
        selectNote(data.id);
    } catch (err) {
        console.error("Error creating note:", err);
    }
}

async function saveActiveNote() {
    if (!activeNoteId) return;
    const title = document.getElementById('note-title-input').value;
    const content = document.getElementById('note-body-input').value;
    
    try {
        const res = await fetch(`${API_URL}/api/notes/${activeNoteId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, content })
        });
        const tag = document.querySelector('.autosave-tag');
        tag.innerText = "Saved successfully";
        setTimeout(() => tag.innerText = "Saved locally", 2000);
        loadNotes();
    } catch (err) {
        console.error("Error saving note:", err);
    }
}

async function deleteActiveNote() {
    if (!activeNoteId) return;
    if (!confirm("Are you sure you want to delete this workspace note?")) return;
    
    try {
        await fetch(`${API_URL}/api/notes/${activeNoteId}`, { method: 'DELETE' });
        activeNoteId = null;
        document.getElementById('editor-active').classList.add('hidden');
        document.getElementById('editor-placeholder').classList.remove('hidden');
        loadNotes();
    } catch (err) {
        console.error("Error deleting note:", err);
    }
}

// --- ARCHIVE & SOURCE VIEWER ---
async function loadSources() {
    try {
        const res = await fetch(`${API_URL}/api/sources`);
        const data = await res.json();
        renderSourcesGrid(data.sources);
    } catch (err) {
        console.error("Error loading sources:", err);
    }
}

function renderSourcesGrid(sources) {
    const grid = document.getElementById('sources-grid');
    grid.innerHTML = '';
    
    if (sources.length === 0) {
        grid.innerHTML = '<div class="empty-state-small">No scraped documents in database. Run the Crawler.</div>';
        return;
    }

    sources.forEach(src => {
        const card = document.createElement('div');
        card.className = 'source-card';
        card.onclick = () => viewSourceDetail(src.id);
        
        let trustClass = 'trust-low';
        let trustLabel = 'Opinion/Blog';
        if (src.trust_score >= 0.9) {
            trustClass = 'trust-high';
            trustLabel = 'Official Gov/UN';
        } else if (src.trust_score >= 0.7) {
            trustClass = 'trust-medium';
            trustLabel = 'Credible Media';
        }
        
        const domain = new URL(src.url).hostname;
        const date = new Date(src.crawled_at).toLocaleDateString();

        card.innerHTML = `
            <div class="source-card-header">
                <span class="category-tag">${src.category}</span>
                <span class="trust-badge ${trustClass}">${trustLabel} (${src.trust_score.toFixed(2)})</span>
            </div>
            <h3>${src.title}</h3>
            <div class="source-card-meta">
                <span class="domain" title="${src.url}"><i class="fa-solid fa-link"></i> ${domain}</span>
                <span>${date}</span>
            </div>
        `;
        grid.appendChild(card);
    });
}

async function viewSourceDetail(sourceId) {
    try {
        const res = await fetch(`${API_URL}/api/sources/${sourceId}`);
        const data = await res.json();
        
        document.getElementById('source-modal-title').innerText = data.source.title;
        document.getElementById('source-modal-link').href = data.source.url;
        document.getElementById('source-modal-category').innerText = data.source.category;
        
        let trustClass = 'trust-low';
        let trustLabel = 'Opinion/Blog';
        if (data.source.trust_score >= 0.9) {
            trustClass = 'trust-high';
            trustLabel = 'Official Gov/UN';
        } else if (data.source.trust_score >= 0.7) {
            trustClass = 'trust-medium';
            trustLabel = 'Credible Media';
        }
        
        const badge = document.getElementById('source-modal-trust');
        badge.className = `trust-badge ${trustClass}`;
        badge.innerText = `Trust Score: ${data.source.trust_score.toFixed(2)} (${trustLabel})`;

        const contentArea = document.getElementById('source-modal-content');
        contentArea.innerHTML = '';
        
        // Render text divided by semantic chunks
        data.chunks.forEach(chunk => {
            const chunkDiv = document.createElement('div');
            chunkDiv.className = 'source-modal-chunk';
            chunkDiv.innerHTML = `
                <div style="font-size: 0.7rem; color: var(--text-muted); margin-bottom: 4px;">Semantic Chunk #${chunk.chunk_index + 1}</div>
                <div class="chunk-body">${chunk.text}</div>
            `;
            contentArea.appendChild(chunkDiv);
        });

        // Show Modal
        document.getElementById('modal-source-view').classList.remove('hidden');
    } catch (err) {
        console.error("Error viewing source detail:", err);
    }
}

// --- DISCOVERY CRAWLER CONTROLLER ---
async function loadCrawlerSeeds() {
    try {
        const res = await fetch(`${API_URL}/api/crawler/seeds`);
        const data = await res.json();
        document.getElementById('crawler-seeds-input').value = data.seeds.join('\n');
    } catch (err) {
        console.error("Error loading seeds:", err);
    }
}

async function startCrawler() {
    const seedsText = document.getElementById('crawler-seeds-input').value;
    const seeds = seedsText.split('\n').map(s => s.trim()).filter(s => s.length > 0);
    const limit = parseInt(document.getElementById('crawler-limit').value);
    const depth = parseInt(document.getElementById('crawler-depth').value);
    
    if (seeds.length === 0) {
        alert("Please enter at least one seed query.");
        return;
    }

    try {
        // 1. Update Seeds List
        await fetch(`${API_URL}/api/crawler/seeds`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(seeds)
        });

        // 2. Trigger Crawl
        const res = await fetch(`${API_URL}/api/crawler/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_pages: limit, max_depth: depth })
        });
        const startData = await res.json();
        
        if (res.status === 400) {
            alert(startData.detail);
            return;
        }

        // Toggles console monitor UI
        const badge = document.getElementById('crawler-pulse-status');
        badge.innerText = 'Crawling';
        badge.className = 'crawler-badge crawling';
        document.getElementById('btn-start-crawl').disabled = true;

        // Reset Terminal
        const consoleEl = document.getElementById('crawler-console');
        consoleEl.innerHTML = '<div class="terminal-line system">Crawl directive registered. Spawning threads...</div>';
        
        // 3. Poll logs
        crawlerPollInterval = setInterval(pollCrawlerStatus, 1500);
    } catch (err) {
        alert("Error starting crawler.");
    }
}

async function pollCrawlerStatus() {
    try {
        const res = await fetch(`${API_URL}/api/crawler/status`);
        const status = await res.json();
        const consoleEl = document.getElementById('crawler-console');
        
        // Re-render logs
        consoleEl.innerHTML = '';
        status.logs.forEach(log => {
            const line = document.createElement('div');
            line.className = 'terminal-line';
            if (log.includes("Indexed source") || log.includes("complete")) {
                line.classList.add('success');
            } else if (log.includes("Error") || log.includes("failed")) {
                line.classList.add('error');
            } else if (log.includes("Starting") || log.includes("Initializing")) {
                line.classList.add('system');
            }
            line.innerText = log;
            consoleEl.appendChild(line);
        });
        
        // Auto scroll terminal to bottom
        consoleEl.scrollTop = consoleEl.scrollHeight;

        if (!status.active) {
            // Crawl finished!
            clearInterval(crawlerPollInterval);
            crawlerPollInterval = null;
            
            const badge = document.getElementById('crawler-pulse-status');
            badge.innerText = 'Idle';
            badge.className = 'crawler-badge idle';
            document.getElementById('btn-start-crawl').disabled = false;
            
            loadSystemStatus();
            alert(`Crawl finished successfully! Scraped & indexed: ${status.pages_indexed} pages.`);
        }
    } catch (err) {
        console.error("Error polling crawler logs:", err);
    }
}

// --- DEBATE PREP / BATTLE STRATEGY ---
async function synthesizeDebate() {
    const committee = document.getElementById('debate-committee').value.trim();
    const portfolio = document.getElementById('debate-portfolio').value.trim();
    const agenda = document.getElementById('debate-agenda').value.trim();
    const mode = document.querySelector('input[name="debate-mode"]:checked').value;
    
    if (!committee) {
        alert("Please enter a Committee Name.");
        return;
    }
    if (!portfolio) {
        alert("Please enter a Represented Portfolio.");
        return;
    }
    if (!agenda) {
        alert("Please enter a Committee Agenda.");
        return;
    }

    const outputPanel = document.getElementById('debate-synthesis-output');
    // Hide export buttons at start of synthesis
    document.getElementById('btn-export-pdf').classList.add('hidden');
    document.getElementById('btn-export-latex').classList.add('hidden');
    
    outputPanel.innerHTML = `
        <div class="empty-state">
            <i class="fa-solid fa-spinner fa-spin"></i>
            <p>Expanding query, retrieving semantically relevant chunks, ranking source credibility, and synthesizing diplomatic strategy...</p>
        </div>
    `;

    try {
        const res = await fetch(`${API_URL}/api/debate/synthesis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ committee, portfolio, agenda, mode, top_k: 6 })
        });
        const data = await res.json();
        lastRetrievedChunks = data.chunks || [];
        
        // Render markdown to HTML
        outputPanel.innerHTML = parseMarkdown(data.synthesis);
        
        // Show export buttons upon successful synthesis
        document.getElementById('btn-export-pdf').classList.remove('hidden');
        document.getElementById('btn-export-latex').classList.remove('hidden');
        
        // Render Ground Truth references
        const refList = document.getElementById('debate-references-list');
        refList.innerHTML = '';
        
        if (data.sources.length === 0) {
            refList.innerHTML = '<div class="empty-state-small">No source materials retrieved.</div>';
            return;
        }

        data.sources.forEach(src => {
            const card = document.createElement('div');
            card.className = 'reference-card';
            
            let trustLabel = 'Opinion';
            if (src.trust_score >= 0.9) trustLabel = 'UN/Gov';
            else if (src.trust_score >= 0.7) trustLabel = 'Media';
            
            card.innerHTML = `
                <div class="reference-meta">
                    <span class="ref-score">${src.category}</span>
                    <span class="trust-badge ${src.trust_score >= 0.9 ? 'trust-high' : src.trust_score >= 0.7 ? 'trust-medium' : 'trust-low'}">${trustLabel} (${src.trust_score.toFixed(2)})</span>
                </div>
                <div class="reference-title">${src.title}</div>
                <a href="${src.url}" target="_blank" style="font-size: 0.7rem; color: var(--accent-color); text-decoration: none;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Visit source URL</a>
            `;
            refList.appendChild(card);
        });

    } catch (err) {
        outputPanel.innerHTML = `<div class="empty-state-small error">Error generating strategy briefing: ${err}</div>`;
    }
}

function copySynthesisText() {
    const textEl = document.getElementById('debate-synthesis-output');
    // Get text content cleanly
    const text = textEl.innerText;
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('btn-copy-synthesis');
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied';
        setTimeout(() => btn.innerHTML = '<i class="fa-regular fa-copy"></i> Copy', 2000);
    }).catch(err => {
        alert("Copy failed.");
    });
}

async function saveSynthesisToNote() {
    const title = `Battle Prep: ${document.getElementById('debate-query').value.substring(0, 30)}...`;
    const textEl = document.getElementById('debate-synthesis-output');
    const content = textEl.innerText;
    
    try {
        const res = await fetch(`${API_URL}/api/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, content })
        });
        const data = await res.json();
        alert("Synthesis saved as a new page in your Notion Workspace!");
        switchTab('notes');
        selectNote(data.id);
    } catch (err) {
        alert("Failed to save to notes workspace.");
    }
}

async function exportDossier(format) {
    const committee = document.getElementById('debate-committee').value.trim();
    const portfolio = document.getElementById('debate-portfolio').value.trim() || "The Delegation";
    const agenda = document.getElementById('debate-agenda').value.trim();
    const title = `${committee} Study Dossier - ${agenda.substring(0, 40)}`;
    const content = document.getElementById('debate-synthesis-output').innerText;
    
    const btn = document.getElementById(`btn-export-${format}`);
    const origHtml = btn.innerHTML;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Generating...`;
    btn.disabled = true;
    
    try {
        const res = await fetch(`${API_URL}/api/debate/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, country: portfolio, content })
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            const downloadUrl = format === 'pdf' ? data.pdf_url : data.latex_url;
            
            // Trigger standard browser download anchor click
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.download = downloadUrl.split('/').pop();
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        } else {
            alert(`Export failed: ${data.detail || 'unknown error'}`);
        }
    } catch (err) {
        alert("Error during document export: " + err);
    } finally {
        btn.innerHTML = origHtml;
        btn.disabled = false;
    }
}

function copyRawContextPrompt() {
    if (!lastRetrievedChunks || lastRetrievedChunks.length === 0) {
        alert("Please run a debate search query first to load context chunks.");
        return;
    }
    
    const committee = document.getElementById('debate-committee').value.trim();
    const portfolio = document.getElementById('debate-portfolio').value.trim();
    const agenda = document.getElementById('debate-agenda').value.trim();
    
    let promptText = `SYSTEM INSTRUCTION: You are an expert research assistant. Below is the raw, web-crawled and semantically retrieved research context regarding the agenda: "${agenda}" inside the committee: "${committee}". Analyze this context and consolidate the key arguments, diplomatic pretexts, and strategic frames for the portfolio representation of ${portfolio}.\n\n`;
    promptText += `### RESEARCH FOUNDATIONS (RAW INTERNET CONTEXT)\n`;
    promptText += `==================================================================\n\n`;
    
    lastRetrievedChunks.forEach((c, idx) => {
        promptText += `[DOCUMENT #${idx + 1}]\n`;
        promptText += `Title: ${c.title}\n`;
        promptText += `URL: ${c.url}\n`;
        promptText += `Trust Score: ${c.trust_score.toFixed(2)} (${c.trust_score >= 0.9 ? 'UN/Gov official' : c.trust_score >= 0.7 ? 'Major Media' : 'Opinion/General'})\n`;
        promptText += `Excerpt:\n"${c.text}"\n`;
        promptText += `------------------------------------------------------------------\n\n`;
    });
    
    navigator.clipboard.writeText(promptText).then(() => {
        const btn = document.getElementById('btn-copy-raw-context');
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
        setTimeout(() => btn.innerHTML = '<i class="fa-regular fa-clipboard"></i> Copy Chunks', 2000);
    }).catch(err => {
        console.error("Clipboard copy error:", err);
        alert("Failed to copy context chunks to clipboard.");
    });
}

async function exportFullDossier() {
    const btn = document.getElementById('btn-export-full-dossier');
    const origHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Exporting...';
    btn.disabled = true;
    
    try {
        const res = await fetch(`${API_URL}/api/export/full-dossier`);
        const data = await res.json();
        
        if (data.pdf_url) {
            // Download PDF
            const link = document.createElement('a');
            link.href = data.pdf_url;
            link.download = data.pdf_url.split('/').pop();
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            // Also download markdown
            if (data.markdown_url) {
                setTimeout(() => {
                    const link2 = document.createElement('a');
                    link2.href = data.markdown_url;
                    link2.download = data.markdown_url.split('/').pop();
                    document.body.appendChild(link2);
                    link2.click();
                    document.body.removeChild(link2);
                }, 500);
            }
            
            alert(`Dossier exported successfully!\n\nSources: ${data.stats.sources}\nChunks: ${data.stats.chunks}\nEntities: ${data.stats.entities}\nRelations: ${data.stats.relations}`);
        } else {
            alert('Export failed: No data returned.');
        }
    } catch (err) {
        alert('Error exporting dossier: ' + err);
    } finally {
        btn.innerHTML = origHtml;
        btn.disabled = false;
    }
}

// --- EDITOR CONTEXT INJECT SYSTEM ---
async function initInjectModal() {
    const modal = document.getElementById('modal-inject');
    
    document.getElementById('btn-open-inject').addEventListener('click', () => {
        document.getElementById('inject-search-input').value = '';
        document.getElementById('inject-results-list').innerHTML = '<div class="empty-state-small">Type queries to fetch chunks.</div>';
        modal.classList.remove('hidden');
    });

    document.getElementById('btn-close-inject').addEventListener('click', () => {
        modal.classList.add('hidden');
    });
    
    document.getElementById('btn-do-inject-search').addEventListener('click', executeInjectSearch);
}

async function executeInjectSearch() {
    const query = document.getElementById('inject-search-input').value;
    if (!query) return;
    const domain = document.getElementById('inject-search-domain').value;
    
    const resultsContainer = document.getElementById('inject-results-list');
    resultsContainer.innerHTML = '<div class="empty-state-small"><i class="fa-solid fa-spinner fa-spin"></i> Retrieving research...</div>';
    
    try {
        const res = await fetch(`${API_URL}/api/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, top_k: 5, domain })
        });
        const data = await res.json();
        resultsContainer.innerHTML = '';
        
        if (data.results.length === 0) {
            resultsContainer.innerHTML = '<div class="empty-state-small">No matching research chunks found.</div>';
            return;
        }

        data.results.forEach(res => {
            const card = document.createElement('div');
            card.className = 'inject-card';
            card.onclick = () => injectChunkIntoEditor(res.text, res.title, res.url);
            
            card.innerHTML = `
                <div class="inject-card-header">
                    <span>${res.title}</span>
                    <span style="color: var(--accent-color);">Relevance: ${(res.similarity * 100).toFixed(0)}%</span>
                </div>
                <div class="inject-card-text">${res.text.substring(0, 160)}...</div>
            `;
            resultsContainer.appendChild(card);
        });
    } catch (err) {
        resultsContainer.innerHTML = '<div class="empty-state-small error">Search failed.</div>';
    }
}

function injectChunkIntoEditor(text, title, url) {
    const editor = document.getElementById('note-body-input');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const currentText = editor.value;
    
    const injection = `\n\n> [!NOTE]\n> **Geopolitical Reference: ${title}**\n> Source URL: ${url}\n> "${text}"\n\n`;
    
    editor.value = currentText.substring(0, start) + injection + currentText.substring(end);
    
    // Hide Modal
    document.getElementById('modal-inject').classList.add('hidden');
    saveActiveNote();
    editor.focus();
}

// --- INIT APP GLOBAL TRIGGERS ---
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initInjectModal();
    
    // Notes Event Bindings
    document.getElementById('btn-new-note').addEventListener('click', createNewNote);
    document.getElementById('btn-save-note').addEventListener('click', saveActiveNote);
    document.getElementById('btn-delete-note').addEventListener('click', deleteActiveNote);
    
    // Save note on keyup to mimic auto-save (debounced slightly or on edit exit)
    document.getElementById('note-body-input').addEventListener('blur', saveActiveNote);
    document.getElementById('note-title-input').addEventListener('blur', saveActiveNote);

    // Sources Modals Bindings
    document.getElementById('btn-close-source-modal').addEventListener('click', () => {
        document.getElementById('modal-source-view').classList.add('hidden');
    });

    // Crawler Event Bindings
    document.getElementById('btn-start-crawl').addEventListener('click', startCrawler);
    
    // Debate Prep Event Bindings
    document.getElementById('btn-generate-debate').addEventListener('click', synthesizeDebate);
    document.getElementById('btn-copy-synthesis').addEventListener('click', copySynthesisText);
    document.getElementById('btn-save-to-note').addEventListener('click', saveSynthesisToNote);
    document.getElementById('btn-export-pdf').addEventListener('click', () => exportDossier('pdf'));
    document.getElementById('btn-export-latex').addEventListener('click', () => exportDossier('latex'));
    document.getElementById('btn-copy-raw-context').addEventListener('click', copyRawContextPrompt);
    document.getElementById('btn-export-full-dossier').addEventListener('click', exportFullDossier);
    
    // Make debate radio cards selectable visually
    const radioLabels = document.querySelectorAll('.radio-card');
    radioLabels.forEach(label => {
        label.addEventListener('click', () => {
            radioLabels.forEach(l => l.classList.remove('selected'));
            label.classList.add('selected');
            const input = label.querySelector('input[type="radio"]');
            input.checked = true;
        });
    });

    // Settings Bindings
    document.getElementById('btn-save-settings').addEventListener('click', saveSettings);

    // Initial Load
    loadSystemStatus();
    loadNotes();
    loadCrawlerSeeds();
});

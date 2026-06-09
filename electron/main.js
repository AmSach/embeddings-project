const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');

// ─── Configuration ───
const BACKEND_PORT = 8001;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const PYTHON_VENV = path.join('C:', 'Users', 'amans', 'AppData', 'Local', 'hermes', 'hermes-agent', 'venv', 'Scripts', 'python.exe');
const PROJECT_ROOT = path.resolve(path.join(__dirname, '..'));
const isDev = process.argv.includes('--dev');

let mainWindow = null;
let splashWindow = null;
let backendProcess = null;

// ─── Splash Screen ───
function createSplashWindow() {
    splashWindow = new BrowserWindow({
        width: 480,
        height: 360,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        resizable: false,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true
        }
    });
    splashWindow.loadFile(path.join(__dirname, 'splash.html'));
    splashWindow.center();
}

// ─── Main Window ───
function createMainWindow() {
    mainWindow = new BrowserWindow({
        width: 1440,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        title: 'Semantic Research Intelligence Assistant',
        icon: path.join(__dirname, 'icon.png'),
        show: false,
        backgroundColor: '#0a0a1a',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        }
    });

    // Custom app menu
    const menuTemplate = [
        {
            label: 'File',
            submenu: [
                {
                    label: 'Export Full Dossier',
                    accelerator: 'CmdOrCtrl+Shift+E',
                    click: () => {
                        mainWindow.webContents.executeJavaScript('exportFullDossier()');
                    }
                },
                { type: 'separator' },
                {
                    label: 'Open Exports Folder',
                    click: () => {
                        const exportsDir = path.join(PROJECT_ROOT, 'frontend', 'exports');
                        if (!fs.existsSync(exportsDir)) fs.mkdirSync(exportsDir, { recursive: true });
                        shell.openPath(exportsDir);
                    }
                },
                { type: 'separator' },
                { role: 'quit' }
            ]
        },
        {
            label: 'View',
            submenu: [
                { role: 'reload' },
                { role: 'forceReload' },
                { role: 'toggleDevTools' },
                { type: 'separator' },
                { role: 'resetZoom' },
                { role: 'zoomIn' },
                { role: 'zoomOut' },
                { type: 'separator' },
                { role: 'togglefullscreen' }
            ]
        },
        {
            label: 'Research',
            submenu: [
                {
                    label: 'Start Crawler',
                    accelerator: 'CmdOrCtrl+Shift+C',
                    click: () => {
                        mainWindow.webContents.executeJavaScript(`
                            switchTab('crawler');
                        `);
                    }
                },
                {
                    label: 'Knowledge Graph',
                    accelerator: 'CmdOrCtrl+Shift+G',
                    click: () => {
                        mainWindow.webContents.executeJavaScript(`
                            switchTab('graph');
                        `);
                    }
                },
                {
                    label: 'Debate Prep',
                    accelerator: 'CmdOrCtrl+Shift+D',
                    click: () => {
                        mainWindow.webContents.executeJavaScript(`
                            switchTab('debate');
                        `);
                    }
                }
            ]
        },
        {
            label: 'Help',
            submenu: [
                {
                    label: 'About',
                    click: () => {
                        dialog.showMessageBox(mainWindow, {
                            type: 'info',
                            title: 'Semantic Research Assistant',
                            message: 'Semantic Research Intelligence Assistant v1.0',
                            detail: 'Multi-domain semantic embeddings research platform.\n\nPowered by:\n• SentenceTransformers (all-MiniLM-L6-v2)\n• FastAPI + SQLite\n• Electron Desktop Shell\n• ReportLab PDF Engine'
                        });
                    }
                }
            ]
        }
    ];

    const menu = Menu.buildFromTemplate(menuTemplate);
    Menu.setApplicationMenu(menu);

    // Open external links in system browser
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        shell.openExternal(url);
        return { action: 'deny' };
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// ─── Backend Process Management ───
function findPython() {
    // Check venv first
    if (fs.existsSync(PYTHON_VENV)) {
        return PYTHON_VENV;
    }
    // Fallback to system python
    return 'python';
}

function startBackend() {
    return new Promise((resolve, reject) => {
        const pythonPath = findPython();
        console.log(`[Electron] Starting backend with: ${pythonPath}`);
        console.log(`[Electron] Working directory: ${PROJECT_ROOT}`);

        backendProcess = spawn(pythonPath, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)], {
            cwd: PROJECT_ROOT,
            stdio: ['pipe', 'pipe', 'pipe'],
            env: { ...process.env }
        });

        backendProcess.stdout.on('data', (data) => {
            const msg = data.toString().trim();
            console.log(`[Backend] ${msg}`);
        });

        backendProcess.stderr.on('data', (data) => {
            const msg = data.toString().trim();
            console.log(`[Backend:err] ${msg}`);
            // Uvicorn logs startup on stderr
            if (msg.includes('Application startup complete') || msg.includes('Uvicorn running on')) {
                resolve();
            }
        });

        backendProcess.on('error', (err) => {
            console.error('[Electron] Failed to start backend:', err);
            reject(err);
        });

        backendProcess.on('exit', (code) => {
            console.log(`[Electron] Backend process exited with code: ${code}`);
            backendProcess = null;
        });

        // Timeout fallback: if we don't get the startup message, poll the health endpoint
        const startTime = Date.now();
        const pollInterval = setInterval(() => {
            if (Date.now() - startTime > 90000) {
                clearInterval(pollInterval);
                reject(new Error('Backend startup timed out after 90s'));
                return;
            }

            const req = http.get(`${BACKEND_URL}/api/status`, (res) => {
                if (res.statusCode === 200) {
                    clearInterval(pollInterval);
                    resolve();
                }
            });
            req.on('error', () => { /* still starting up */ });
            req.end();
        }, 1000);

    });
}

function killBackend() {
    if (backendProcess) {
        console.log('[Electron] Shutting down backend process...');
        backendProcess.kill('SIGTERM');
        
        // Force kill after 5s if it doesn't exit gracefully
        setTimeout(() => {
            if (backendProcess) {
                try {
                    backendProcess.kill('SIGKILL');
                } catch (e) { /* already dead */ }
            }
        }, 5000);
    }
}

// ─── App Lifecycle ───
app.whenReady().then(async () => {
    // 1. Show splash screen
    createSplashWindow();

    // 2. Create main window (hidden)
    createMainWindow();

    try {
        // 3. Start backend
        console.log('[Electron] Starting FastAPI backend...');
        await startBackend();
        console.log('[Electron] Backend is ready!');

        // 4. Load the frontend from the backend server
        await mainWindow.loadURL(BACKEND_URL);
        
        // 5. Show main window, close splash
        mainWindow.show();
        if (splashWindow) {
            splashWindow.close();
            splashWindow = null;
        }
    } catch (err) {
        console.error('[Electron] Startup error:', err);
        if (splashWindow) {
            splashWindow.close();
        }
        dialog.showErrorBox(
            'Startup Error',
            `Failed to start the research assistant backend.\n\nError: ${err.message}\n\nPlease ensure Python and all dependencies are installed.`
        );
        app.quit();
    }
});

app.on('window-all-closed', () => {
    killBackend();
    app.quit();
});

app.on('before-quit', () => {
    killBackend();
});

// macOS dock click re-create window
app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow();
        mainWindow.loadURL(BACKEND_URL);
        mainWindow.show();
    }
});

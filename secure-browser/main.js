const { app, BrowserWindow, globalShortcut, Menu, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');

const CONFIG = {
    baseUrl: 'http://localhost'
};

let mainWindow;
let isSafeToQuit = false;

// ============================================================
// VIOLATION LOG FILE SETUP
// Violations ek local file mein save honge proof ke liye
// ============================================================
const logPath = path.join(os.homedir(), 'oems_violations.log');

function writeLog(message) {
    const timestamp = new Date().toISOString();
    const line = `[${timestamp}] ${message}\n`;
    try {
        fs.appendFileSync(logPath, line);
    } catch (e) {
        console.error('Log write failed:', e);
    }
}

// ============================================================
// APP READY
// ============================================================
app.whenReady().then(() => {
    Menu.setApplicationMenu(null);

    mainWindow = new BrowserWindow({
        fullscreen: true,
        kiosk: true,
        alwaysOnTop: true,
        frame: false,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            // Extra hardening
            webSecurity: true,
            allowRunningInsecureContent: false,
            experimentalFeatures: false,
        }
    });

    // FIX: Secure browser signature — Flask ko pata chalega ki Electron chal raha hai
    mainWindow.webContents.session.webRequest.onBeforeSendHeaders((details, callback) => {
        details.requestHeaders['X-OEMS-Secure-Browser'] = 'ElectronV1';
        callback({ requestHeaders: details.requestHeaders });
    });

    // ---------------------------------------------------------
    // YAHAN CHANGE KIYA HAI: Direct URL ke bajaye Local HTML load karega
    // ---------------------------------------------------------
    mainWindow.loadFile('splash.html');
    writeLog('SESSION STARTED — OEMS Exam Browser launched.');

    // ============================================================
    // FIX 1: will-navigate — sirf allowed URLs
    // ---------------------------------------------------------
    // YAHAN BHI CHANGE KIYA HAI: Nginx (port 80) aur local files ko allow kiya
    // ============================================================
    mainWindow.webContents.on('will-navigate', (event, url) => {
        const allowed =
            url.startsWith('http://127.0.0.1') ||
            url.startsWith('http://localhost') ||
            url.startsWith('file://'); // Local start.html allow karne ke liye
            
        if (!allowed) {
            event.preventDefault();
            writeLog(`BLOCKED navigation attempt to: ${url}`);
        }
    });

    // ============================================================
    // FIX 2: NEW WINDOW BLOCK — window.open() ya _blank links
    // ============================================================
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        writeLog(`BLOCKED new window attempt: ${url}`);
        return { action: 'deny' };
    });

    // ============================================================
    // FIX 3: COPY-PASTE & RIGHT-CLICK BLOCK (page load ke baad)
    // ============================================================
    mainWindow.webContents.on('did-finish-load', () => {
        mainWindow.webContents.executeJavaScript(`
            document.addEventListener('contextmenu', e => e.preventDefault());
            document.addEventListener('copy',  e => e.preventDefault());
            document.addEventListener('cut',   e => e.preventDefault());
            document.addEventListener('paste', e => e.preventDefault());
            document.body.style.userSelect = 'none';
            document.body.style.webkitUserSelect = 'none';
        `);
    });

    // ============================================================
    // FIX 4: KEYBOARD SHORTCUTS BLOCK
    // ============================================================
    const blockedShortcuts = [
        'CommandOrControl+R',         
        'F5',                         
        'F11',                        
        'F12',                        
        'CommandOrControl+Shift+I',   
        'CommandOrControl+Shift+J',   
        'CommandOrControl+W',         
        'CommandOrControl+N',         
        'CommandOrControl+T',         
        'Alt+F4',                     
        'CommandOrControl+C',         
        'CommandOrControl+V',         
        'CommandOrControl+X',         
        'CommandOrControl+A',         
        'CommandOrControl+Option+Space', 
        'CommandOrControl+Tab',       
        'Alt+Tab',                    
        'CommandOrControl+M',         
        'CommandOrControl+H',         
    ];

    blockedShortcuts.forEach(key => {
        try {
            globalShortcut.register(key, () => {
                writeLog(`BLOCKED shortcut attempt: ${key}`);
            });
        } catch (err) {
            console.log(`Warning: Could not block ${key} — ${err.message}`);
        }
    });

    writeLog(`Blocked ${blockedShortcuts.length} keyboard shortcuts.`);
});

// ============================================================
// FIX 5: IPC LISTENERS — preload.js se aane wale events
// ============================================================

// Violation log karo
ipcMain.on('violation', (event, data) => {
    const msg = `VIOLATION | type=${data.type} | details=${data.details}`;
    console.log(`[OEMS] ${msg}`);
    writeLog(msg);
});

// Exam submit — safely quit karo
ipcMain.on('submit-exam', (event) => {
    writeLog('EXAM SUBMITTED — safe quit triggered.');
    isSafeToQuit = true;
    setTimeout(() => app.quit(), 2000);
});

// ============================================================
// FORCE QUIT BLOCKER (Cmd+Q)
// ============================================================
app.on('before-quit', (event) => {
    if (!isSafeToQuit) {
        event.preventDefault();
        writeLog('BLOCKED force quit attempt (Cmd+Q or similar).');
        console.log('[OEMS] Force quit blocked.');
    }
});

process.on('SIGTERM', () => {
    writeLog('SIGTERM received — admin shutdown.');
    isSafeToQuit = true;
    app.quit();
});

process.on('SIGINT', () => {
    writeLog('SIGINT received — admin shutdown.');
    isSafeToQuit = true;
    app.quit();
});

app.on('will-quit', () => {
    globalShortcut.unregisterAll();
    writeLog('SESSION ENDED — shortcuts unregistered.\n' + '='.repeat(60));
});

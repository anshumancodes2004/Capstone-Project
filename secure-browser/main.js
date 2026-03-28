const { app, BrowserWindow, globalShortcut, Menu } = require('electron');
const { exec } = require('child_process');
const os = require('os');

const CONFIG = {
    baseUrl: 'http://127.0.0.1:5000' 
};

let mainWindow;

// Ye flag decide karega ki app ko close hone dena hai ya nahi
let isSafeToQuit = false;

app.whenReady().then(() => {
    Menu.setApplicationMenu(null);

    mainWindow = new BrowserWindow({
        fullscreen: true,
        kiosk: true,
        alwaysOnTop: true,
        frame: false,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true
        }
    });

    mainWindow.loadURL(CONFIG.baseUrl);
    
    // Security check: Domain restrict karna
    mainWindow.webContents.on('will-navigate', (event, url) => {
        if (!url.includes('127.0.0.1:5000') && !url.includes('localhost:5000')) {
            event.preventDefault();
        }
    });

    // ==========================================
    // 1. COPY-PASTE & RIGHT-CLICK BLOCK
    // ==========================================
    mainWindow.webContents.on('did-finish-load', () => {
        mainWindow.webContents.executeJavaScript(`
            // Right-click disable karega
            document.addEventListener('contextmenu', event => event.preventDefault());
            // Copy, Cut, Paste disable karega
            document.addEventListener('copy', event => event.preventDefault());
            document.addEventListener('cut', event => event.preventDefault());
            document.addEventListener('paste', event => event.preventDefault());
            // Text selection (highlighting) disable karega
            document.body.style.userSelect = 'none';
            document.body.style.webkitUserSelect = 'none';
        `);
    });

    // ==========================================
    // 2. ADMIN TERMINAL SHORTCUT
    // ==========================================
    globalShortcut.register('CommandOrControl+Shift+T', () => {
        if (os.platform() === 'win32') {
            exec('start cmd'); 
        } else if (os.platform() === 'darwin') {
            exec('open -a Terminal'); 
        } else {
            exec('x-terminal-emulator'); 
        }
    });

    // ==========================================
    // 3. KEYBOARD SHORTCUTS BLOCK
    // ==========================================
    const blockedShortcuts = [
        'CommandOrControl+R',           // Reload
        'F5',                           // Reload
        'CommandOrControl+Shift+I',     // Developer Tools
        'CommandOrControl+W',           // Close Tab/Window
        'Alt+F4',                       // Close Window (Windows)
        'CommandOrControl+C',           // Copy (Keyboard)
        'CommandOrControl+V',           // Paste (Keyboard)
        'CommandOrControl+X',           // Cut (Keyboard)
        'CommandOrControl+Option+Space' // Mac Finder/Spotlight
    ];

    blockedShortcuts.forEach(key => {
        try {
            globalShortcut.register(key, () => {
                console.log(`${key} is blocked during the exam.`);
            });
        } catch (err) {
            console.log(`Warning: Failed to block ${key}`);
        }
    });
});

// ==========================================
// 4. FORCE QUIT (Cmd+Q) BLOCKER
// ==========================================
app.on('before-quit', (event) => {
    // Agar command line se kill signal nahi aaya hai, toh quit cancel kar do
    if (!isSafeToQuit) {
        event.preventDefault();
        console.log("Force quit (Cmd+Q) is disabled!");
    }
});

// Jab Admin terminal se 'killall Electron' chalayega, tabhi app band hoga
process.on('SIGTERM', () => {
    isSafeToQuit = true;
    app.quit();
});
process.on('SIGINT', () => {
    isSafeToQuit = true;
    app.quit();
});

// Memory clear karne ke liye
app.on('will-quit', () => {
    globalShortcut.unregisterAll();
});

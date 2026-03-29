const { contextBridge, ipcRenderer } = require('electron');

// ============================================================
// OEMS Secure Browser — Preload Script
//
// Sirf yahi APIs renderer (HTML page) ko milti hain.
// Node.js ya Electron internals directly accessible nahi hain.
// ============================================================

contextBridge.exposeInMainWorld('secureBrowser', {

    // --------------------------------------------------------
    // reportViolation — exam violation main process ko bhejo
    // FIX: Input validation add ki — koi bhi arbitrary data
    // ipcRenderer se nahi bheja ja sakta ab
    // --------------------------------------------------------
    reportViolation: (type, details) => {
        // Type check — sirf strings allowed
        if (typeof type !== 'string' || typeof details !== 'string') {
            console.warn('[OEMS] reportViolation: invalid input ignored.');
            return;
        }
        // Length limit — log overflow prevent karna
        const safeType    = type.slice(0, 50);
        const safeDetails = details.slice(0, 200);

        ipcRenderer.send('violation', {
            type:    safeType,
            details: safeDetails
        });
    },

    // --------------------------------------------------------
    // submitExam — exam submit hone pe main process ko batao
    // FIX: ab main.js mein ipcMain.on('submit-exam') listener
    // hai jo safely app quit karta hai
    // --------------------------------------------------------
    submitExam: () => {
        ipcRenderer.send('submit-exam');
    },

    // --------------------------------------------------------
    // isElectron — HTML page check kar sake ki Electron mein
    // chal raha hai ya normal browser mein
    // --------------------------------------------------------
    isElectron: true,

    // NOTE: getVersion() hata diya — hardcoded '1.0.0' tha,
    // koi use nahi tha aur unnecessary exposure tha.
});
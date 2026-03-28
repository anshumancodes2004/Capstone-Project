const { contextBridge, ipcRenderer } = require('electron');

// Expose safe APIs to frontend
contextBridge.exposeInMainWorld('secureBrowser', {
    reportViolation: (type, details) => {
        ipcRenderer.send('violation', { type, details });
    },
    
    submitExam: () => {
        ipcRenderer.send('submit-exam');
    },
    
    getVersion: () => {
        return '1.0.0';
    }
});

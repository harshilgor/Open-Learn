const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('formaDesktop', Object.freeze({
  platform: process.platform,
  version: process.env.npm_package_version || '0.1.0',
  serviceMode: process.env.FORMA_HOSTED_API_URL ? 'cloud' : 'local',
  apiBaseUrl: process.env.FORMA_HOSTED_API_URL || (process.env.FORMA_API_PORT ? `http://127.0.0.1:${process.env.FORMA_API_PORT}` : undefined),
  apiToken: process.env.FORMA_HOSTED_API_URL ? undefined : process.env.FORMA_API_TOKEN || undefined,
  credentials: Object.freeze({
    has: key => ipcRenderer.invoke('credentials:has', key),
    get: key => ipcRenderer.invoke('credentials:get', key),
    set: (key, value) => ipcRenderer.invoke('credentials:set', key, value),
    delete: key => ipcRenderer.invoke('credentials:delete', key)
  }),
  preferences: Object.freeze({
    get: () => ipcRenderer.invoke('preferences:get'),
    set: values => ipcRenderer.invoke('preferences:set', values)
  }),
  updates: Object.freeze({
    status: () => ipcRenderer.invoke('updates:status'),
    check: () => ipcRenderer.invoke('updates:check'),
    install: () => ipcRenderer.invoke('updates:install'),
    onStatus: callback => {
      const listener = (_event, status) => callback(status);
      ipcRenderer.on('forma:update-status', listener);
      return () => ipcRenderer.removeListener('forma:update-status', listener);
    }
  }),
  onOpenSettings: callback => {
    const listener = () => callback();
    ipcRenderer.on('forma:open-settings', listener);
    return () => ipcRenderer.removeListener('forma:open-settings', listener);
  },
  onServiceStatus: callback => {
    const listener = (_event, status) => callback(status);
    ipcRenderer.on('forma:service-status', listener);
    return () => ipcRenderer.removeListener('forma:service-status', listener);
  }
}));

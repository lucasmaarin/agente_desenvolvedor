// Service Worker mínimo — apenas para tornar o app instalável como PWA.
// Não faz cache offline porque o app precisa do servidor para funcionar.
const CACHE = 'code-agent-v1';

self.addEventListener('install', (e) => e.waitUntil(self.skipWaiting()));
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// Passa todas as requisições direto para a rede
self.addEventListener('fetch', (e) => {
  e.respondWith(fetch(e.request));
});

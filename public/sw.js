const CACHE_NAME = 'canvas-pwa-v1.0.1';
const urlsToCache = [
    '/',
    '/index.html',
    '/script.js',
    '/style.css',
    '/manifest.json',
    'https://cdn.tailwindcss.com',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css',
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap',
    'https://fonts.gstatic.com/s/inter/v12/UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hiJ-Ek-_EeA.woff2'
];

// Install event - cache resources for offline use
self.addEventListener('install', (event) => {
    console.log('SW: Installing service worker');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('SW: Caching app shell');
                return cache.addAll(urlsToCache);
            })
            .then(() => {
                console.log('SW: App shell cached successfully');
                return self.skipWaiting();
            })
            .catch((error) => {
                console.error('SW: Cache failed:', error);
            })
    );
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {
    const { request } = event;
    
    // Skip socket.io and other real-time requests
    if (request.url.includes('socket.io') || 
        request.url.includes('hot-update') ||
        request.method !== 'GET') {
        return;
    }
    
    event.respondWith(
        caches.match(request)
            .then((cachedResponse) => {
                if (cachedResponse) {
                    // Return cached version
                    return cachedResponse;
                }
                
                // Fetch from network
                return fetch(request)
                    .then((networkResponse) => {
                        // Don't cache if not successful
                        if (!networkResponse || networkResponse.status !== 200) {
                            return networkResponse;
                        }
                        
                        // Clone the response
                        const responseToCache = networkResponse.clone();
                        
                        // Cache new resources
                        caches.open(CACHE_NAME)
                            .then((cache) => {
                                cache.put(request, responseToCache);
                            });
                        
                        return networkResponse;
                    })
                    .catch((error) => {
                        console.log('SW: Network request failed:', error);
                        // Return offline fallback if available
                        return caches.match('/index.html');
                    });
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('SW: Activating service worker');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('SW: Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => {
            console.log('SW: Service worker activated');
            return self.clients.claim();
        })
    );
});

// Background sync for offline drawing data
self.addEventListener('sync', (event) => {
    if (event.tag === 'background-sync-canvas') {
        console.log('SW: Background sync triggered');
        event.waitUntil(syncCanvasData());
    }
});

// Push notifications (for future use)
self.addEventListener('push', (event) => {
    const options = {
        body: event.data ? event.data.text() : 'New canvas update available',
        icon: '/icon-192.png',
        badge: '/badge-72.png',
        vibrate: [100, 50, 100],
        data: {
            dateOfArrival: Date.now(),
            primaryKey: '1'
        },
        actions: [
            {
                action: 'explore',
                title: 'View Canvas',
                icon: '/icon-192.png'
            },
            {
                action: 'close',
                title: 'Close',
                icon: '/icon-192.png'
            }
        ]
    };
    
    event.waitUntil(
        self.registration.showNotification('Canvas App', options)
    );
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    
    if (event.action === 'explore') {
        event.waitUntil(
            clients.openWindow('/')
        );
    }
});

// Sync canvas data when back online
async function syncCanvasData() {
    try {
        // Get stored offline data
        const cache = await caches.open(CACHE_NAME);
        const offlineData = await cache.match('/offline-canvas-data');
        
        if (offlineData) {
            const data = await offlineData.json();
            // Send to server when online
            await fetch('/api/sync-canvas', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            // Clear offline data
            await cache.delete('/offline-canvas-data');
            console.log('SW: Canvas data synced successfully');
        }
    } catch (error) {
        console.error('SW: Sync failed:', error);
    }
}

// Message handling from main thread
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
    
    if (event.data && event.data.type === 'CACHE_CANVAS_DATA') {
        // Cache canvas data for offline use
        caches.open(CACHE_NAME).then((cache) => {
            cache.put('/offline-canvas-data', new Response(JSON.stringify(event.data.payload)));
        });
    }
});
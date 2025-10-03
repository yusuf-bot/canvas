const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const path = require('path');
const fs = require('fs').promises;
const admin = require('firebase-admin');

const app = express();
const server = http.createServer(app);
const io = socketIo(server, {
    cors: {
        origin: process.env.NODE_ENV === 'production' ? false : "*",
        methods: ["GET", "POST"]
    }
});

// ------------------- FCM Setup -------------------
const serviceAccount = require('./fcm-service-account.json'); // Place your JSON here
admin.initializeApp({
    credential: admin.credential.cert(serviceAccount)
});

async function sendFCMUpdate() {
    const message = {
        data: { type: 'canvas_update' },
        topic: 'canvas_updates'
    };
    try {
        await admin.messaging().send(message);
        console.log('FCM canvas update sent');
    } catch (err) {
        console.error('FCM send error:', err);
    }
}

// ------------------- Global variables -------------------
global.lastResetDate = new Date().toDateString();
app.use(express.json({ limit: '50mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// Security headers
app.use((req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('X-XSS-Protection', '1; mode=block');
    if (process.env.NODE_ENV === 'production') {
        res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
    }
    next();
});

// PWA routes
app.get('/manifest.json', (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.sendFile(path.join(__dirname, 'public', 'manifest.json'));
});
app.get('/sw.js', (req, res) => {
    res.setHeader('Content-Type', 'application/javascript');
    res.sendFile(path.join(__dirname, 'public', 'sw.js'));
});

// Canvas persistence
let canvasData = [];
const MAX_STROKES = 2000;
const CANVAS_DATA_FILE = path.join(__dirname, 'canvas-data.json');

// Load canvas data
async function loadCanvasData() {
    try {
        const data = await fs.readFile(CANVAS_DATA_FILE, 'utf8');
        canvasData = JSON.parse(data);
        console.log(`Loaded ${canvasData.length} canvas strokes from disk`);
        const today = new Date().toDateString();
        if (canvasData.length > 0 && canvasData[0].timestamp) {
            const dataDate = new Date(canvasData[0].timestamp).toDateString();
            if (dataDate !== today) {
                console.log('Canvas data from previous day, clearing...');
                canvasData = [];
            }
        }
    } catch (error) {
        console.log('No existing canvas data found, starting fresh');
        canvasData = [];
    }
}

// Save canvas data
async function saveCanvasData() {
    try {
        await fs.writeFile(CANVAS_DATA_FILE, JSON.stringify(canvasData));
        console.log(`Saved ${canvasData.length} canvas strokes to disk`);
    } catch (error) {
        console.error('Failed to save canvas data:', error);
    }
}

// Periodic save every 30s
setInterval(saveCanvasData, 30000);

// Save on exit
process.on('SIGINT', async () => {
    console.log('Shutting down server...');
    await saveCanvasData();
    process.exit(0);
});
process.on('SIGTERM', async () => {
    console.log('Server terminated');
    await saveCanvasData();
    process.exit(0);
});

// ------------------- Socket.IO -------------------
io.on('connection', (socket) => {
    console.log(`User connected: ${socket.id} (Total: ${io.engine.clientsCount})`);
    
    setTimeout(() => {
        console.log(`Sending ${canvasData.length} strokes to ${socket.id}`);
        socket.emit('canvas-data', canvasData);
    }, 200);

    // Draw event
    socket.on('draw', async (data) => {
        try {
            if (!data || typeof data.x0 !== 'number' || typeof data.y0 !== 'number' || 
                typeof data.x1 !== 'number' || typeof data.y1 !== 'number') return;

            const strokeData = { 
                ...data, 
                timestamp: Date.now(), 
                id: generateId(),
                userId: socket.id,
                type: 'draw'
            };

            canvasData.push(strokeData);
            socket.broadcast.emit('stroke-added', strokeData);

            if (canvasData.length > MAX_STROKES) {
                const removed = canvasData.length - MAX_STROKES;
                canvasData = canvasData.slice(-MAX_STROKES);
                console.log(`Trimmed ${removed} old strokes`);
            }

            await sendFCMUpdate();
        } catch (error) {
            console.error('Error handling draw event:', error);
            socket.emit('error', { message: 'Failed to process draw event' });
        }
    });

    // Daily reset
    socket.on('daily-reset', async () => {
        try {
            const today = new Date().toDateString();
            if (!global.lastResetDate || global.lastResetDate !== today) {
                global.lastResetDate = today;
                canvasData = [];
                io.emit('canvas-cleared');
                await saveCanvasData();
                await sendFCMUpdate();
                console.log(`Daily canvas reset triggered for ${today}`);
            }
        } catch (error) {
            console.error('Error handling daily reset:', error);
        }
    });

    // Erase event
    socket.on('erase', async (data) => {
        try {
            if (!data || typeof data.x0 !== 'number' || typeof data.y0 !== 'number' ||
                typeof data.x1 !== 'number' || typeof data.y1 !== 'number') return;

            const strokeData = { 
                ...data, 
                timestamp: Date.now(), 
                id: generateId(),
                userId: socket.id,
                type: 'erase'
            };

            canvasData.push(strokeData);
            socket.broadcast.emit('stroke-added', strokeData);

            if (canvasData.length > MAX_STROKES) canvasData = canvasData.slice(-MAX_STROKES);

            await sendFCMUpdate();
        } catch (error) {
            console.error('Error handling erase event:', error);
            socket.emit('error', { message: 'Failed to process erase event' });
        }
    });

    // Clear canvas
    socket.on('clear', async () => {
        try {
            const previousCount = canvasData.length;
            canvasData = [];
            io.emit('canvas-cleared');
            await saveCanvasData();
            await sendFCMUpdate();
            console.log(`Canvas cleared by ${socket.id} - removed ${previousCount} strokes`);
        } catch (error) {
            console.error('Error handling clear event:', error);
            socket.emit('error', { message: 'Failed to clear canvas' });
        }
    });

    // Undo
    socket.on('undo', async (data) => {
        try {
            if (data && data.targetLength && typeof data.targetLength === 'number') {
                if (data.targetLength >= 0 && data.targetLength < canvasData.length) {
                    const removedCount = canvasData.length - data.targetLength;
                    canvasData = canvasData.slice(0, data.targetLength);
                    io.emit('canvas-data', canvasData);
                    await sendFCMUpdate();
                    console.log(`Undo by ${socket.id} - removed ${removedCount} strokes`);
                }
            }
        } catch (error) {
            console.error('Error handling undo event:', error);
        }
    });

    // Request sync
    socket.on('request-sync', () => {
        try {
            socket.emit('canvas-data', canvasData);
        } catch (error) {
            console.error('Error handling sync request:', error);
        }
    });

    // Disconnect
    socket.on('disconnect', (reason) => {
        console.log(`User disconnected: ${socket.id} (${reason}) - Remaining: ${Math.max(0, io.engine.clientsCount - 1)}`);
    });

    // Socket errors
    socket.on('error', (error) => {
        console.error(`Socket error from ${socket.id}:`, error);
    });
});

// ------------------- API Endpoints -------------------
app.get('/api/health', (req, res) => {
    res.json({ 
        status: 'healthy', 
        strokes: canvasData.length,
        maxStrokes: MAX_STROKES,
        connections: io.engine.clientsCount,
        uptime: Math.floor(process.uptime()),
        memory: process.memoryUsage(),
        timestamp: new Date().toISOString(),
        version: '1.0.1'
    });
});

app.get('/api/canvas/stats', (req, res) => {
    const stats = {
        totalStrokes: canvasData.length,
        strokesByTool: {},
        strokesByHour: {},
        oldestStroke: null,
        newestStroke: null
    };

    if (canvasData.length > 0) {
        canvasData.forEach(stroke => {
            stats.strokesByTool[stroke.tool] = (stats.strokesByTool[stroke.tool] || 0) + 1;
            const hour = new Date(stroke.timestamp).getHours();
            stats.strokesByHour[hour] = (stats.strokesByHour[hour] || 0) + 1;
        });
        stats.oldestStroke = new Date(canvasData[0].timestamp).toISOString();
        stats.newestStroke = new Date(canvasData[canvasData.length - 1].timestamp).toISOString();
    }

    res.json(stats);
});

// Backup
app.get('/api/canvas/backup', async (req, res) => {
    try {
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Content-Disposition', 'attachment; filename="canvas-backup.json"');
        res.json({
            version: '1.0.1',
            exportDate: new Date().toISOString(),
            strokeCount: canvasData.length,
            data: canvasData
        });
    } catch (error) {
        res.status(500).json({ error: 'Failed to create backup' });
    }
});

// Restore
app.post('/api/canvas/restore', async (req, res) => {
    try {
        const { data } = req.body;
        if (!Array.isArray(data)) return res.status(400).json({ error: 'Invalid data format' });

        canvasData = data;
        await saveCanvasData();
        io.emit('canvas-data', canvasData);
        await sendFCMUpdate();

        res.json({ success: true, strokeCount: canvasData.length, message: 'Canvas restored successfully' });
    } catch (error) {
        res.status(500).json({ error: 'Failed to restore canvas data' });
    }
});

// Offline sync
app.post('/api/sync-canvas', async (req, res) => {
    try {
        const offlineStrokes = req.body;
        if (Array.isArray(offlineStrokes)) {
            canvasData.push(...offlineStrokes);
            if (canvasData.length > MAX_STROKES) canvasData = canvasData.slice(-MAX_STROKES);
            io.emit('canvas-data', canvasData);
            await sendFCMUpdate();
            res.json({ success: true, syncedStrokes: offlineStrokes.length });
        } else {
            res.status(400).json({ error: 'Invalid sync data' });
        }
    } catch (error) {
        res.status(500).json({ error: 'Sync failed' });
    }
});

// ------------------- Helper -------------------
function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
}

// ------------------- Start Server -------------------
const PORT = process.env.PORT || 3000;

loadCanvasData().then(() => {
    server.listen(PORT, () => {
        console.log(`Canvas PWA Server running on port ${PORT}`);
        console.log(`App available at: http://localhost:${PORT}`);
        console.log(`Health check: http://localhost:${PORT}/api/health`);
        console.log(`Canvas stats: http://localhost:${PORT}/api/canvas/stats`);
        console.log(`Canvas loaded with ${canvasData.length} strokes`);
    });
}).catch((error) => {
    console.error('Failed to load canvas data:', error);
    process.exit(1);
});

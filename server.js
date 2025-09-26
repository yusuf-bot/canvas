const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const path = require('path');
const fs = require('fs').promises;

const app = express();
const server = http.createServer(app);
const io = socketIo(server, {
    cors: {
        origin: process.env.NODE_ENV === 'production' ? false : "*",
        methods: ["GET", "POST"]
    }
});

// Middleware
app.use(express.json({ limit: '50mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// Security headers for PWA
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

// Store canvas data with persistence
let canvasData = [];
const MAX_STROKES = 2000;
const CANVAS_DATA_FILE = path.join(__dirname, 'canvas-data.json');

// Load existing canvas data on startup
async function loadCanvasData() {
    try {
        const data = await fs.readFile(CANVAS_DATA_FILE, 'utf8');
        canvasData = JSON.parse(data);
        console.log(`Loaded ${canvasData.length} canvas strokes from disk`);
    } catch (error) {
        console.log('No existing canvas data found, starting fresh');
        canvasData = [];
    }
}

// Save canvas data to disk
async function saveCanvasData() {
    try {
        await fs.writeFile(CANVAS_DATA_FILE, JSON.stringify(canvasData));
        console.log(`Saved ${canvasData.length} canvas strokes to disk`);
    } catch (error) {
        console.error('Failed to save canvas data:', error);
    }
}

// Periodic save every 30 seconds
setInterval(saveCanvasData, 30000);

// Save on process exit
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

// Socket.IO connection handling
io.on('connection', (socket) => {
    console.log(`User connected: ${socket.id} (Total: ${io.engine.clientsCount})`);
    
    // Send existing canvas data to new user with delay to ensure connection is stable
    setTimeout(() => {
        console.log(`Sending ${canvasData.length} strokes to ${socket.id}`);
        socket.emit('canvas-data', canvasData);
    }, 200);
    
    // Handle drawing events
    socket.on('draw', (data) => {
        try {
            // Validate incoming data
            if (!data || typeof data.x0 !== 'number' || typeof data.y0 !== 'number' || 
                typeof data.x1 !== 'number' || typeof data.y1 !== 'number') {
                console.log('Invalid draw data received from', socket.id);
                return;
            }
            
            const strokeData = { 
                ...data, 
                timestamp: Date.now(), 
                id: generateId(),
                userId: socket.id,
                type: 'draw'
            };
            
            canvasData.push(strokeData);
            console.log(`Draw stroke added: ${canvasData.length} total strokes`);
            
            // Broadcast to all other clients (not sender)
            socket.broadcast.emit('stroke-added', strokeData);
            
            // Limit strokes to prevent memory issues
            if (canvasData.length > MAX_STROKES) {
                const removed = canvasData.length - MAX_STROKES;
                canvasData = canvasData.slice(-MAX_STROKES);
                console.log(`Trimmed ${removed} old strokes`);
            }
        } catch (error) {
            console.error('Error handling draw event:', error);
            socket.emit('error', { message: 'Failed to process draw event' });
        }
    });
    
    // Handle erase events
    socket.on('erase', (data) => {
        try {
            // Validate incoming data
            if (!data || typeof data.x0 !== 'number' || typeof data.y0 !== 'number' ||
                typeof data.x1 !== 'number' || typeof data.y1 !== 'number') {
                console.log('Invalid erase data received from', socket.id);
                return;
            }
            
            const strokeData = { 
                ...data, 
                timestamp: Date.now(), 
                id: generateId(),
                userId: socket.id,
                type: 'erase'
            };
            
            canvasData.push(strokeData);
            console.log(`Erase stroke added: ${canvasData.length} total strokes`);
            
            // Broadcast to all other clients
            socket.broadcast.emit('stroke-added', strokeData);
            
            if (canvasData.length > MAX_STROKES) {
                canvasData = canvasData.slice(-MAX_STROKES);
            }
        } catch (error) {
            console.error('Error handling erase event:', error);
            socket.emit('error', { message: 'Failed to process erase event' });
        }
    });
    
    // Handle clear events
    socket.on('clear', () => {
        try {
            const previousCount = canvasData.length;
            canvasData = [];
            console.log(`Canvas cleared by ${socket.id} - removed ${previousCount} strokes`);
            
            // Broadcast to all clients including sender
            io.emit('canvas-cleared');
            
            // Save cleared state immediately
            saveCanvasData();
        } catch (error) {
            console.error('Error handling clear event:', error);
            socket.emit('error', { message: 'Failed to clear canvas' });
        }
    });
    
    // Handle undo events
    socket.on('undo', (data) => {
        try {
            if (data && data.targetLength && typeof data.targetLength === 'number') {
                if (data.targetLength >= 0 && data.targetLength < canvasData.length) {
                    const removedCount = canvasData.length - data.targetLength;
                    canvasData = canvasData.slice(0, data.targetLength);
                    console.log(`Undo by ${socket.id} - removed ${removedCount} strokes`);
                    
                    // Broadcast full canvas state to all clients
                    io.emit('canvas-data', canvasData);
                }
            }
        } catch (error) {
            console.error('Error handling undo event:', error);
        }
    });
    
    // Handle canvas sync request
    socket.on('request-sync', () => {
        try {
            console.log(`Sync requested by ${socket.id} - sending ${canvasData.length} strokes`);
            socket.emit('canvas-data', canvasData);
        } catch (error) {
            console.error('Error handling sync request:', error);
        }
    });
    
    // Handle disconnection
    socket.on('disconnect', (reason) => {
        console.log(`User disconnected: ${socket.id} (${reason}) - Remaining: ${Math.max(0, io.engine.clientsCount - 1)}`);
    });
    
    // Handle connection errors
    socket.on('error', (error) => {
        console.error(`Socket error from ${socket.id}:`, error);
    });
});

// API Routes
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
        // Analyze strokes
        canvasData.forEach(stroke => {
            // Count by tool
            stats.strokesByTool[stroke.tool] = (stats.strokesByTool[stroke.tool] || 0) + 1;
            
            // Count by hour
            const hour = new Date(stroke.timestamp).getHours();
            stats.strokesByHour[hour] = (stats.strokesByHour[hour] || 0) + 1;
        });
        
        stats.oldestStroke = new Date(canvasData[0].timestamp).toISOString();
        stats.newestStroke = new Date(canvasData[canvasData.length - 1].timestamp).toISOString();
    }
    
    res.json(stats);
});

// Canvas data backup endpoint
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

// Canvas data restore endpoint
app.post('/api/canvas/restore', async (req, res) => {
    try {
        const { data } = req.body;
        if (!Array.isArray(data)) {
            return res.status(400).json({ error: 'Invalid data format' });
        }
        
        canvasData = data;
        await saveCanvasData();
        
        // Notify all connected clients
        io.emit('canvas-data', canvasData);
        
        res.json({ 
            success: true, 
            strokeCount: canvasData.length,
            message: 'Canvas restored successfully' 
        });
    } catch (error) {
        res.status(500).json({ error: 'Failed to restore canvas data' });
    }
});

// Sync endpoint for offline data
app.post('/api/sync-canvas', async (req, res) => {
    try {
        const offlineStrokes = req.body;
        if (Array.isArray(offlineStrokes)) {
            // Add offline strokes to canvas data
            canvasData.push(...offlineStrokes);
            
            // Trim if necessary
            if (canvasData.length > MAX_STROKES) {
                canvasData = canvasData.slice(-MAX_STROKES);
            }
            
            // Notify all clients
            io.emit('canvas-data', canvasData);
            
            res.json({ 
                success: true, 
                syncedStrokes: offlineStrokes.length 
            });
        } else {
            res.status(400).json({ error: 'Invalid sync data' });
        }
    } catch (error) {
        res.status(500).json({ error: 'Sync failed' });
    }
});

// Generate unique ID for strokes
function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
}

// Start server
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
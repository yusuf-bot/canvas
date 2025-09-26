// Canvas PWA - Updated Script
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const socket = io();

// App state
let isDrawing = false;
let currentTool = 'inkPen';
let currentColor = '#06b6d4'; // Cyan default
let brushSize = 4; // Fixed size
let lastX = 0;
let lastY = 0;
let zoom = 1;
let offsetX = 0;
let offsetY = 0;

// Canvas management
let canvases = []; // Array to store multiple canvases
let currentCanvasId = 0;

// Touch handling
let isPanning = false;
let lastPanX = 0;
let lastPanY = 0;
let lastTouchDistance = 0;

// Drawing storage
let allStrokes = [];
let history = [];
let historyStep = -1;
const MAX_UNDO_STEPS = 5; // Limit undo to 5 times

// Tool properties
const toolProperties = {
    inkPen: { lineCap: 'round', opacity: 1.0, composite: 'source-over' },
    brush: { lineCap: 'round', opacity: 0.8, composite: 'source-over' },
    marker: { lineCap: 'square', opacity: 0.7, composite: 'source-over' },
    pencil: { lineCap: 'round', opacity: 0.9, composite: 'source-over' },
    highlighter: { lineCap: 'round', opacity: 0.3, composite: 'multiply' },
    eraser: { lineCap: 'round', opacity: 1.0, composite: 'destination-out' }
};

// Initialize canvas
function initCanvas() {
    const container = document.querySelector('.canvas-container');
    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    
    ctx.scale(dpr, dpr);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    
    redrawCanvas();
    saveState();
    initColorPicker();
}

function drawBackground() {
    const rect = canvas.getBoundingClientRect();
    // Black background like in the image
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, rect.width, rect.height);
}

function redrawCanvas() {
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    drawBackground();
    
    // Draw all strokes
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(zoom, zoom);
    
    allStrokes.forEach(stroke => {
        const props = toolProperties[stroke.tool] || toolProperties.inkPen;
        
        ctx.globalCompositeOperation = props.composite;
        ctx.strokeStyle = stroke.color;
        ctx.lineWidth = stroke.size;
        ctx.lineCap = props.lineCap;
        ctx.globalAlpha = props.opacity;
        
        ctx.beginPath();
        ctx.moveTo(stroke.x0, stroke.y0);
        ctx.lineTo(stroke.x1, stroke.y1);
        ctx.stroke();
    });
    
    ctx.restore();
}

function getCanvasPoint(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const x = (clientX - rect.left - offsetX) / zoom;
    const y = (clientY - rect.top - offsetY) / zoom;
    return { x, y };
}

function draw(e) {
    if (!isDrawing) return;
    
    const clientX = e.clientX || e.touches[0].clientX;
    const clientY = e.clientY || e.touches[0].clientY;
    const { x, y } = getCanvasPoint(clientX, clientY);
    
    const strokeData = {
        x0: lastX, y0: lastY, x1: x, y1: y,
        color: currentColor, size: brushSize, tool: currentTool,
        type: currentTool === 'eraser' ? 'erase' : 'draw',
        id: Date.now().toString(36) + Math.random().toString(36).substr(2)
    };
    
    // Add to local strokes immediately
    allStrokes.push(strokeData);
    
    // Draw stroke immediately for responsiveness
    drawSingleStroke(strokeData);
    
    // Send to server
    socket.emit(currentTool === 'eraser' ? 'erase' : 'draw', strokeData);
    
    [lastX, lastY] = [x, y];
}

function drawSingleStroke(strokeData) {
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(zoom, zoom);
    
    const props = toolProperties[strokeData.tool] || toolProperties.inkPen;
    ctx.globalCompositeOperation = props.composite;
    ctx.strokeStyle = strokeData.color;
    ctx.lineWidth = strokeData.size;
    ctx.lineCap = props.lineCap;
    ctx.globalAlpha = props.opacity;
    
    ctx.beginPath();
    ctx.moveTo(strokeData.x0, strokeData.y0);
    ctx.lineTo(strokeData.x1, strokeData.y1);
    ctx.stroke();
    
    ctx.restore();
}

function startDrawing(e) {
    e.preventDefault();
    
    const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
    const clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
    
    // Two finger gestures
    if (e.touches && e.touches.length === 2) {
        isPanning = true;
        const touch1 = e.touches[0];
        const touch2 = e.touches[1];
        lastPanX = (touch1.clientX + touch2.clientX) / 2;
        lastPanY = (touch1.clientY + touch2.clientY) / 2;
        lastTouchDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
        return;
    }
    
    // Start drawing
    if (!isPanning) {
        isDrawing = true;
        const { x, y } = getCanvasPoint(clientX, clientY);
        [lastX, lastY] = [x, y];
    }
}

function handleMove(e) {
    e.preventDefault();
    
    // Two finger pan/zoom
    if (e.touches && e.touches.length === 2 && isPanning) {
        const touch1 = e.touches[0];
        const touch2 = e.touches[1];
        const currentDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
        const currentX = (touch1.clientX + touch2.clientX) / 2;
        const currentY = (touch1.clientY + touch2.clientY) / 2;
        
        // Pinch zoom
        if (lastTouchDistance > 0) {
            const deltaDistance = currentDistance - lastTouchDistance;
            if (Math.abs(deltaDistance) > 3) {
                const zoomFactor = deltaDistance > 0 ? 1.02 : 0.98;
                zoom = Math.max(0.5, Math.min(3, zoom * zoomFactor));
                lastTouchDistance = currentDistance;
            }
        }
        
        // Two finger pan
        if (lastPanX !== 0 && lastPanY !== 0) {
            offsetX += (currentX - lastPanX) * 0.8;
            offsetY += (currentY - lastPanY) * 0.8;
            redrawCanvas();
        }
        
        lastPanX = currentX;
        lastPanY = currentY;
        return;
    }
    
    // Draw
    if (isDrawing) {
        draw(e);
    }
}

function stopDrawing() {
    if (isDrawing) {
        isDrawing = false;
        saveState();
    }
    isPanning = false;
    lastTouchDistance = 0;
}

function saveState() {
    historyStep++;
    if (historyStep < history.length) {
        history.length = historyStep;
    }
    
    // Only keep last 5 states for undo
    history.push(allStrokes.length);
    if (history.length > MAX_UNDO_STEPS) {
        history = history.slice(-MAX_UNDO_STEPS);
        historyStep = MAX_UNDO_STEPS - 1;
    }
    
    console.log(`State saved. History steps: ${history.length}, Current step: ${historyStep}`);
}

function undo() {
    if (historyStep > 0) {
        historyStep--;
        const targetLength = history[historyStep];
        
        if (targetLength < allStrokes.length) {
            allStrokes = allStrokes.slice(0, targetLength);
            redrawCanvas();
            
            // Notify server about undo
            socket.emit('undo', { targetLength: targetLength });
            
            console.log(`Undo performed. Strokes: ${allStrokes.length}, Steps remaining: ${historyStep}`);
        }
    } else {
        console.log('No more undo steps available');
    }
}

function clearCanvas() {
    allStrokes = [];
    redrawCanvas();
    history = [0];
    historyStep = 0;
    socket.emit('clear');
    console.log('Canvas cleared locally and sent to server');
}

function createNewCanvas() {
    // Save current canvas state
    canvases.push({
        id: currentCanvasId,
        strokes: [...allStrokes],
        timestamp: Date.now()
    });
    
    // Create new blank canvas
    currentCanvasId = Date.now();
    allStrokes = [];
    redrawCanvas();
    history = [0];
    historyStep = 0;
    
    console.log('Created new canvas, total canvases:', canvases.length + 1);
}

// Color picker functions
function initColorPicker() {
    const spectrum = document.getElementById('colorSpectrum');
    const hueSlider = document.getElementById('hueSlider');
    
    if (!spectrum || !hueSlider) return;
    
    const spectrumCtx = spectrum.getContext('2d');
    const hueCtx = hueSlider.getContext('2d');
    
    // Draw hue slider
    const hueGradient = hueCtx.createLinearGradient(0, 0, 280, 0);
    hueGradient.addColorStop(0, '#ff0000');
    hueGradient.addColorStop(0.17, '#ffff00');
    hueGradient.addColorStop(0.33, '#00ff00');
    hueGradient.addColorStop(0.5, '#00ffff');
    hueGradient.addColorStop(0.67, '#0000ff');
    hueGradient.addColorStop(0.83, '#ff00ff');
    hueGradient.addColorStop(1, '#ff0000');
    
    hueCtx.fillStyle = hueGradient;
    hueCtx.fillRect(0, 0, 280, 30);
    
    updateColorSpectrum('#00ffff'); // Start with cyan
}

function updateColorSpectrum(hueColor) {
    const spectrum = document.getElementById('colorSpectrum');
    if (!spectrum) return;
    
    const ctx = spectrum.getContext('2d');
    
    ctx.clearRect(0, 0, 280, 280);
    ctx.fillStyle = hueColor;
    ctx.fillRect(0, 0, 280, 280);
    
    const whiteGradient = ctx.createLinearGradient(0, 0, 280, 0);
    whiteGradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
    whiteGradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = whiteGradient;
    ctx.fillRect(0, 0, 280, 280);
    
    const blackGradient = ctx.createLinearGradient(0, 0, 0, 280);
    blackGradient.addColorStop(0, 'rgba(0, 0, 0, 0)');
    blackGradient.addColorStop(1, 'rgba(0, 0, 0, 1)');
    ctx.fillStyle = blackGradient;
    ctx.fillRect(0, 0, 280, 280);
}

function hslToHex(h, s, l) {
    l /= 100;
    const a = s * Math.min(l, 1 - l) / 100;
    const f = n => {
        const k = (n + h / 30) % 12;
        const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
        return Math.round(255 * color).toString(16).padStart(2, '0');
    };
    return `#${f(0)}${f(8)}${f(4)}`;
}

// Modal functions
function showModal(modalId) {
    document.getElementById(modalId).classList.add('active');
    document.getElementById(modalId).classList.remove('hidden');
    document.getElementById(modalId).classList.add('flex');
}

function hideModal(modalId) {
    document.getElementById(modalId).classList.remove('active', 'flex');
    document.getElementById(modalId).classList.add('hidden');
}

// Socket events - Fixed syncing issues
socket.on('connect', () => {
    console.log('Connected to server with ID:', socket.id);
    // Request latest canvas data on connect
    setTimeout(() => {
        socket.emit('request-sync');
    }, 300);
});

socket.on('canvas-data', (data) => {
    console.log('Received canvas data:', data.length, 'strokes');
    if (Array.isArray(data)) {
        allStrokes = data;
        redrawCanvas();
        
        // Reset history to current state
        history = [allStrokes.length];
        historyStep = 0;
        
        console.log('Canvas synchronized with server');
    }
});

socket.on('stroke-added', (strokeData) => {
    if (strokeData && typeof strokeData.x0 === 'number' && typeof strokeData.y0 === 'number') {
        // Add stroke from other user
        allStrokes.push(strokeData);
        
        // Draw the new stroke immediately for performance
        drawSingleStroke(strokeData);
        
        console.log('Received stroke from other user:', strokeData.tool);
    }
});

socket.on('canvas-cleared', () => {
    console.log('Canvas cleared by another user');
    allStrokes = [];
    redrawCanvas();
    history = [0];
    historyStep = 0;
});

socket.on('disconnect', (reason) => {
    console.log('Disconnected from server:', reason);
    // Attempt to reconnect after delay
    setTimeout(() => {
        if (!socket.connected) {
            console.log('Attempting to reconnect...');
            socket.connect();
        }
    }, 2000);
});

socket.on('connect_error', (error) => {
    console.error('Connection error:', error);
});

socket.on('error', (error) => {
    console.error('Socket error:', error);
});

function stopDrawing() {
    if (isDrawing) {
        isDrawing = false;
        saveState();
    }
    isPanning = false;
    lastTouchDistance = 0;
}

function saveState() {
    historyStep++;
    if (historyStep < history.length) {
        history.length = historyStep;
    }
    history.push([...allStrokes]);
}

function undo() {
    if (historyStep > 0) {
        historyStep--;
        allStrokes = [...history[historyStep]];
        redrawCanvas();
    }
}

function clearCanvas() {
    allStrokes = [];
    redrawCanvas();
    history = [];
    historyStep = -1;
    saveState();
    socket.emit('clear');
}

function createNewCanvas() {
    // Save current canvas state
    canvases.push({
        id: currentCanvasId,
        strokes: [...allStrokes],
        timestamp: Date.now()
    });
    
    // Create new blank canvas
    currentCanvasId = Date.now();
    allStrokes = [];
    redrawCanvas();
    history = [];
    historyStep = -1;
    saveState();
    
    console.log('Created new canvas, total canvases:', canvases.length + 1);
}

// Color picker functions
function initColorPicker() {
    const spectrum = document.getElementById('colorSpectrum');
    const hueSlider = document.getElementById('hueSlider');
    
    if (!spectrum || !hueSlider) return;
    
    const spectrumCtx = spectrum.getContext('2d');
    const hueCtx = hueSlider.getContext('2d');
    
    // Draw hue slider
    const hueGradient = hueCtx.createLinearGradient(0, 0, 280, 0);
    hueGradient.addColorStop(0, '#ff0000');
    hueGradient.addColorStop(0.17, '#ffff00');
    hueGradient.addColorStop(0.33, '#00ff00');
    hueGradient.addColorStop(0.5, '#00ffff');
    hueGradient.addColorStop(0.67, '#0000ff');
    hueGradient.addColorStop(0.83, '#ff00ff');
    hueGradient.addColorStop(1, '#ff0000');
    
    hueCtx.fillStyle = hueGradient;
    hueCtx.fillRect(0, 0, 280, 30);
    
    updateColorSpectrum('#00ffff'); // Start with cyan
}

function updateColorSpectrum(hueColor) {
    const spectrum = document.getElementById('colorSpectrum');
    if (!spectrum) return;
    
    const ctx = spectrum.getContext('2d');
    
    ctx.clearRect(0, 0, 280, 280);
    ctx.fillStyle = hueColor;
    ctx.fillRect(0, 0, 280, 280);
    
    const whiteGradient = ctx.createLinearGradient(0, 0, 280, 0);
    whiteGradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
    whiteGradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = whiteGradient;
    ctx.fillRect(0, 0, 280, 280);
    
    const blackGradient = ctx.createLinearGradient(0, 0, 0, 280);
    blackGradient.addColorStop(0, 'rgba(0, 0, 0, 0)');
    blackGradient.addColorStop(1, 'rgba(0, 0, 0, 1)');
    ctx.fillStyle = blackGradient;
    ctx.fillRect(0, 0, 280, 280);
}

function hslToHex(h, s, l) {
    l /= 100;
    const a = s * Math.min(l, 1 - l) / 100;
    const f = n => {
        const k = (n + h / 30) % 12;
        const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
        return Math.round(255 * color).toString(16).padStart(2, '0');
    };
    return `#${f(0)}${f(8)}${f(4)}`;
}

// Modal functions
function showModal(modalId) {
    document.getElementById(modalId).classList.add('active');
    document.getElementById(modalId).classList.remove('hidden');
    document.getElementById(modalId).classList.add('flex');
}

function hideModal(modalId) {
    document.getElementById(modalId).classList.remove('active', 'flex');
    document.getElementById(modalId).classList.add('hidden');
}

// Socket events - Fixed syncing issues
socket.on('connect', () => {
    console.log('Connected to server');
    // Request latest canvas data on connect
    socket.emit('request-sync');
});

socket.on('canvas-data', (data) => {
    console.log('Received canvas data:', data.length, 'strokes');
    if (Array.isArray(data)) {
        allStrokes = data;
        redrawCanvas();
        saveState();
    }
});

socket.on('draw', (data) => {
    if (data && typeof data.x0 === 'number' && typeof data.y0 === 'number') {
        allStrokes.push(data);
        
        // Draw the new stroke immediately without full redraw for performance
        const rect = canvas.getBoundingClientRect();
        ctx.save();
        ctx.translate(offsetX, offsetY);
        ctx.scale(zoom, zoom);
        
        const props = toolProperties[data.tool] || toolProperties.inkPen;
        ctx.globalCompositeOperation = props.composite;
        ctx.strokeStyle = data.color;
        ctx.lineWidth = data.size;
        ctx.lineCap = props.lineCap;
        ctx.globalAlpha = props.opacity;
        
        ctx.beginPath();
        ctx.moveTo(data.x0, data.y0);
        ctx.lineTo(data.x1, data.y1);
        ctx.stroke();
        ctx.restore();
    }
});

socket.on('erase', (data) => {
    if (data && typeof data.x0 === 'number' && typeof data.y0 === 'number') {
        allStrokes.push(data);
        
        // Apply erase stroke immediately
        const rect = canvas.getBoundingClientRect();
        ctx.save();
        ctx.translate(offsetX, offsetY);
        ctx.scale(zoom, zoom);
        
        ctx.globalCompositeOperation = 'destination-out';
        ctx.lineWidth = data.size;
        ctx.lineCap = 'round';
        ctx.globalAlpha = 1.0;
        
        ctx.beginPath();
        ctx.moveTo(data.x0, data.y0);
        ctx.lineTo(data.x1, data.y1);
        ctx.stroke();
        ctx.restore();
    }
});

socket.on('clear', () => {
    console.log('Canvas cleared by another user');
    allStrokes = [];
    redrawCanvas();
    history = [];
    historyStep = -1;
    saveState();
});

socket.on('disconnect', (reason) => {
    console.log('Disconnected from server:', reason);
    // Attempt to reconnect
    setTimeout(() => {
        if (!socket.connected) {
            socket.connect();
        }
    }, 2000);
});

socket.on('connect_error', (error) => {
    console.error('Connection error:', error);
});

socket.on('error', (error) => {
    console.error('Socket error:', error);
});

// Event listeners
canvas.addEventListener('mousedown', startDrawing);
canvas.addEventListener('mousemove', handleMove);
canvas.addEventListener('mouseup', stopDrawing);
canvas.addEventListener('touchstart', startDrawing, { passive: false });
canvas.addEventListener('touchmove', handleMove, { passive: false });
canvas.addEventListener('touchend', stopDrawing, { passive: false });

// Prevent context menu
canvas.addEventListener('contextmenu', e => e.preventDefault());

// Button event listeners
document.getElementById('deleteBtn').addEventListener('click', () => {
    showModal('confirmModal');
});

document.getElementById('newCanvasBtn').addEventListener('click', createNewCanvas);

document.getElementById('saveBtn').addEventListener('click', () => {
    const link = document.createElement('a');
    link.download = 'canvas-drawing.png';
    link.href = canvas.toDataURL();
    link.click();
});

document.getElementById('shareBtn').addEventListener('click', async () => {
    try {
        if (navigator.share && navigator.canShare) {
            const blob = await new Promise(resolve => canvas.toBlob(resolve));
            const file = new File([blob], 'canvas-drawing.png', { type: 'image/png' });
            await navigator.share({
                title: 'Canvas Drawing',
                text: 'Check out my drawing!',
                files: [file]
            });
        } else {
            // Fallback - download
            const link = document.createElement('a');
            link.download = 'canvas-drawing.png';
            link.href = canvas.toDataURL();
            link.click();
        }
    } catch (err) {
        console.log('Share cancelled or failed');
        // Fallback to download
        const link = document.createElement('a');
        link.download = 'canvas-drawing.png';
        link.href = canvas.toDataURL();
        link.click();
    }
});

document.getElementById('undoBtn').addEventListener('click', undo);

document.getElementById('toolBtn').addEventListener('click', () => {
    showModal('toolsModal');
});

document.getElementById('colorPicker').addEventListener('click', () => {
    showModal('colorModal');
});

// Color selection
document.querySelectorAll('.color-option').forEach(option => {
    option.addEventListener('click', () => {
        document.querySelectorAll('.color-option').forEach(opt => opt.classList.remove('selected'));
        option.classList.add('selected');
        currentColor = option.dataset.color;
        document.getElementById('colorPicker').style.background = currentColor;
        hideModal('colorModal');
    });
});

// Custom color picker
document.getElementById('customColorBtn').addEventListener('click', () => {
    hideModal('colorModal');
    showModal('customColorModal');
});

// Custom color picker interactions
let currentHue = 180; // Start with cyan hue

document.getElementById('hueSlider').addEventListener('click', (e) => {
    const rect = e.target.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const hue = (x / 280) * 360;
    currentHue = hue;
    
    const hueColor = hslToHex(hue, 100, 50);
    updateColorSpectrum(hueColor);
    
    const indicator = document.getElementById('hueIndicator');
    indicator.style.left = x + 'px';
    
    updatePreviewColor();
});

document.getElementById('colorSpectrum').addEventListener('click', (e) => {
    const rect = e.target.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Get the actual color from the canvas
    const spectrumCtx = e.target.getContext('2d');
    const imageData = spectrumCtx.getImageData(x, y, 1, 1);
    const [r, g, b] = imageData.data;
    
    document.getElementById('rgbR').value = r;
    document.getElementById('rgbG').value = g;
    document.getElementById('rgbB').value = b;
    
    updatePreviewColor();
    
    const indicator = document.getElementById('spectrumIndicator');
    indicator.style.left = x + 'px';
    indicator.style.top = y + 'px';
});

function updatePreviewColor() {
    const r = parseInt(document.getElementById('rgbR').value) || 0;
    const g = parseInt(document.getElementById('rgbG').value) || 180;
    const b = parseInt(document.getElementById('rgbB').value) || 216;
    
    const color = `rgb(${r}, ${g}, ${b})`;
    document.getElementById('colorPreview').style.backgroundColor = color;
    document.querySelector('.custom-color-preview').style.backgroundColor = color;
}

document.getElementById('confirmCustomColor').addEventListener('click', () => {
    const r = parseInt(document.getElementById('rgbR').value) || 0;
    const g = parseInt(document.getElementById('rgbG').value) || 180;
    const b = parseInt(document.getElementById('rgbB').value) || 216;
    
    currentColor = `rgb(${Math.min(255, Math.max(0, r))}, ${Math.min(255, Math.max(0, g))}, ${Math.min(255, Math.max(0, b))})`;
    document.getElementById('colorPicker').style.backgroundColor = currentColor;
    
    // Update selected color in main palette
    document.querySelectorAll('.color-option').forEach(opt => opt.classList.remove('selected'));
    
    hideModal('customColorModal');
});

document.getElementById('cancelCustomColor').addEventListener('click', () => {
    hideModal('customColorModal');
});

// RGB input validation and live update
['rgbR', 'rgbG', 'rgbB'].forEach(id => {
    document.getElementById(id).addEventListener('input', (e) => {
        let value = parseInt(e.target.value);
        if (value > 255) e.target.value = 255;
        if (value < 0) e.target.value = 0;
        updatePreviewColor();
    });
});

// Tool selection
document.querySelectorAll('.tool-option').forEach(option => {
    option.addEventListener('click', () => {
        document.querySelectorAll('.tool-option').forEach(opt => opt.classList.remove('active'));
        option.classList.add('active');
        currentTool = option.dataset.tool;
        hideModal('toolsModal');
    });
});

// Confirm delete
document.getElementById('cancelDelete').addEventListener('click', () => {
    hideModal('confirmModal');
});

document.getElementById('confirmDelete').addEventListener('click', () => {
    clearCanvas();
    hideModal('confirmModal');
});

// Close modals when clicking outside
document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('active', 'flex');
            modal.classList.add('hidden');
        }
    });
});

// PWA Installation
let deferredPrompt;
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
});

// Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then((registration) => {
                console.log('SW registered: ', registration);
            })
            .catch((registrationError) => {
                console.log('SW registration failed: ', registrationError);
            });
    });
}

// Resize handler
window.addEventListener('resize', () => {
    setTimeout(initCanvas, 100);
});

// Initialize
initCanvas();
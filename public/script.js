// Canvas PWA - Fixed Script
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const socket = io();

// App state
let isDrawing = false;
let currentTool = 'Pen';
let currentColor = '#06b6d4'; // Cyan default
let brushSize = 4; // Fixed size
let lastX = 0;
let lastY = 0;
let zoom = 1;
let offsetX = 0;
let offsetY = 0;

// Touch handling
let isPanning = false;
let lastPanX = 0;
let lastPanY = 0;
let lastTouchDistance = 0;

// Drawing storage
let allStrokes = [];
let history = [];
let historyStep = -1;
const MAX_UNDO_STEPS = 5;

// Tool properties
const toolProperties = {
    Pen: { lineCap: 'round', opacity: 1.0, composite: 'source-over' },
    eraser: { lineCap: 'round', opacity: 1.0, composite: 'destination-out' }
};

// Daily canvas reset
const CANVAS_DATE_KEY = 'canvas_date';

function checkDailyReset() {
    const today = new Date().toDateString();
    const savedDate = localStorage.getItem(CANVAS_DATE_KEY);
    
    if (savedDate !== today) {
        localStorage.setItem(CANVAS_DATE_KEY, today);
        socket.emit('daily-reset');
    }
}

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
    checkDailyReset();
}

function drawBackground() {
    const rect = canvas.getBoundingClientRect();
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, rect.width, rect.height);
}

function redrawCanvas() {
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    drawBackground();
    
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(zoom, zoom);
    
    allStrokes.forEach(stroke => {
        // Check if it's an eraser stroke
        if (stroke.tool === 'eraser') {
            ctx.globalCompositeOperation = 'destination-out';
        } else {
            ctx.globalCompositeOperation = 'source-over';
        }
        
        ctx.strokeStyle = stroke.color;
        ctx.lineWidth = stroke.size;
        ctx.lineCap = 'round';
        ctx.globalAlpha = 1.0;
        
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
    
    allStrokes.push(strokeData);
    drawSingleStroke(strokeData);
    socket.emit(currentTool === 'eraser' ? 'erase' : 'draw', strokeData);
    
    [lastX, lastY] = [x, y];
}

function drawSingleStroke(strokeData) {
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(zoom, zoom);
    
    // Check if it's an eraser stroke
    if (strokeData.tool === 'eraser') {
        ctx.globalCompositeOperation = 'destination-out';
    } else {
        ctx.globalCompositeOperation = 'source-over';
    }
    
    ctx.strokeStyle = strokeData.color;
    ctx.lineWidth = strokeData.size;
    ctx.lineCap = 'round';
    ctx.globalAlpha = 1.0;
    
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
    
    if (e.touches && e.touches.length === 2) {
        isPanning = true;
        const touch1 = e.touches[0];
        const touch2 = e.touches[1];
        lastPanX = (touch1.clientX + touch2.clientX) / 2;
        lastPanY = (touch1.clientY + touch2.clientY) / 2;
        lastTouchDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
        return;
    }
    
    if (!isPanning) {
        isDrawing = true;
        const { x, y } = getCanvasPoint(clientX, clientY);
        [lastX, lastY] = [x, y];
    }
}

function handleMove(e) {
    e.preventDefault();
    
    if (e.touches && e.touches.length === 2 && isPanning) {
        const touch1 = e.touches[0];
        const touch2 = e.touches[1];
        const currentDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
        const currentX = (touch1.clientX + touch2.clientX) / 2;
        const currentY = (touch1.clientY + touch2.clientY) / 2;
        
        if (lastTouchDistance > 0) {
            const deltaDistance = currentDistance - lastTouchDistance;
            if (Math.abs(deltaDistance) > 3) {
                const zoomFactor = deltaDistance > 0 ? 1.02 : 0.98;
                zoom = Math.max(0.5, Math.min(3, zoom * zoomFactor));
                lastTouchDistance = currentDistance;
            }
        }
        
        if (lastPanX !== 0 && lastPanY !== 0) {
            offsetX += (currentX - lastPanX) * 0.8;
            offsetY += (currentY - lastPanY) * 0.8;
            redrawCanvas();
        }
        
        lastPanX = currentX;
        lastPanY = currentY;
        return;
    }
    
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
    
    history.push(allStrokes.length);
    if (history.length > MAX_UNDO_STEPS) {
        history = history.slice(-MAX_UNDO_STEPS);
        historyStep = MAX_UNDO_STEPS - 1;
    }
}

function undo() {
    if (historyStep > 0) {
        historyStep--;
        const targetLength = history[historyStep];
        
        if (targetLength < allStrokes.length) {
            allStrokes = allStrokes.slice(0, targetLength);
            redrawCanvas();
            socket.emit('undo', { targetLength: targetLength });
        }
    }
}

function clearCanvas() {
    allStrokes = [];
    redrawCanvas();
    history = [0];
    historyStep = 0;
    socket.emit('clear');
}

// Color picker functions
function initColorPicker() {
    const spectrum = document.getElementById('colorSpectrum');
    const hueSlider = document.getElementById('hueSlider');
    
    if (!spectrum || !hueSlider) return;
    
    const spectrumCtx = spectrum.getContext('2d');
    const hueCtx = hueSlider.getContext('2d');
    
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
    
    updateColorSpectrum('#00ffff');
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

function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(x => {
        const hex = Math.min(255, Math.max(0, x)).toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    }).join('');
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

// Socket events
socket.on('connect', () => {
    console.log('Connected to server');
    setTimeout(() => {
        socket.emit('request-sync');
    }, 300);
});

socket.on('canvas-data', (data) => {
    if (Array.isArray(data)) {
        allStrokes = data;
        redrawCanvas();
        history = [allStrokes.length];
        historyStep = 0;
    }
});

socket.on('stroke-added', (strokeData) => {
    if (strokeData && typeof strokeData.x0 === 'number' && typeof strokeData.y0 === 'number') {
        allStrokes.push(strokeData);
        drawSingleStroke(strokeData);
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


socket.on('canvas-cleared', () => {
    allStrokes = [];
    redrawCanvas();
    history = [0];
    historyStep = 0;
});

socket.on('disconnect', (reason) => {
    console.log('Disconnected:', reason);
    setTimeout(() => {
        if (!socket.connected) {
            socket.connect();
        }
    }, 2000);
});

// Event listeners
canvas.addEventListener('mousedown', startDrawing);
canvas.addEventListener('mousemove', handleMove);
canvas.addEventListener('mouseup', stopDrawing);
canvas.addEventListener('touchstart', startDrawing, { passive: false });
canvas.addEventListener('touchmove', handleMove, { passive: false });
canvas.addEventListener('touchend', stopDrawing, { passive: false });
canvas.addEventListener('contextmenu', e => e.preventDefault());

// Button event listeners
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
            const link = document.createElement('a');
            link.download = 'canvas-drawing.png';
            link.href = canvas.toDataURL();
            link.click();
        }
    } catch (err) {
        const link = document.createElement('a');
        link.download = 'canvas-drawing.png';
        link.href = canvas.toDataURL();
        link.click();
    }
});

document.getElementById('undoBtn').addEventListener('click', undo);

// Size slider
document.getElementById('sizeSlider').addEventListener('input', (e) => {
    brushSize = parseInt(e.target.value);
    document.getElementById('sizeValue').textContent = brushSize + 'px';
    console.log('Brush size changed to:', brushSize);
});
// Tool switching - Fix for pen and eraser buttons
const toolButtons = document.querySelectorAll('[data-tool]');
toolButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const tool = btn.getAttribute('data-tool');
        if (tool === 'pen') {
            currentTool = 'Pen';
            console.log('Switched to Pen');
        } else if (tool === 'eraser') {
            currentTool = 'eraser';
            console.log('Switched to Eraser');
        }
    });
});

// Color picker
document.getElementById('colorPicker').addEventListener('click', () => {
    showModal('colorModal');
});

document.querySelectorAll('.color-option').forEach(option => {
    option.addEventListener('click', () => {
        document.querySelectorAll('.color-option').forEach(opt => opt.classList.remove('selected'));
        option.classList.add('selected');
        currentColor = option.dataset.color;
        document.getElementById('colorPicker').style.backgroundColor = currentColor;
        hideModal('colorModal');
    });
});

// Custom color picker
document.getElementById('customColorBtn').addEventListener('click', () => {
    hideModal('colorModal');
    showModal('customColorModal');
});

let currentHue = 180;

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
    
    const hexColor = rgbToHex(r, g, b);
    document.getElementById('colorPreview').style.backgroundColor = hexColor;
    document.querySelector('.custom-color-preview').style.backgroundColor = hexColor;
}

document.getElementById('confirmCustomColor').addEventListener('click', () => {
    const r = parseInt(document.getElementById('rgbR').value) || 0;
    const g = parseInt(document.getElementById('rgbG').value) || 180;
    const b = parseInt(document.getElementById('rgbB').value) || 216;
    
    currentColor = rgbToHex(r, g, b);
    document.getElementById('colorPicker').style.backgroundColor = currentColor;
    
    document.querySelectorAll('.color-option').forEach(opt => opt.classList.remove('selected'));
    
    hideModal('customColorModal');
    console.log('Custom color set to:', currentColor);
});

document.getElementById('cancelCustomColor').addEventListener('click', () => {
    hideModal('customColorModal');
});

['rgbR', 'rgbG', 'rgbB'].forEach(id => {
    document.getElementById(id).addEventListener('input', (e) => {
        let value = parseInt(e.target.value);
        if (value > 255) e.target.value = 255;
        if (value < 0) e.target.value = 0;
        updatePreviewColor();
    });
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
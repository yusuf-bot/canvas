const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const socket = io();

// Canvas state
let isDrawing = false;
let currentTool = 'inkPen';
let currentColor = '#3b82f6';
let brushSize = 3;
let lastX = 0;
let lastY = 0;
let zoom = 1;
let offsetX = 0;
let offsetY = 0;
let eraserMode = 'pen';

// Pan state
let isPanning = false;
let lastPanX = 0;
let lastPanY = 0;
let lastTouchDistance = 0;

// Drawing storage for persistence
let allStrokes = [];

// History
let history = [];
let historyStep = -1;

// Tool properties
const toolProperties = {
    inkPen: { lineCap: 'round', opacity: 1 },
    brush: { lineCap: 'round', opacity: 0.8 },
    marker: { lineCap: 'square', opacity: 0.7 },
    calligraphy: { lineCap: 'butt', opacity: 1 }
};

// Initialize canvas
function initCanvas() {
    const dpr = window.devicePixelRatio || 1;
    
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    canvas.style.width = window.innerWidth + 'px';
    canvas.style.height = window.innerHeight + 'px';
    
    ctx.scale(dpr, dpr);
    
    redrawCanvas();
    initColorPicker();
}

function drawBackground() {
    // Fill with white
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
    
    // Draw more visible grid dots
    ctx.fillStyle = '#c0c0c0';
    const gridSize = 20;
    const dotSize = 2;
    
    // Calculate grid based on zoom and offset
    const scaledGridSize = gridSize * zoom;
    const startX = (offsetX % scaledGridSize);
    const startY = (offsetY % scaledGridSize);
    
    for (let x = startX; x < window.innerWidth; x += scaledGridSize) {
        for (let y = startY; y < window.innerHeight; y += scaledGridSize) {
            ctx.fillRect(x - dotSize/2, y - dotSize/2, dotSize, dotSize);
        }
    }
}

function redrawCanvas() {
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    drawBackground();
    
    // Redraw all strokes
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(zoom, zoom);
    
    allStrokes.forEach(stroke => {
        if (stroke.type === 'erase') {
            ctx.globalCompositeOperation = 'destination-out';
            ctx.lineWidth = stroke.size;
            ctx.globalAlpha = 1;
            ctx.lineCap = 'round';
        } else {
            const props = toolProperties[stroke.tool] || toolProperties.inkPen;
            ctx.globalCompositeOperation = 'source-over';
            ctx.strokeStyle = stroke.color;
            ctx.lineWidth = stroke.size;
            ctx.lineCap = props.lineCap;
            ctx.globalAlpha = props.opacity;
        }
        
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
        type: currentTool === 'eraser' ? 'erase' : 'draw'
    };
    
    // Add to local storage
    allStrokes.push(strokeData);
    
    // Draw immediately
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(zoom, zoom);
    
    if (currentTool === 'eraser') {
        ctx.globalCompositeOperation = 'destination-out';
        ctx.lineWidth = brushSize;
        ctx.globalAlpha = 1;
        ctx.lineCap = 'round';
    } else {
        const props = toolProperties[currentTool];
        ctx.globalCompositeOperation = 'source-over';
        ctx.strokeStyle = currentColor;
        ctx.lineWidth = brushSize;
        ctx.lineCap = props.lineCap;
        ctx.globalAlpha = props.opacity;
    }
    
    ctx.beginPath();
    ctx.moveTo(lastX, lastY);
    ctx.lineTo(x, y);
    ctx.stroke();
    ctx.restore();
    
    // Emit to server
    socket.emit(currentTool === 'eraser' ? 'erase' : 'draw', strokeData);
    
    [lastX, lastY] = [x, y];
}

function startDrawing(e) {
    e.preventDefault();
    
    const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
    const clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
    
    // Handle two-finger gestures
    if (e.touches && e.touches.length === 2) {
        isPanning = true;
        const touch1 = e.touches[0];
        const touch2 = e.touches[1];
        lastPanX = (touch1.clientX + touch2.clientX) / 2;
        lastPanY = (touch1.clientY + touch2.clientY) / 2;
        lastTouchDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
        return;
    }
    
    // Handle single finger or mouse
    if (e.shiftKey) {
        isPanning = true;
        lastPanX = clientX;
        lastPanY = clientY;
    } else {
        isDrawing = true;
        const { x, y } = getCanvasPoint(clientX, clientY);
        [lastX, lastY] = [x, y];
    }
}

function handleMove(e) {
    e.preventDefault();
    
    // Handle two-finger pan and zoom
    if (e.touches && e.touches.length === 2 && isPanning) {
        const touch1 = e.touches[0];
        const touch2 = e.touches[1];
        const currentDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
        const currentX = (touch1.clientX + touch2.clientX) / 2;
        const currentY = (touch1.clientY + touch2.clientY) / 2;
        
        // Handle pinch zoom
        if (lastTouchDistance > 0) {
            const deltaDistance = currentDistance - lastTouchDistance;
            if (Math.abs(deltaDistance) > 5) {
                const zoomFactor = deltaDistance > 0 ? 1.05 : 0.95;
                changeZoom(zoomFactor);
                lastTouchDistance = currentDistance;
            }
        }
        
        // Handle two-finger pan
        if (lastPanX !== 0 && lastPanY !== 0) {
            offsetX += (currentX - lastPanX);
            offsetY += (currentY - lastPanY);
            redrawCanvas();
        }
        
        lastPanX = currentX;
        lastPanY = currentY;
        return;
    }
    
    // Handle single finger/mouse pan
    if (isPanning && !isDrawing) {
        const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : lastPanX);
        const clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : lastPanY);
        
        offsetX += (clientX - lastPanX);
        offsetY += (clientY - lastPanY);
        lastPanX = clientX;
        lastPanY = clientY;
        
        redrawCanvas();
        return;
    }
    
    // Handle drawing
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

function changeZoom(factor) {
    zoom = Math.max(0.1, Math.min(5, zoom * factor));
    document.getElementById('zoomInput').value = Math.round(zoom * 100);
    redrawCanvas();
}

function saveState() {
    historyStep++;
    if (historyStep < history.length) {
        history.length = historyStep;
    }
    // Store current strokes instead of image data for better performance
    history.push([...allStrokes]);
}

function undo() {
    if (historyStep > 0) {
        historyStep--;
        allStrokes = [...history[historyStep]];
        redrawCanvas();
    }
}

// Color picker functions
function initColorPicker() {
    const spectrum = document.getElementById('colorSpectrum');
    const spectrumCtx = spectrum.getContext('2d');
    const hueSlider = document.getElementById('hueSlider');
    const hueCtx = hueSlider.getContext('2d');
    
    // Draw hue slider
    const hueGradient = hueCtx.createLinearGradient(0, 0, 240, 0);
    hueGradient.addColorStop(0, '#ff0000');
    hueGradient.addColorStop(0.17, '#ffff00');
    hueGradient.addColorStop(0.33, '#00ff00');
    hueGradient.addColorStop(0.5, '#00ffff');
    hueGradient.addColorStop(0.67, '#0000ff');
    hueGradient.addColorStop(0.83, '#ff00ff');
    hueGradient.addColorStop(1, '#ff0000');
    
    hueCtx.fillStyle = hueGradient;
    hueCtx.fillRect(0, 0, 240, 20);
    
    updateColorSpectrum('#ff0000');
}

function updateColorSpectrum(hueColor) {
    const spectrum = document.getElementById('colorSpectrum');
    const ctx = spectrum.getContext('2d');
    
    ctx.clearRect(0, 0, 240, 240);
    ctx.fillStyle = hueColor;
    ctx.fillRect(0, 0, 240, 240);
    
    const whiteGradient = ctx.createLinearGradient(0, 0, 240, 0);
    whiteGradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
    whiteGradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = whiteGradient;
    ctx.fillRect(0, 0, 240, 240);
    
    const blackGradient = ctx.createLinearGradient(0, 0, 0, 240);
    blackGradient.addColorStop(0, 'rgba(0, 0, 0, 0)');
    blackGradient.addColorStop(1, 'rgba(0, 0, 0, 1)');
    ctx.fillStyle = blackGradient;
    ctx.fillRect(0, 0, 240, 240);
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

// Socket events
socket.on('canvas-data', (data) => {
    allStrokes = data;
    redrawCanvas();
});

socket.on('draw', (data) => {
    allStrokes.push(data);
    redrawCanvas();
});

socket.on('erase', (data) => {
    allStrokes.push(data);
    redrawCanvas();
});

socket.on('clear', () => {
    allStrokes = [];
    redrawCanvas();
    history = [];
    historyStep = -1;
    saveState();
});

// Event listeners
canvas.addEventListener('mousedown', startDrawing);
canvas.addEventListener('mousemove', handleMove);
canvas.addEventListener('mouseup', stopDrawing);
canvas.addEventListener('touchstart', startDrawing, { passive: false });
canvas.addEventListener('touchmove', handleMove, { passive: false });
canvas.addEventListener('touchend', stopDrawing, { passive: false });

// Tool buttons
document.getElementById('penTool').addEventListener('click', () => {
    currentTool = 'inkPen';
    document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active', 'bg-blue-500'));
    document.getElementById('penTool').classList.add('active', 'bg-blue-500');
    document.getElementById('eraserPalette').classList.add('hidden');
});

document.getElementById('eraserTool').addEventListener('click', () => {
    currentTool = 'eraser';
    document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active', 'bg-blue-500'));
    document.getElementById('eraserTool').classList.add('active', 'bg-blue-500');
    document.getElementById('eraserPalette').classList.toggle('hidden');
});

// Long press for pen tools
let longPressTimer;
document.getElementById('penTool').addEventListener('touchstart', (e) => {
    longPressTimer = setTimeout(() => {
        document.getElementById('penToolsPalette').classList.toggle('hidden');
    }, 500);
});

document.getElementById('penTool').addEventListener('touchend', () => {
    clearTimeout(longPressTimer);
});

// Pen tool selection
document.querySelectorAll('.pen-tool-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        currentTool = btn.dataset.tool;
        document.querySelectorAll('.pen-tool-btn').forEach(b => b.classList.remove('active', 'bg-blue-500'));
        btn.classList.add('active', 'bg-blue-500');
        document.getElementById('penToolsPalette').classList.add('hidden');
    });
});

// Eraser mode selection
document.querySelectorAll('.eraser-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        eraserMode = btn.dataset.mode;
        document.querySelectorAll('.eraser-btn').forEach(b => b.classList.remove('active', 'bg-red-500'));
        btn.classList.add('active', 'bg-red-500');
    });
});

// Size controls
document.getElementById('decreaseSize').addEventListener('click', () => {
    if (brushSize > 1) {
        brushSize--;
        document.getElementById('sizeInput').value = brushSize;
    }
});

document.getElementById('increaseSize').addEventListener('click', () => {
    if (brushSize < 50) {
        brushSize++;
        document.getElementById('sizeInput').value = brushSize;
    }
});

document.getElementById('sizeInput').addEventListener('change', (e) => {
    const value = Math.max(1, Math.min(50, parseInt(e.target.value) || 3));
    brushSize = value;
    e.target.value = value;
});

// Zoom controls
document.getElementById('zoomIn').addEventListener('click', () => changeZoom(1.2));
document.getElementById('zoomOut').addEventListener('click', () => changeZoom(0.8));

document.getElementById('zoomInput').addEventListener('change', (e) => {
    const value = Math.max(10, Math.min(500, parseInt(e.target.value) || 100));
    zoom = value / 100;
    e.target.value = value;
    redrawCanvas();
});

// Color picker
document.getElementById('colorPicker').addEventListener('click', () => {
    document.getElementById('colorPalette').classList.toggle('hidden');
});

document.querySelectorAll('.color-option').forEach(option => {
    option.addEventListener('click', () => {
        currentColor = option.dataset.color;
        document.getElementById('colorPicker').style.backgroundColor = currentColor;
        document.getElementById('colorPalette').classList.add('hidden');
    });
});

// Custom color picker
document.getElementById('customColorBtn').addEventListener('click', () => {
    document.getElementById('colorPalette').classList.add('hidden');
    document.getElementById('customColorPicker').classList.remove('hidden');
});

let currentHue = 0;
document.getElementById('hueSlider').addEventListener('click', (e) => {
    const rect = e.target.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const hue = (x / 240) * 360;
    currentHue = hue;
    
    const hueColor = hslToHex(hue, 100, 50);
    updateColorSpectrum(hueColor);
    
    const indicator = document.getElementById('hueIndicator');
    indicator.style.left = x + 'px';
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
    
    const color = `rgb(${r}, ${g}, ${b})`;
    document.getElementById('customColorBtn').firstElementChild.style.backgroundColor = color;
    
    const indicator = document.getElementById('spectrumIndicator');
    indicator.style.left = x + 'px';
    indicator.style.top = y + 'px';
});

document.getElementById('confirmColorPicker').addEventListener('click', () => {
    const r = parseInt(document.getElementById('rgbR').value) || 0;
    const g = parseInt(document.getElementById('rgbG').value) || 0;
    const b = parseInt(document.getElementById('rgbB').value) || 0;
    
    currentColor = `rgb(${Math.min(255, Math.max(0, r))}, ${Math.min(255, Math.max(0, g))}, ${Math.min(255, Math.max(0, b))})`;
    document.getElementById('colorPicker').style.backgroundColor = currentColor;
    document.getElementById('customColorPicker').classList.add('hidden');
});

document.getElementById('cancelColorPicker').addEventListener('click', () => {
    document.getElementById('customColorPicker').classList.add('hidden');
});

// RGB input validation
['rgbR', 'rgbG', 'rgbB'].forEach(id => {
    document.getElementById(id).addEventListener('input', (e) => {
        let value = parseInt(e.target.value);
        if (value > 255) e.target.value = 255;
        if (value < 0) e.target.value = 0;
        
        const r = parseInt(document.getElementById('rgbR').value) || 0;
        const g = parseInt(document.getElementById('rgbG').value) || 0;
        const b = parseInt(document.getElementById('rgbB').value) || 0;
        const color = `rgb(${r}, ${g}, ${b})`;
        
        document.getElementById('customColorBtn').firstElementChild.style.backgroundColor = color;
    });
});

// Clear button with confirmation
document.getElementById('clearBtn').addEventListener('click', () => {
    document.getElementById('confirmModal').classList.remove('hidden');
    document.getElementById('confirmModal').classList.add('flex');
});

document.getElementById('cancelClear').addEventListener('click', () => {
    document.getElementById('confirmModal').classList.add('hidden');
    document.getElementById('confirmModal').classList.remove('flex');
});

document.getElementById('confirmClear').addEventListener('click', () => {
    allStrokes = [];
    redrawCanvas();
    history = [];
    historyStep = -1;
    saveState();
    socket.emit('clear');
    document.getElementById('confirmModal').classList.add('hidden');
    document.getElementById('confirmModal').classList.remove('flex');
});

// Other controls
document.getElementById('undo').addEventListener('click', undo);

document.getElementById('download').addEventListener('click', () => {
    const link = document.createElement('a');
    link.download = 'canvas.png';
    link.href = canvas.toDataURL();
    link.click();
});

// Mouse wheel zoom
canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    changeZoom(factor);
});

// Hide palettes on outside click
document.addEventListener('click', (e) => {
    if (!e.target.closest('#colorPalette') && !e.target.closest('#colorPicker')) {
        document.getElementById('colorPalette').classList.add('hidden');
    }
    if (!e.target.closest('#customColorPicker') && !e.target.closest('#customColorBtn')) {
        document.getElementById('customColorPicker').classList.add('hidden');
    }
    if (!e.target.closest('#penToolsPalette') && !e.target.closest('#penTool')) {
        document.getElementById('penToolsPalette').classList.add('hidden');
    }
    if (!e.target.closest('#eraserPalette') && !e.target.closest('#eraserTool')) {
        document.getElementById('eraserPalette').classList.add('hidden');
    }
});

// Prevent context menu
canvas.addEventListener('contextmenu', e => e.preventDefault());

// Resize handler
window.addEventListener('resize', initCanvas);

// Initialize
initCanvas();
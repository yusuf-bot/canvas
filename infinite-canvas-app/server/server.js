const express = require('express');
const http = require('http');
const socketIo = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = socketIo(server);

app.use(express.static('public'));

// Store all drawing data server-side
let canvasData = [];

io.on('connection', (socket) => {
  console.log('User connected');
  
  // Send existing canvas data to new user
  socket.emit('canvas-data', canvasData);
  
  socket.on('draw', (data) => {
    canvasData.push({ type: 'draw', ...data, timestamp: Date.now() });
    socket.broadcast.emit('draw', data);
  });
  
  socket.on('erase', (data) => {
    canvasData.push({ type: 'erase', ...data, timestamp: Date.now() });
    socket.broadcast.emit('erase', data);
  });
  
  socket.on('clear', () => {
    canvasData = [];
    socket.broadcast.emit('clear');
  });
  
  socket.on('disconnect', () => {
    console.log('User disconnected');
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
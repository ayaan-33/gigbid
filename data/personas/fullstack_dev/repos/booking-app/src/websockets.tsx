import { Server } from "socket.io";
import { createAdapter } from "@socket.io/redis-adapter";
import { createClient } from "redis";

const pub = createClient({ url: process.env.REDIS_URL });
const sub = pub.duplicate();
await Promise.all([pub.connect(), sub.connect()]);

const io = new Server(3001, { cors: { origin: "*" } });
io.adapter(createAdapter(pub, sub));
io.on("connection", (socket) => {
  socket.on("message", (room: string, text: string) => io.to(room).emit("message", { text, at: Date.now() }));
});

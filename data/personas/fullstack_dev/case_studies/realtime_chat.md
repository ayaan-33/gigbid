---
{"id": "fullstack_dev:case:realtime_chat", "type": "case_study", "project": "realtime_chat", "title": "Real-time chat module", "client_industry": "edtech", "date": "2021-03-21", "skills": ["WebSockets", "Node.js", "React", "Redis"], "synthetic": true}
---

# Real-time chat module

## Context

When I started with North Studio, a edtech business, users left the platform to message each other.

## What I did

- Socket.IO with Redis pub/sub for horizontal scale.
- Shipped it as a container image so their ops team could run it anywhere.
- Read receipts and typing indicators.
- Moderation queue for flagged messages.
- Kept the whole codebase strictly typed.

## Results

- 22k concurrent connections tested.
- Message latency p95 under 236 ms.
- Off-platform contact attempts down 60%.

Engagement: 5 weeks, finished 2021-03.

## Stack

WebSockets, Node.js, React, Redis

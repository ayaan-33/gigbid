---
{"id": "ai_ml_engineer:case:agent_workflow", "type": "case_study", "project": "agent_workflow", "title": "Multi-step AI agent for operations", "client_industry": "real estate", "date": "2023-05-15", "skills": ["Python", "LLM", "LangChain", "Chatbot"], "synthetic": true}
---

# Multi-step AI agent for operations

## Context

When I started with Beacon Partners, a real estate business, staff copied data between five internal tools for each request.

## What I did

- Designed a LangGraph agent with typed tools for each system.
- Human approval before any write.
- Kept everything in their existing relational database with proper migrations.
- Full audit trail of tool calls.
- Exposed it over a documented HTTP API their other systems could call.

## Results

- Handling time per request down 47%.
- 599 requests per week automated.
- Zero unapproved writes in production.

Engagement: 8 weeks, finished 2023-05.

## Stack

Python, LLM, LangChain, Chatbot

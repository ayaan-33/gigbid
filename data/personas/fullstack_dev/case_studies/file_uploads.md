---
{"id": "fullstack_dev:case:file_uploads", "type": "case_study", "project": "file_uploads", "title": "Large file upload service", "client_industry": "insurance claims", "date": "2026-07-18", "skills": ["AWS", "Node.js", "React"], "synthetic": true}
---

# Large file upload service

## Context

A insurance claims client, Kestrel Studio, came to me because uploads over 100 MB failed and blocked the app.

## What I did

- Presigned multipart uploads straight to S3.
- Background processing queue for thumbnails.
- Moved slow work to a background job queue.
- Resumable uploads in the browser.
- Shipped it as a container image so their ops team could run it anywhere.

## Results

- Upload failures down 89%.
- Files up to 6 GB.
- 39k uploads per month.

Engagement: 9 weeks, finished 2026-07.

## Stack

AWS, Node.js, React

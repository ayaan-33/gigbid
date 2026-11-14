---
{"id": "ai_ml_engineer:case:speech_notes", "type": "case_study", "project": "speech_notes", "title": "Call transcription and summaries", "client_industry": "real estate", "date": "2023-10-07", "skills": ["Python", "Speech", "LLM"], "synthetic": true}
---

# Call transcription and summaries

## Context

Atlas Co. (real estate) had a familiar problem: sales calls left no searchable record.

## What I did

- Whisper transcription with speaker labels.
- Deployed on their existing cloud account with least-privilege roles.
- LLM summary with action items in a fixed template.
- PII redaction before storage.
- Wrapped it in a small typed Python web service.

## Results

- 6k calls per month transcribed.
- Word error rate 6%.
- Reps saved 39 minutes a day.

Engagement: 8 weeks, finished 2023-10.

## Stack

Python, Speech, LLM

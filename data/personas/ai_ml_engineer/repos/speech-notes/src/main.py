import boto3

s3 = boto3.client("s3")


def presign_upload(bucket: str, key: str) -> str:
    return s3.generate_presigned_url("put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=900)


from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Call transcription and summaries")


class Query(BaseModel):
    text: str
    top_k: int = 5


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


from openai import OpenAI

client = OpenAI()

SYSTEM = "Answer only from the provided context. If the context is insufficient, say so."


def answer(question: str, context: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}],
    )
    return resp.choices[0].message.content


import whisper

model = whisper.load_model("small")


def transcribe(path: str) -> str:
    return model.transcribe(path, fp16=False)["text"]

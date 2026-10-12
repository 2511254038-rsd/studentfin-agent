from fastapi import FastAPI

app = FastAPI(title="StudentFin Agent")

@app.get("/health")
def health():
    return {"status": "ok"}

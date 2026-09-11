from fastapi import FastAPI

app = FastAPI(title="DocuEngine API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
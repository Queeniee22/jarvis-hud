import uvicorn

if __name__ == "__main__":
    uvicorn.run("jarvis.app:app", host="127.0.0.1", port=8770, reload=False)

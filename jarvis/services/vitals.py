import asyncio
import psutil

def sample() -> dict:
    return {
        "type": "vitals",
        "cpu": round(psutil.cpu_percent()),
        "ram": round(psutil.virtual_memory().percent),
        "disk": round(psutil.disk_usage("C:\\").percent),
    }

async def run(hub, interval: float = 2.0):
    while True:
        await hub.broadcast(sample())
        await asyncio.sleep(interval)

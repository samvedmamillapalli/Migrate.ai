import asyncio, sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import uvicorn
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8002
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=True, reload_dirs=["app"])

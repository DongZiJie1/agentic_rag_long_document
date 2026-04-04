"""Entry point for running the FastAPI application"""
import os
import uvicorn


def main():
    """Run the FastAPI application"""
    port = int(os.getenv("APP_PORT", "8001"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )


if __name__ == "__main__":
    main()

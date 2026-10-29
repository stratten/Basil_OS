from fastapi import FastAPI, HTTPException
from pathlib import Path
import uvicorn

from config.config_manager import AppConfig
from utils.logger import setup_logger
from api.routes.model_routes import model_testing_router

def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(title="Basil API")
    
    try:
        config_path = Path(__file__).parent / "config" / "default_config.yaml"
        config = AppConfig.load_from_yaml(config_path)
        config.ensure_paths()
        app.state.config = config
        
        # Set up logger after loading config
        logger = setup_logger(__name__, debug=config.debug)
        logger.info(f"Started {config.name} in {'debug' if config.debug else 'production'} mode")
        
        # Include routers
        app.include_router(model_testing_router)
        
    except Exception as e:
        # Use default logger for startup errors
        startup_logger = setup_logger(__name__, debug=True)
        startup_logger.error(f"Failed to initialize application: {str(e)}")
        raise

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}

    return app

app = create_app()

if __name__ == "__main__":
    config = app.state.config
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        # Match the primary launcher: tolerate brief event-loop stalls so a live
        # WebSocket is not closed with a 1011 keepalive ping timeout mid-stream.
        ws_ping_interval=30,
        ws_ping_timeout=60,
    ) 
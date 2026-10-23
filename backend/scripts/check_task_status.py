#!/usr/bin/env python3
import sys
import os
import logging
import time
import json
from pathlib import Path
import sqlite3

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("task_status_checker")

# Set the model type and variant
MODEL_TYPE = "llama32-3b-instruct"
VARIANT = "base"

def check_task_status():
    """Check the status of the task queue download directly from the Huey database."""
    logger.info(f"Checking task status for {MODEL_TYPE}-{VARIANT}")
    
    # Path to the Huey task database
    db_path = Path.home() / ".basil" / "tasks" / "tasks.db"
    
    if not db_path.exists():
        logger.error(f"Task database not found at {db_path}")
        return False
    
    logger.info(f"Found task database at {db_path}")
    
    try:
        # Connect to the SQLite database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Query for tasks related to model downloads
        cursor.execute("SELECT id, queue, data, status, created, retries, retry_delay FROM huey_queue")
        tasks = cursor.fetchall()
        
        if not tasks:
            logger.info("No tasks found in the queue")
            return False
        
        logger.info(f"Found {len(tasks)} tasks in the queue")
        
        # Look for our specific model download task
        for task in tasks:
            task_id, queue, data, status, created, retries, retry_delay = task
            
            # Try to parse the task data
            try:
                # The data might be in different formats depending on Huey version
                if isinstance(data, bytes):
                    # Skip binary data for now
                    continue
                
                logger.info(f"Task ID: {task_id}")
                logger.info(f"Status: {status}")
                logger.info(f"Created: {created}")
                logger.info(f"Data: {data[:100]}..." if len(data) > 100 else f"Data: {data}")
                logger.info("-" * 50)
                
                # Check if this task is for our model
                if MODEL_TYPE in str(data):
                    logger.info(f"Found task for {MODEL_TYPE}")
                    
                    # Check task status
                    if status == "done":
                        logger.info("Task completed successfully")
                    elif status == "executing":
                        logger.info("Task is currently executing")
                    else:
                        logger.info(f"Task status: {status}")
            except Exception as e:
                logger.error(f"Error parsing task data: {e}")
        
        # Query for task results
        cursor.execute("SELECT id, queue, data, created FROM huey_result")
        results = cursor.fetchall()
        
        if results:
            logger.info(f"Found {len(results)} task results")
            
            for result in results:
                result_id, queue, data, created = result
                logger.info(f"Result ID: {result_id}")
                logger.info(f"Created: {created}")
                logger.info("-" * 50)
        
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error checking task status: {e}")
        return False

def check_huey_process():
    """Check if the Huey consumer process is running."""
    logger.info("Checking if Huey consumer is running")
    
    try:
        import subprocess
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        output = result.stdout
        
        huey_processes = [line for line in output.split('\n') if 'huey_consumer' in line and 'grep' not in line]
        
        if huey_processes:
            logger.info(f"Found {len(huey_processes)} Huey consumer processes:")
            for process in huey_processes:
                logger.info(process.strip())
            return True
        else:
            logger.warning("No Huey consumer processes found")
            return False
    except Exception as e:
        logger.error(f"Error checking Huey process: {e}")
        return False

def check_model_file():
    """Check if the model file exists or is being downloaded."""
    logger.info(f"Checking for model file for {MODEL_TYPE}-{VARIANT}")
    
    # Path to the model file
    model_path = Path.home() / ".basil" / "models" / f"{MODEL_TYPE}-{VARIANT}.gguf"
    
    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        logger.info(f"Model file exists at {model_path} ({size_mb:.2f} MB)")
        return True
    else:
        logger.info(f"Model file does not exist at {model_path}")
        
        # Check for temporary download directories
        temp_dirs = list(Path("/var/folders").glob("**/tmp*"))
        for temp_dir in temp_dirs:
            if temp_dir.is_dir():
                for file in temp_dir.glob("**/*"):
                    if file.is_file() and "Llama-3.2" in file.name:
                        size_mb = file.stat().st_size / (1024 * 1024)
                        logger.info(f"Found temporary download file: {file} ({size_mb:.2f} MB)")
                        return True
        
        logger.info("No temporary download files found")
        return False

if __name__ == "__main__":
    try:
        logger.info("Starting task status check")
        
        # Check if Huey is running
        huey_running = check_huey_process()
        
        # Check task status
        task_status = check_task_status()
        
        # Check model file
        model_file = check_model_file()
        
        logger.info("Task status check complete")
        logger.info(f"Huey running: {huey_running}")
        logger.info(f"Task status checked: {task_status}")
        logger.info(f"Model file checked: {model_file}")
        
        # Keep checking every 30 seconds if requested
        if len(sys.argv) > 1 and sys.argv[1] == "--monitor":
            logger.info("Monitoring mode enabled, will check every 30 seconds")
            while True:
                time.sleep(30)
                logger.info("\n" + "=" * 50)
                logger.info("Periodic check")
                check_huey_process()
                check_task_status()
                check_model_file()
                logger.info("=" * 50 + "\n")
        
    except KeyboardInterrupt:
        logger.info("Check interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        sys.exit(1) 
#!/usr/bin/env python3
import asyncio
import json
import sys
import time
from pathlib import Path
import aiohttp
import websockets
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table
import pkg_resources

# Configure rich console for nice output
console = Console()

# API endpoints
BASE_URL = "http://localhost:8000/test"
WS_BASE_URL = "ws://localhost:8000/test"

# Test configuration
DEFAULT_MODEL_TYPE = "whisper"
DEFAULT_MODEL_VARIANT = "tiny"
CONNECTION_TIMEOUT = 10  # seconds
DOWNLOAD_TIMEOUT = 1800  # 30 minutes for download


async def check_server_available():
    """Check if the API server is running."""
    start_time = time.time()
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BASE_URL}/models/available", 
                    timeout=CONNECTION_TIMEOUT
                ) as response:
                    if response.status != 200:
                        raise ConnectionError(f"Server returned status {response.status}")
                    console.print("[green]✓ API server is available[/green]")
                    return True
        except asyncio.TimeoutError:
            retry_count += 1
            console.print(f"[yellow]Connection timed out, retrying... ({retry_count}/{max_retries})[/yellow]")
            await asyncio.sleep(1)
        except Exception as e:
            console.print(f"[red]Error: API server is not available - {str(e)}[/red]")
            console.print("[yellow]Make sure the API server is running on localhost:8000[/yellow]")
            return False
    
    console.print(f"[red]Failed to connect after {max_retries} retries[/red]")
    return False


async def get_available_models():
    """Get list of available models."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/models/available", 
                timeout=CONNECTION_TIMEOUT
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Failed to get available models: {response.status}")
                return await response.json()
    except Exception as e:
        console.print(f"[red]Error fetching available models: {str(e)}[/red]")
        raise


async def get_installed_models():
    """Get list of installed models."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/models/installed", 
                timeout=CONNECTION_TIMEOUT
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Failed to get installed models: {response.status}")
                return await response.json()
    except Exception as e:
        console.print(f"[red]Error fetching installed models: {str(e)}[/red]")
        raise


async def monitor_download_progress(model_type: str, variant: str, progress: Progress):
    """Monitor download progress using WebSocket connection."""
    task = progress.add_task(
        f"[cyan]Downloading {model_type}-{variant}...",
        total=100
    )
    
    last_progress = 0
    stall_start_time = None
    stall_timeout = 300  # 5 minutes of no progress is considered stalled
    
    try:
        ws_url = f"{WS_BASE_URL}/models/download/{model_type}/{variant}/progress"
        console.print(f"[dim]Connecting to WebSocket: {ws_url}[/dim]")
        
        # Set a reasonable timeout for the WebSocket connection
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=60) as ws:
            console.print("[green]WebSocket connection established[/green]")
            
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(msg)
                    
                    if data.get("status") == "error":
                        error_msg = data.get("error", "Unknown error")
                        progress.update(task, description=f"[red]Error: {error_msg}")
                        console.print(f"[red]Download error: {error_msg}[/red]")
                        return False
                    
                    if "progress" in data:
                        current_progress = int(data["progress"] * 100)
                        progress.update(task, completed=current_progress)
                        
                        # Check for stalled downloads
                        if current_progress > last_progress:
                            last_progress = current_progress
                            stall_start_time = None
                        elif stall_start_time is None:
                            stall_start_time = time.time()
                        elif time.time() - stall_start_time > stall_timeout:
                            progress.update(task, description=f"[yellow]Download appears stalled at {current_progress}%[/yellow]")
                            console.print(f"[yellow]Warning: Download stalled at {current_progress}% for {stall_timeout} seconds[/yellow]")
                            # Don't return False here, just warn - the download might still complete
                        
                    if data.get("status") == "completed":
                        progress.update(task, description="[green]Download completed!", completed=100)
                        return True
                        
                except asyncio.TimeoutError:
                    # Check if we've been stuck for too long
                    if stall_start_time and time.time() - stall_start_time > stall_timeout:
                        progress.update(task, description=f"[red]Timeout waiting for progress updates[/red]")
                        console.print("[red]Error: Timeout waiting for progress updates[/red]")
                        return False
                    console.print("[yellow]WebSocket message timeout, still waiting...[/yellow]")
                    continue
                except websockets.exceptions.ConnectionClosed:
                    progress.update(task, description="[yellow]WebSocket connection closed[/yellow]")
                    console.print("[yellow]WebSocket connection closed unexpectedly[/yellow]")
                    break
                except json.JSONDecodeError:
                    progress.update(task, description="[red]Error: Invalid response from server[/red]")
                    console.print("[red]Error: Invalid JSON response from server[/red]")
                    return False
                except Exception as e:
                    progress.update(task, description=f"[red]Error: {str(e)}[/red]")
                    console.print(f"[red]Error monitoring download: {str(e)}[/red]")
                    return False
                
    except Exception as e:
        progress.update(task, description=f"[red]Connection error: {str(e)}[/red]")
        console.print(f"[red]WebSocket connection error: {str(e)}[/red]")
        return False


async def download_model(model_type: str, variant: str):
    """Initiate model download."""
    try:
        async with aiohttp.ClientSession() as session:
            console.print(f"[dim]Sending download request for {model_type}-{variant}...[/dim]")
            async with session.post(
                f"{BASE_URL}/models/download",
                json={"model_type": model_type, "variant": variant},
                timeout=CONNECTION_TIMEOUT
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Failed to initiate download: {response.status}")
                result = await response.json()
                console.print("[green]Download initiated successfully[/green]")
                return result
    except Exception as e:
        console.print(f"[red]Error initiating download: {str(e)}[/red]")
        raise


def display_model_info(models_dict: dict, title: str):
    """Display model information in a formatted table."""
    table = Table(title=title)
    table.add_column("Model Type", style="cyan")
    table.add_column("Variant", style="magenta")
    table.add_column("Name", style="green")
    table.add_column("Size", style="yellow")
    table.add_column("RAM Required", style="red")
    table.add_column("Capabilities", style="blue")
    
    for model_type, info in models_dict.items():
        for variant, variant_info in info["variants"].items():
            capabilities = ", ".join(
                [str(cap) for cap in variant_info["capabilities"]]
            ) if isinstance(variant_info["capabilities"], list) else "N/A"
            table.add_row(
                model_type,
                variant,
                variant_info["name"],
                variant_info["size"],
                variant_info["recommended_ram"],
                capabilities
            )
    
    console.print(table)


def check_huggingface_hub_version():
    """Check the installed version of huggingface_hub."""
    try:
        version = pkg_resources.get_distribution("huggingface_hub").version
        console.print(f"[bold blue]huggingface_hub version: [green]{version}[/green][/bold blue]")
        
        if version >= "0.28.0":
            console.print("[green]✓ Your huggingface_hub version supports the timeout parameter in snapshot_download()[/green]")
        else:
            console.print("[yellow]⚠ Your huggingface_hub version does not support the timeout parameter in snapshot_download()[/yellow]")
            console.print("[yellow]  This may cause issues when downloading large models[/yellow]")
            
        return version
    except Exception as e:
        console.print(f"[red]Error checking huggingface_hub version: {str(e)}[/red]")
        return "unknown"


async def main():
    """Main test routine."""
    console.print("[bold blue]======================================[/bold blue]")
    console.print("[bold blue]     Model Download Test Script      [/bold blue]")
    console.print("[bold blue]======================================[/bold blue]")
    
    # Check huggingface_hub version first
    hf_version = check_huggingface_hub_version()
    
    console.print("\nChecking server availability...")
    
    if not await check_server_available():
        sys.exit(1)
    
    try:
        # Get available models
        console.print("\nFetching available models...")
        available_models = await get_available_models()
        
        if not available_models:
            console.print("[red]No models available for download[/red]")
            sys.exit(1)
        
        # Display available models
        display_model_info(available_models, "Available Models")
        
        # Get installed models
        installed_models = await get_installed_models()
        if installed_models:
            console.print("\n[yellow]Already Installed Models:[/yellow]")
            for model_id, info in installed_models.items():
                console.print(f"  • {model_id}")
        
        # Default models
        model_type = DEFAULT_MODEL_TYPE
        variant = DEFAULT_MODEL_VARIANT
        
        # Allow instruction line override
        if len(sys.argv) > 2:
            model_type = sys.argv[1]
            variant = sys.argv[2]
            
            # Validate model choice
            if model_type not in available_models:
                console.print(f"[red]Error: Unknown model type '{model_type}'[/red]")
                sys.exit(1)
            if variant not in available_models[model_type]["variants"]:
                console.print(f"[red]Error: Unknown variant '{variant}' for model {model_type}[/red]")
                sys.exit(1)
        
        console.print(f"\n[bold]Testing download of [cyan]{model_type}-{variant}[/cyan][/bold]")
        console.print(f"[dim]Using huggingface_hub version {hf_version}[/dim]")
        
        # Check if model is already installed
        if (installed_models and model_type in installed_models and 
            variant in installed_models[model_type]["variants"]):
            console.print(f"[yellow]Note: Model {model_type}-{variant} is already installed.[/yellow]")
            prompt = input("Do you want to proceed with the download test anyway? (y/n): ")
            if prompt.lower() != 'y':
                console.print("[yellow]Test aborted by user[/yellow]")
                sys.exit(0)
        
        # Start download
        await download_model(model_type, variant)
        
        # Monitor download with progress
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
            transient=False
        ) as progress:
            download_success = await monitor_download_progress(model_type, variant, progress)
        
        if download_success:
            console.print("\n[green bold]✓ Download test completed successfully![/green bold]")
            
            # Verify installation
            updated_installed_models = await get_installed_models()
            if (model_type in updated_installed_models and 
                variant in updated_installed_models[model_type]["variants"]):
                console.print("[green]✓ Model verified in installed models list[/green]")
                
                # Get model path
                model_path = updated_installed_models[model_type]["variants"][variant]["path"]
                console.print(f"[green]✓ Model installed at: [cyan]{model_path}[/cyan][/green]")
            else:
                console.print("[red]⚠ Warning: Model not found in installed models list[/red]")
        else:
            console.print("\n[red bold]✗ Download test failed![/red bold]")
            sys.exit(1)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {str(e)}[/red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)
    
    console.print("\n[bold blue]======================================[/bold blue]")
    console.print("[bold green]             Test Complete            [/bold green]")
    console.print("[bold blue]======================================[/bold blue]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {str(e)}[/red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1) 
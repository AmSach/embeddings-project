import os
import sys
import subprocess
import time
import webbrowser

VENV_PYTHON = r"C:\Users\amans\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"

def check_and_redirect():
    """If running in the global python environment, redirect to the virtual environment."""
    current_python = sys.executable
    print(f"Current Python interpreter: {current_python}")
    
    # Check if the active python is NOT the virtual environment
    if current_python.lower() != VENV_PYTHON.lower():
        if os.path.exists(VENV_PYTHON):
            print(f"Redirecting execution to agent virtual environment at:\n  {VENV_PYTHON}\n")
            # Re-execute the script using the virtual environment python
            # Forwarding all command line arguments
            sys.exit(subprocess.run([VENV_PYTHON] + sys.argv).returncode)
        else:
            print("[Warning] Agent virtual environment not found at default location.")
            print("Proceeding with global system Python interpreter...")

def launch_server():
    """Launches the uvicorn web server and opens the browser."""
    print("==================================================================")
    print("           Notion-Like Model UN Research Assistant                ")
    print("==================================================================")
    print("Starting FastAPI Uvicorn Server...")
    
    # Dynamic browser launch after a brief delay to let the server start up
    def open_browser():
        time.sleep(1.5)
        url = "http://127.0.0.1:8000"
        print(f"Launching default web browser to: {url}")
        webbrowser.open(url)

    # Spawn browser thread
    import threading
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()

    # Import uvicorn locally to run
    try:
        import uvicorn
        # Run server
        # Host on localhost only for security
        uvicorn.run("backend.main:app", host="127.0.0.1", port=8001, reload=True)
    except ImportError:
        print("[Error] Uvicorn is not installed in the selected environment.")
        print("Please ensure uvicorn is available or run: pip install uvicorn")
        sys.exit(1)

if __name__ == "__main__":
    # Ensure working directory is workspace root
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Redirect to venv if needed
    check_and_redirect()
    
    # Launch
    launch_server()

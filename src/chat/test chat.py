import glob
import os
from pathlib import Path

directory_path = PG_BASE / "ChatLogs"

def find_latest_log_file(directory_path, extension='*.log'):
    """
    Finds the latest log file in the specified directory.

    Args:
        directory_path (str): The path to the directory containing log files.
        extension (str): The file extension to search for (default: '*.log').

    Returns:
        Path or None: The path to the latest log file, or None if no files are found.
    """
    # Create a Path object for the directory
    p = Path(directory_path)

    # Use glob to find all files matching the extension
    # glob.glob returns a list of strings
    list_of_files = glob.glob(str(p / extension))

    if not list_of_files:
        return None

    # Sort files by modification time (os.path.getmtime)
    # key=os.path.getmtime sorts by timestamp
    # reverse=True ensures the newest file is first
    latest_file = max(list_of_files, key=os.path.getmtime)

    # Convert the result back to a Path object for consistency
    return Path(latest_file)

# Example usage:
log_directory = "./logs" # Replace with your log directory path
latest_file_path = find_latest_log_file(log_directory)

if latest_file_path:
    print(f"The latest log file is: {latest_file_path}")
    # You can now open and read this file
    # with open(latest_file_path, 'r') as f:
    #     content = f.read()
else:
    print(f"No log files found in {log_directory}")


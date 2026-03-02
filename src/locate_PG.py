from pathlib import Path

def find_PG():
    def find_directory_from_home(directory_name):
        home_dir = Path.home()
        print(f"Starting search from: {home_dir}")
        for path in home_dir.rglob(directory_name):
            if path.is_dir():
                return path
        return None

    target_dir_name = "Project Gorgon"
    PG_BASE = find_directory_from_home(target_dir_name)

    if PG_BASE:
        print(f"Found directory: {PG_BASE}")
    else:
        print(f"Directory '{target_dir_name}' not found in the home directory or its subdirectories.")

find_PG()


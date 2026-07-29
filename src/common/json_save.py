import json
import os
from pathlib import Path


def orbital(orbital):
    name_new = orbital["name"].replace(" ", "_")

    repo_root = Path(__file__).resolve().parents[2]
    folder_path = repo_root / "data" / "outputs" / "orbital"
    folder_path.mkdir(parents=True, exist_ok=True)

    file_name = name_new + "_data.json"
    file_path = folder_path / file_name

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(orbital, file, indent=4)

def housekeeping(housekeeping):

    cwd = os.getcwd()
    name_new = housekeeping["name"].replace(" ", "_")

    folder_path = cwd + "/housekeeping_data"
    file_name = name_new + "_data.json"

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    file_path = os.path.join(folder_path, file_name)

    with open(file_path, "w") as file:
        json.dump(housekeeping, file, indent = 4)
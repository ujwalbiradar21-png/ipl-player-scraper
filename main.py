
import csv
from pathlib import Path

# Create an output folder
output_folder = Path("output")
output_folder.mkdir(exist_ok=True)

# Create a CSV file
file_path = output_folder / "test.csv"

with open(file_path, "w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)

    writer.writerow(["Player Name", "Runs", "Wickets"])
    writer.writerow(["Example Batter", 250, 3])
    writer.writerow(["Example Bowler", 40, 12])

print("CSV file created successfully!")
print("File location:", file_path.resolve())

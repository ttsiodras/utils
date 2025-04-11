#!/usr/bin/env python3

import sys
import matplotlib.pyplot as plt

# Specify the filename.
filename = 'some.data.series.with.one.number.perline'

# Read the data from the file, assuming one number per line.
data = []
for line in sys.stdin:
    stripped = line.strip()
    if stripped:
        try:
            data.append(float(stripped))
        except ValueError:
            print(f"Skipping invalid number: {stripped}")

# Create a figure with a size that roughly corresponds to your original ASCII graph dimensions.
# Here, we use 12 inches by 5 inches; feel free to adjust as desired.
plt.figure(figsize=(12, 5))

# Plot the data with a line and markers.
plt.plot(data, marker='o', linestyle='-', markersize=3)

# Set plot labels and title.
plt.xlabel("Index")
plt.ylabel("Value")
plt.title(sys.argv[1])

# Optionally add a grid.
plt.grid(True)

# Adjust layout and display the plot.
plt.tight_layout()
plt.show()

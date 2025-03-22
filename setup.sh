#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

# Check if the virtual environment directory exists; if not, create it.
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate the virtual environment.
source venv/bin/activate

# Upgrade pip to the latest version.
pip install --upgrade pip

# Install the required packages.
pip install -r requirements.txt

echo "Setup complete!"
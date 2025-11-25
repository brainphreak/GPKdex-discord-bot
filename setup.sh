#!/bin/bash

# GPK Dex Bot Setup Script
# Run this on your server after uploading files

echo "=== GPK Dex Bot Setup ==="

# Install dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# Set permissions
echo "Setting permissions..."
chmod +x bot.py

# Copy systemd service
echo "Installing systemd service..."
sudo cp gpkdex.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable and start the service
echo "Starting GPK Dex bot..."
sudo systemctl enable gpkdex
sudo systemctl start gpkdex

# Check status
echo ""
echo "=== Bot Status ==="
sudo systemctl status gpkdex --no-pager

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Useful commands:"
echo "  View logs:     sudo journalctl -u gpkdex -f"
echo "  Restart bot:   sudo systemctl restart gpkdex"
echo "  Stop bot:      sudo systemctl stop gpkdex"
echo "  Bot status:    sudo systemctl status gpkdex"

#!/bin/bash
# Start IBKR Client Portal Gateway on port 5001
# After starting, open https://localhost:5001 in browser to authenticate

GATEWAY_DIR="${IBKR_GATEWAY_DIR:-$HOME/Downloads/clientportal.gw}"

if [ ! -d "$GATEWAY_DIR" ]; then
    echo "Error: IBKR Gateway not found at $GATEWAY_DIR"
    echo "Set IBKR_GATEWAY_DIR env var or download to ~/Downloads/clientportal.gw"
    exit 1
fi

cd "$GATEWAY_DIR"
echo "Starting IBKR Client Portal Gateway on https://localhost:5001 ..."
echo "Open https://localhost:5001 in your browser to log in."
echo "Press Ctrl+C to stop."
echo ""
bin/run.sh root/conf.yaml

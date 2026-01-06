#!/usr/bin/env python3
"""
Simple HTTP server for the Bully Election Visualizer.

Usage:
    python serve.py --state path/to/state_log.jsonl --msg path/to/message_log.jsonl --debug path/to/debug_log.jsonl [--port PORT]

If log files are provided, they will be copied to the visualizer directory
and automatically loaded when the page opens.
"""

import http.server
import socketserver
import os
import shutil
import argparse
import webbrowser
import json
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(
        description='Serve the Bully Election Visualizer with optional log files'
    )
    parser.add_argument(
        '--state', '-s',
        dest='state_log',
        help='Path to state_log.jsonl file'
    )
    parser.add_argument(
        '--msg', '-m',
        dest='message_log',
        help='Path to message_log.jsonl file'
    )
    parser.add_argument(
        '--debug', '-d',
        dest='debug_log',
        help='Path to debug_log.jsonl file'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=8080,
        help='Port to serve on (default: 8080)'
    )
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not open browser automatically'
    )
    return parser.parse_args()

def copy_log_files(state_log, message_log, debug_log, dest_dir):
    """Copy log files to the visualizer directory."""
    copied = []

    if state_log:
        state_path = Path(state_log)
        if state_path.exists():
            dest = dest_dir / 'state_log.jsonl'
            shutil.copy(state_path, dest)
            copied.append(('state', state_path))
            print(f"Copied state log: {state_path} -> {dest}")
        else:
            print(f"Warning: State log not found: {state_log}")

    if message_log:
        msg_path = Path(message_log)
        if msg_path.exists():
            dest = dest_dir / 'message_log.jsonl'
            shutil.copy(msg_path, dest)
            copied.append(('message', msg_path))
            print(f"Copied message log: {msg_path} -> {dest}")
        else:
            print(f"Warning: Message log not found: {message_log}")

    if debug_log:
        debug_path = Path(debug_log)
        if debug_path.exists():
            dest = dest_dir / 'debug_log.jsonl'
            shutil.copy(debug_path, dest)
            copied.append(('debug', debug_path))
            print(f"Copied debug log: {debug_path} -> {dest}")
        else:
            print(f"Warning: Debug log not found: {debug_log}")

    return copied

def create_autoload_config(dest_dir, has_state, has_message, has_debug):
    """Create a config file that tells the frontend to auto-load files."""
    config = {
        'autoload': has_state and has_message,
        'stateFile': 'state_log.jsonl' if has_state else None,
        'messageFile': 'message_log.jsonl' if has_message else None,
        'debugFile': 'debug_log.jsonl' if has_debug else None
    }
    config_path = dest_dir / 'autoload.json'
    with open(config_path, 'w') as f:
        json.dump(config, f)
    return config['autoload']

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with CORS headers."""

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, format, *args):
        # Quieter logging - only show errors
        if args[1].startswith('4') or args[1].startswith('5'):
            super().log_message(format, *args)

def main():
    args = parse_args()

    # Change to the directory containing this script
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    # Copy log files if provided
    has_state = False
    has_message = False
    has_debug = False

    if args.state_log or args.message_log or args.debug_log:
        copied = copy_log_files(args.state_log, args.message_log, args.debug_log, script_dir)
        has_state = any(t == 'state' for t, _ in copied)
        has_message = any(t == 'message' for t, _ in copied)
        has_debug = any(t == 'debug' for t, _ in copied)
    else:
        # Check if files already exist in directory
        has_state = (script_dir / 'state_log.jsonl').exists()
        has_message = (script_dir / 'message_log.jsonl').exists()
        has_debug = (script_dir / 'debug_log.jsonl').exists()

    # Create autoload config
    autoload = create_autoload_config(script_dir, has_state, has_message, has_debug)

    print()
    print(f"Starting Bully Election Visualizer")
    print(f"=" * 40)
    print(f"Server: http://localhost:{args.port}")
    print(f"State log: {'Ready' if has_state else 'Not found'}")
    print(f"Message log: {'Ready' if has_message else 'Not found'}")
    print(f"Debug log: {'Ready' if has_debug else 'Not found'}")
    print(f"Auto-load: {'Yes' if autoload else 'No (upload files manually)'}")
    print()
    print("Press Ctrl+C to stop")
    print()

    # Open browser
    if not args.no_browser:
        webbrowser.open(f'http://localhost:{args.port}')

    # Start server
    with socketserver.TCPServer(("", args.port), CORSHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == '__main__':
    main()

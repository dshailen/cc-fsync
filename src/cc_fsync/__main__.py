
"""
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Author: Shailendra Dharmistan, Zcaler Inc.
"""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from cc_fsync.sync import run_copy_process, settings
import schedule
import time
import daemon
import signal
import subprocess
import sys

# Configuration for logging
log_level = settings['logging'].get('log_level', 'INFO')
log_file = settings['logging'].get('log_file', 'cc-fsync.log')
max_bytes = settings['logging'].get('max_bytes', 10485760)  # 10MB
backup_count = settings['logging'].get('backup_count', 5)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(log_level.upper())
handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Get the interval from sync_script.py
interval = settings.get('interval', 60)

# Schedule the copy process to run periodically
schedule.every(interval).seconds.do(run_copy_process)

# Flag to indicate if the daemon should stop
should_stop = False

# Signal handler for graceful shutdown
def signal_handler(signum, frame):
    global should_stop
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    should_stop = True

def main():
    # Main loop to keep the script running and executing the scheduled tasks
    logger.info("Starting cc-fsync...")
    while not should_stop:
        schedule.run_pending()
        time.sleep(1)
    logger.info("Stopping cc-fsync...")

# Argument parsing
parser = argparse.ArgumentParser(description="Run the script in the foreground, background or as a daemon.")
parser.add_argument('--daemon', action='store_true', help="Run as a daemon")
parser.add_argument('--background', action='store_true', help="Run in the background")
args = parser.parse_args()

if args.daemon:
    # Run as a daemon
    with daemon.DaemonContext(
        files_preserve=[handler.stream],
        signal_map={
            signal.SIGTERM: signal_handler,
            signal.SIGINT: signal_handler
        }
    ):
        main()
elif args.background:
    # Run in the background using nohup
    command = ['nohup', 'python3'] + [arg for arg in sys.argv[:] if arg != '--background']
    with open('.out.log', 'w') as fp:
        subprocess.Popen(command, stdout=fp, stderr=fp, start_new_session=True)
    print(f"Running cc-fsync in the background...")
    sys.exit(0)
else:
    # Run in the foreground
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    main()


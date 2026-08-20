import sys
import os

# Add your project folder to the path
path = '/home/yourusername/megatek-forum'
if path not in sys.path:
    sys.path.insert(0, path)

# Set environment variables if needed
os.environ['SECRET_KEY'] = 'your-secret-key-here'
os.environ['MAIL_PASSWORD'] = 'your-app-password'

from app import app as application
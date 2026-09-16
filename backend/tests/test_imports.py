"""Test Browser Provider imports"""
import sys
sys.path.insert(0, 'H:/AI-Agent-Platform/backend')

from app.providers.browser_provider import BrowserProvider
from app.providers.bitbrowser_provider import BitBrowserProvider
from app.services.browser_service import BrowserService
from app.schemas.browser import BrowserProfileCreate, BrowserProfileResponse

print("All imports successful!")
print(f"BrowserProvider abstract methods: {[m for m in dir(BrowserProvider) if not m.startswith('_')]}")
print(f"BitBrowserProvider created: {BitBrowserProvider()}")

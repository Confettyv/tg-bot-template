"""Настройки до импорта bot.py (он читает окружение при импорте)."""
import os
import sys

os.environ.update({"BOT_TOKEN": "123456:TEST", "ADMIN_ID": "1"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

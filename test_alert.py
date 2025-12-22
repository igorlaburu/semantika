"""Test script to verify alert service SMTP configuration."""

from utils.alert_service import alert

if __name__ == "__main__":
    print("Sending test alert...")
    alert.test_alert()
    print("Test alert sent. Check igor@gako.ai inbox.")

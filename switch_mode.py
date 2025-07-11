#!/usr/bin/env python3
"""
MailBridge Mode Switcher

This utility allows you to easily switch between different modes:
- iCloud: Standard MailBridge functionality using iCloud
- postmark: Postmark-specific integration

Usage:
    python switch_mode.py icloud     # Switch to iCloud mode
    python switch_mode.py postmark   # Switch to Postmark mode
    python switch_mode.py status     # Show current mode
"""

import yaml
import sys
import os
from pathlib import Path

def load_config():
    """Load the current configuration file."""
    config_path = Path("/config/config.yml")
    if not config_path.exists():
        config_path = Path("config/config.yml")
    
    if not config_path.exists():
        print("❌ Configuration file not found!")
        sys.exit(1)
    
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def save_config(config):
    """Save the configuration back to file."""
    config_path = Path("/config/config.yml")
    if not config_path.exists():
        config_path = Path("config/config.yml")
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, indent=4)

def switch_mode(mode):
    """Switch to the specified mode."""
    # Normalize mode to proper case
    mode_mapping = {
        "icloud": "iCloud",
        "postmark": "postmark"
    }
    
    normalized_mode = mode_mapping.get(mode.lower())
    if not normalized_mode:
        print(f"❌ Invalid mode: {mode}")
        print("Valid modes: iCloud, postmark")
        sys.exit(1)
    
    # Use the normalized mode
    mode = normalized_mode
    
    config = load_config()
    
    # Ensure global section exists
    if "global" not in config:
        config["global"] = {}
    
    # Update mode
    config["global"]["mode"] = mode
    
    # Save configuration
    save_config(config)
    
    print(f"✅ Successfully switched to {mode} mode")
    print(f"📧 Your emails will now be processed using the {mode} integration")
    
    if mode == "postmark":
        print("\n📋 Postmark mode features:")
        print("   - Form submissions will be formatted with Postmark-specific styling")
        print("   - Email subjects will be prefixed with 'Postmark Inquiry:'")
        print("   - Auto-replies will have Postmark branding and styling")
        print("   - Pushover notifications will indicate Postmark mode")
    else:
        print("\n📋 iCloud mode features:")
        print("   - Standard MailBridge functionality using iCloud")
        print("   - Regular email formatting")
        print("   - Standard auto-reply system")

def show_status():
    """Show the current mode status."""
    config = load_config()
    current_mode = config.get("global", {}).get("mode", "iCloud")
    
    print(f"📊 Current MailBridge Mode: {current_mode}")
    
    if current_mode == "postmark":
        print("🎯 Postmark integration is active")
        print("   - Form submissions use Postmark formatting")
        print("   - Auto-replies include Postmark branding")
    else:
        print("🔧 iCloud MailBridge mode is active")
        print("   - Standard form processing using iCloud")
        print("   - Regular auto-reply system")

def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print("  python switch_mode.py icloud     # Switch to iCloud mode")
        print("  python switch_mode.py postmark   # Switch to Postmark mode")
        print("  python switch_mode.py status     # Show current mode")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "status":
        show_status()
    elif command in ["icloud", "postmark"]:
        switch_mode(command)
    else:
        print(f"❌ Unknown command: {command}")
        print("Valid commands: icloud, postmark, status")
        sys.exit(1)

if __name__ == "__main__":
    main() 
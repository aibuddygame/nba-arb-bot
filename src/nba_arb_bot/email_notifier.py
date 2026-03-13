"""
Email notification module for NBA Arbitrage Bot.

Sends email alerts when strong signals are detected.

Setup Instructions:
-------------------
1. Go to Yahoo Account Security: https://login.yahoo.com/account/security
2. Enable "Two-step verification" if not already enabled
3. Go to "Generate app password"
4. Select "Other App" and name it "NBA Arb Bot"
5. Copy the 16-character app password
6. Add to config.yaml under email section

Usage:
    from nba_arb_bot.email_notifier import send_alert_email

    send_alert_email(
        subject="Strong Signal Detected",
        body="Report content here...",
        strong_teams=["Team A", "Team B"]
    )
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from nba_arb_bot.config import load_config

# Module logger
logger = logging.getLogger(__name__)

# SMTP settings for common providers
SMTP_SETTINGS = {
    "yahoo": {
        "server": "smtp.mail.yahoo.com",
        "port": 587,
    },
    "gmail": {
        "server": "smtp.gmail.com",
        "port": 587,
    },
    "outlook": {
        "server": "smtp-mail.outlook.com",
        "port": 587,
    },
}


def get_smtp_settings(email: str) -> dict:
    """
    Get SMTP settings based on email domain.
    
    Args:
        email: Email address
        
    Returns:
        Dictionary with server and port
    """
    domain = email.split("@")[-1].lower()
    
    if "yahoo" in domain:
        return SMTP_SETTINGS["yahoo"]
    elif "gmail" in domain:
        return SMTP_SETTINGS["gmail"]
    elif "outlook" in domain or "hotmail" in domain:
        return SMTP_SETTINGS["outlook"]
    else:
        # Default to Yahoo settings
        return SMTP_SETTINGS["yahoo"]


def send_alert_email(
    subject: str,
    body: str,
    strong_teams: list[str],
) -> bool:
    """
    Send an email alert for strong signals.
    
    Args:
        subject: Email subject line
        body: Full report content
        strong_teams: List of team names with strong signals
        
    Returns:
        True if email sent successfully, False otherwise
    """
    config = load_config()
    
    # Check if email is configured
    if not hasattr(config, 'email') or not config.email:
        logger.warning("[EMAIL] Email not configured. Skipping notification.")
        return False
    
    email_config = config.email
    
    if not email_config.enabled:
        logger.info("[EMAIL] Email notifications disabled.")
        return False
    
    if not email_config.sender_email or not email_config.sender_password:
        logger.warning("[EMAIL] Email credentials not configured. Skipping notification.")
        return False
    
    recipient = email_config.recipient_email or email_config.sender_email
    
    # Get SMTP settings
    smtp_settings = get_smtp_settings(email_config.sender_email)
    
    # Create email message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_config.sender_email
    msg["To"] = recipient
    
    # Create HTML body
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .alert {{ background-color: #d4edda; border: 1px solid #c3e6cb; padding: 15px; margin: 10px 0; border-radius: 5px; }}
            .strong {{ color: #155724; font-weight: bold; font-size: 18px; }}
            pre {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; font-size: 12px; }}
        </style>
    </head>
    <body>
        <h2>🚨 NBA Arbitrage Bot - Strong Signal Alert</h2>
        
        <div class="alert">
            <p class="strong">Strong Signal Teams: {', '.join(strong_teams)}</p>
        </div>
        
        <h3>Full Report:</h3>
        <pre>{body}</pre>
        
        <p><em>This is an automated alert from NBA Arbitrage Bot.</em></p>
    </body>
    </html>
    """
    
    # Plain text version
    plain_body = f"""
NBA Arbitrage Bot - Strong Signal Alert

Strong Signal Teams: {', '.join(strong_teams)}

Full Report:
{body}

This is an automated alert from NBA Arbitrage Bot.
"""
    
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    
    try:
        logger.info(f"[EMAIL] Connecting to {smtp_settings['server']}:{smtp_settings['port']}...")
        
        with smtplib.SMTP(smtp_settings["server"], smtp_settings["port"]) as server:
            server.starttls()
            server.login(email_config.sender_email, email_config.sender_password)
            server.sendmail(
                email_config.sender_email,
                recipient,
                msg.as_string()
            )
        
        logger.info(f"[EMAIL] Alert sent successfully to {recipient}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"[EMAIL] Authentication failed. Check your app password. Error: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"[EMAIL] Failed to send email: {e}")
        return False
    except Exception as e:
        logger.error(f"[EMAIL] Unexpected error: {e}")
        return False


def send_strong_signal_alert(report_content: str, strong_teams: list[str]) -> bool:
    """
    Send email alert specifically for strong signals.
    
    Args:
        report_content: Full report content
        strong_teams: List of teams with strong signals
        
    Returns:
        True if email sent successfully
    """
    if not strong_teams:
        logger.info("[EMAIL] No strong signals. Skipping email.")
        return False
    
    subject = f"🚨 NBA Strong Signal: {', '.join(strong_teams)}"
    
    return send_alert_email(
        subject=subject,
        body=report_content,
        strong_teams=strong_teams,
    )


# CLI test
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    
    print("Testing email configuration...")
    print("Make sure you have configured email settings in config.yaml")
    
    # Test with sample data
    test_result = send_strong_signal_alert(
        report_content="This is a test report.",
        strong_teams=["Test Team"]
    )
    
    if test_result:
        print("✓ Email sent successfully!")
    else:
        print("✗ Email failed. Check configuration and logs.")

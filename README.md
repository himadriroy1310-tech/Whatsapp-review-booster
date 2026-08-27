# 💬 WhatsApp Google Review Automation Dashboard

A lightweight, zero-cost Python & Flask web tool built for local businesses (clinics, salons, auto shops, contractors) to capture 5-star Google reviews directly via WhatsApp.

---

## 📌 Key Highlights

- **100% Free & No API Limits:** Uses direct WhatsApp click-to-chat (`wa.me`) protocols. Requires no Twilio account, Meta Business verification, or monthly messaging credits.
- **Zero Carrier / Regional Restrictions:** Works seamlessly across all international markets with high WhatsApp penetration (UK, EU, UAE, Singapore, India, Australia, Latin America).
- **One-Tap Review Routing:** Pre-fills a personalized review message and generates a direct link taking the customer straight to the Google 5-star review modal.
- **Queue & Status Tracking:** Built-in SQLite database logs pending requests, completed sends, and exact timestamps to prevent duplicate outreach.
- **Front-Desk Friendly UI:** Simple, responsive interface designed for staff to add a customer name and phone number in seconds.

---

## ⚙️ Quick Start Setup

### 1. Clone the Repository & Set Up Python Environment
```powershell
git clone [https://github.com/](https://github.com/)<YOUR_USERNAME>/whatsapp-review-bot.git
cd whatsapp-review-bot

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Geminie Trading

Mobile-first Streamlit trading dashboard using Zerodha Kite Connect.

## Security
Credentials belong in Streamlit Secrets, never in source code.

Required secrets:
- `ZERODHA_API_KEY`
- `ZERODHA_API_SECRET`
- `ZERODHA_REDIRECT_URI`

The redirect URI must exactly match the URL registered in the Kite Connect developer console.

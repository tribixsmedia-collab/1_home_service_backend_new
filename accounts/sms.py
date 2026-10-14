"""
Pluggable SMS sending. Controlled by SMS_BACKEND in settings/.env:

  SMS_BACKEND=console   -> FREE. Just prints/logs the OTP. Use this while developing.
  SMS_BACKEND=fast2sms  -> Real SMS via Fast2SMS (needs FAST2SMS_API_KEY in .env)
  SMS_BACKEND=msg91     -> Real SMS via MSG91 (needs MSG91_AUTH_KEY and
                           MSG91_TEMPLATE_ID; the wording lives in the
                           DLT-approved template, not here)
  SMS_BACKEND=twilio    -> Real SMS via Twilio (needs TWILIO_* keys in .env)

To go live later: sign up for one of the real providers, put the API key in
.env, change SMS_BACKEND in .env -- NO CODE CHANGES NEEDED anywhere else.
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_otp_sms(phone_number: str, code: str) -> None:
    backend = getattr(settings, 'SMS_BACKEND', 'console')

    if backend == 'console':
        _send_console(phone_number, code)
    elif backend == 'fast2sms':
        _send_fast2sms(phone_number, code)
    elif backend == 'msg91':
        _send_msg91(phone_number, code)
    elif backend == 'twilio':
        _send_twilio(phone_number, code)
    else:
        raise ValueError(f"Unknown SMS_BACKEND: {backend}")


def _send_console(phone_number: str, code: str) -> None:
    # FREE mode for development: no real SMS sent. The OTP is just printed
    # to your terminal (and Django's log) so you can test the full flow.
    print(f"\n{'='*50}\n[DEV SMS] OTP for {phone_number} is: {code}\n{'='*50}\n")
    logger.info(f"[console SMS backend] OTP for {phone_number}: {code}")


def _send_fast2sms(phone_number: str, code: str) -> None:
    import requests
    api_key = settings.FAST2SMS_API_KEY
    resp = requests.get(
        "https://www.fast2sms.com/dev/bulkV2",
        params={
            "authorization": api_key,
            "route": "otp",
            "variables_values": code,
            "flash": 0,
            "numbers": phone_number,
        },
        timeout=10,
    )
    resp.raise_for_status()


MSG91_FLOW_URL = "https://control.msg91.com/api/v5/flow"


def _send_msg91(phone_number: str, code: str) -> None:
    """
    MSG91 Flow API v5. Shape verified against docs.msg91.com/sms/send-sms.

    Under India's DLT rules the wording cannot be chosen here. It has to match
    a template approved on the DLT portal, and is referenced by id -- which is
    why no message string appears below. The template leaves one blank for the
    code; MSG91_OTP_VARIABLE names it, because the name is whatever was typed
    when the template was created.

    The previous version of this function could not have worked: it posted a
    free-text `message` to api.msg91.com with a v2-era `route` parameter. DLT
    rejects free text, the host is wrong, and `recipients` was never sent.
    """
    import requests

    if not settings.MSG91_TEMPLATE_ID:
        raise ValueError(
            "MSG91_TEMPLATE_ID is not set. Under DLT the OTP wording comes "
            "from a template approved on the DLT portal, not from this code. "
            "Approve one, add it in MSG91, and put its id in .env."
        )

    # MSG91 wants the country code. A bare ten-digit Indian number is accepted
    # by the API and then simply never arrives, which is the worst outcome.
    mobile = phone_number.strip().lstrip("+").replace(" ", "")
    if len(mobile) == 10:
        mobile = f"91{mobile}"

    resp = requests.post(
        MSG91_FLOW_URL,
        headers={
            "accept": "application/json",
            "authkey": settings.MSG91_AUTH_KEY,
            "content-type": "application/json",
        },
        json={
            "template_id": settings.MSG91_TEMPLATE_ID,
            # Ask for the real outcome instead of "queued". Without it a
            # refusal still answers 200 and is indistinguishable from a send.
            "realTimeResponse": "1",
            "recipients": [{
                "mobiles": mobile,
                settings.MSG91_OTP_VARIABLE: code,
            }],
        },
        timeout=15,
    )
    resp.raise_for_status()

    # 200 is not delivery. MSG91 answers 200 with {"type": "error", ...} for a
    # rejected template, an unknown variable name, or an empty balance, and
    # the documented success body is {"type": "success", "message": "<id>"}.
    # Treating the status code as the answer is how an OTP silently vanishes.
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError(f"MSG91 returned a non-JSON reply: {resp.text[:200]}")

    if str(body.get("type", "")).lower() != "success":
        raise RuntimeError(f"MSG91 refused the message: {body}")

    logger.info("MSG91 accepted OTP for %s (request %s)", mobile, body.get("message"))


def _send_twilio(phone_number: str, code: str) -> None:
    from twilio.rest import Client
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(
        body=f"Your Home Service verification code is {code}.",
        from_=settings.TWILIO_FROM_NUMBER,
        to=f"+91{phone_number}" if not phone_number.startswith('+') else phone_number,
    )

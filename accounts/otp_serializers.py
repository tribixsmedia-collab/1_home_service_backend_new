import secrets
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, OTPRequest
from .sms import send_otp_sms


class SendOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)

    def validate_phone_number(self, value):
        value = value.strip()
        if not value.isdigit() or len(value) < 10:
            raise serializers.ValidationError("Enter a valid phone number (digits only, at least 10 digits).")
        return value

    def create_and_send(self):
        phone_number = self.validated_data['phone_number']

        # Rate limit: block a new OTP if one was already sent very recently.
        cooldown = getattr(settings, 'OTP_RESEND_COOLDOWN_SECONDS', 60)
        recent = OTPRequest.objects.filter(phone_number=phone_number).order_by('-created_at').first()
        if recent and (timezone.now() - recent.created_at).total_seconds() < cooldown:
            wait_left = cooldown - int((timezone.now() - recent.created_at).total_seconds())
            raise serializers.ValidationError(f"Please wait {wait_left} seconds before requesting another OTP.")

        # secrets, not the random module: that is the Mersenne Twister,
        # whose next output is derivable from a handful of observed
        # ones. These six digits are the whole of the login.
        code = f"{secrets.randbelow(900000) + 100000}"
        expiry_minutes = getattr(settings, 'OTP_EXPIRY_MINUTES', 5)
        otp = OTPRequest.objects.create(
            phone_number=phone_number,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
        )
        send_otp_sms(phone_number, code)
        return otp


def _available_username(phone_number):
    """
    A free username for a new customer account.

    The phone number doubles as the username, but usernames are unique across
    every role and an admin may already have given this one to a vendor -- the
    same person, very often, since one number can hold both a customer and a
    vendor account. Falling back to a suffix keeps sign-in working instead of
    failing on the clash; nothing reads meaning out of a customer's username,
    only their phone and their role.
    """
    if not User.objects.filter(username=phone_number).exists():
        return phone_number

    suffix = 2
    while User.objects.filter(username=f'{phone_number}-{suffix}').exists():
        suffix += 1
    return f'{phone_number}-{suffix}'


class VerifyOTPSerializer(serializers.Serializer):
    """
    Verifies the OTP. If this phone number has no account yet, creates one
    (auto-signup) using the optional profile fields provided. If the account
    already exists, this just logs them in.
    """
    phone_number = serializers.CharField(max_length=15)
    code = serializers.CharField(max_length=6)

    # Only required for a BRAND NEW customer (first-time signup).
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    referral_code = serializers.CharField(max_length=12, required=False, allow_blank=True)

    def validate(self, attrs):
        phone_number = attrs['phone_number'].strip()
        code = attrs['code'].strip()

        otp = OTPRequest.objects.filter(
            phone_number=phone_number, is_verified=False
        ).order_by('-created_at').first()

        if not otp:
            raise serializers.ValidationError("No pending OTP found for this number. Please request a new one.")

        max_attempts = 5
        if otp.attempts >= max_attempts:
            raise serializers.ValidationError("Too many incorrect attempts. Please request a new OTP.")

        if timezone.now() > otp.expires_at:
            raise serializers.ValidationError("This OTP has expired. Please request a new one.")

        if otp.code != code:
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            raise serializers.ValidationError("Incorrect OTP. Please try again.")

        otp.is_verified = True
        otp.save(update_fields=['is_verified'])
        attrs['_otp'] = otp
        return attrs

    def _attach_referral(self, customer):
        """
        Records who invited this brand new customer. A bad or missing code is
        not worth failing a signup over, so anything unexpected is ignored.
        """
        from referrals.models import Referral, ReferralCode, ReferralProgram

        code = (self.validated_data.get('referral_code') or '').strip().upper()
        if not code:
            return

        try:
            program = ReferralProgram.get_solo()
            if not program.is_active:
                return

            referral_code = ReferralCode.objects.filter(code=code).first()
            # Nobody gets to refer themselves.
            if referral_code is None or referral_code.customer_id == customer.id:
                return

            Referral.objects.create(
                referrer=referral_code.customer,
                referred_customer=customer,
                code_used=code,
            )
        except Exception:
            pass

    def verify_and_login(self):
        from customers.models import Customer

        phone_number = self.validated_data['phone_number'].strip()
        is_new_user = False

        try:
            user = User.objects.get(phone_number=phone_number, role=User.Role.CUSTOMER)
        except User.DoesNotExist:
            # First time this phone number has verified an OTP -> create the account.
            user = User.objects.create_user(
                username=_available_username(phone_number),
                phone_number=phone_number,
                first_name=self.validated_data.get('first_name', ''),
                last_name=self.validated_data.get('last_name', ''),
                role=User.Role.CUSTOMER,
            )
            user.set_unusable_password()  # no password login for phone/OTP accounts
            user.save()
            customer = Customer.objects.create(
                user=user, address=self.validated_data.get('address', '')
            )
            is_new_user = True
            self._attach_referral(customer)

        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'is_new_user': is_new_user,
            'user': {
                'id': user.id,
                'phone_number': user.phone_number,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
        }

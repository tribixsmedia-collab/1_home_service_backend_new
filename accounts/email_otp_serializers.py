import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .email_otp import send_email_otp
from .models import EmailOTPRequest, User

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


class SendEmailOTPSerializer(serializers.Serializer):
    """
    Emails a 6-digit code to the address the signed-in customer typed into
    their profile. The address is NOT written to the account here -- only a
    successfully verified code does that.
    """
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.strip().lower()

        # One address, one account. Checking against verified addresses only
        # means an abandoned, never-confirmed attempt by somebody else cannot
        # lock the rightful owner out of their own email.
        taken = (
            User.objects
            .filter(email__iexact=value, customer_profile__email_verified=True)
            .exclude(pk=self.context['request'].user.pk)
            .exists()
        )
        if taken:
            raise serializers.ValidationError(
                "This email is already linked to another account."
            )
        return value

    def create_and_send(self):
        user = self.context['request'].user
        email = self.validated_data['email']

        # Rate limit per user, not per address: otherwise a script could walk
        # a list of addresses and send a mail to each one at full speed.
        cooldown = getattr(settings, 'OTP_RESEND_COOLDOWN_SECONDS', 60)
        recent = EmailOTPRequest.objects.filter(user=user).order_by('-created_at').first()
        if recent and (timezone.now() - recent.created_at).total_seconds() < cooldown:
            wait_left = cooldown - int((timezone.now() - recent.created_at).total_seconds())
            raise serializers.ValidationError(
                f"Please wait {wait_left} seconds before requesting another code."
            )

        # secrets, not the random module: that is the Mersenne Twister,
        # whose next output is derivable from a handful of observed
        # ones. These six digits are the whole of the login.
        code = f"{secrets.randbelow(900000) + 100000}"
        expiry_minutes = getattr(settings, 'OTP_EXPIRY_MINUTES', 5)

        otp = EmailOTPRequest.objects.create(
            user=user,
            email=email,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
        )

        try:
            send_email_otp(email, code, first_name=user.first_name or '')
        except Exception as exc:
            # A row nobody can ever use is worse than no row: it would hold
            # the cooldown open and block the retry that might work.
            otp.delete()
            logger.exception("Could not send email OTP to %s", email)
            raise serializers.ValidationError(
                "We could not send the code to that address. "
                "Please check it and try again."
            ) from exc

        return otp


class VerifyEmailOTPSerializer(serializers.Serializer):
    """
    Checks the code and, when it matches, writes the address onto the account
    and marks it verified. Verifying is what saves the email -- the profile
    form only ever confirms what already went through here.
    """
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def validate(self, attrs):
        user = self.context['request'].user
        email = attrs['email'].strip().lower()
        code = attrs['code'].strip()

        otp = (
            EmailOTPRequest.objects
            .filter(user=user, email__iexact=email, is_verified=False)
            .order_by('-created_at')
            .first()
        )

        if not otp:
            raise serializers.ValidationError(
                "No pending code for this address. Please request a new one."
            )

        if otp.attempts >= MAX_ATTEMPTS:
            raise serializers.ValidationError(
                "Too many incorrect attempts. Please request a new code."
            )

        if timezone.now() > otp.expires_at:
            raise serializers.ValidationError(
                "This code has expired. Please request a new one."
            )

        if otp.code != code:
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            remaining = MAX_ATTEMPTS - otp.attempts
            if remaining <= 0:
                raise serializers.ValidationError(
                    "Too many incorrect attempts. Please request a new code."
                )
            raise serializers.ValidationError(
                f"Incorrect code. {remaining} attempt"
                f"{'' if remaining == 1 else 's'} left."
            )

        attrs['_otp'] = otp
        attrs['email'] = email
        return attrs

    @transaction.atomic
    def confirm(self):
        user = self.context['request'].user
        otp = self.validated_data['_otp']
        email = self.validated_data['email']

        otp.is_verified = True
        otp.save(update_fields=['is_verified'])

        user.email = email
        user.save(update_fields=['email'])

        profile = getattr(user, 'customer_profile', None)
        if profile is not None and not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=['email_verified'])

        return {'email': email, 'email_verified': True}

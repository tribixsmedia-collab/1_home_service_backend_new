from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from accounts.models import User
from .models import Customer
from maps import plus_codes


class CustomerRegisterSerializer(serializers.Serializer):
    """
    Used by the Customer app's signup screen.
    Creates BOTH the User (login) and Customer (profile) in one call.
    """
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=15)
    address = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data.get('last_name', ''),
            phone_number=validated_data['phone_number'],
            role=User.Role.CUSTOMER,
        )
        customer = Customer.objects.create(
            user=user,
            address=validated_data.get('address', ''),
            latitude=validated_data.get('latitude'),
            longitude=validated_data.get('longitude'),
        )
        return customer


class CustomerProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name', required=False)
    phone_number = serializers.CharField(source='user.phone_number')
    email = serializers.EmailField(source='user.email', required=False, allow_blank=True)
    is_profile_complete = serializers.SerializerMethodField()
    # Worked out from the pin rather than stored: a column for it could only
    # ever drift out of step with the latitude and longitude beside it.
    plus_code = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'username', 'first_name', 'last_name', 'phone_number', 'email',
            'address', 'state', 'district', 'pincode', 'latitude', 'longitude',
            'plus_code', 'is_profile_complete', 'email_verified',
        ]
        # Set by the email OTP flow alone; a profile save can never claim it.
        read_only_fields = ['email_verified']

    def get_plus_code(self, obj):
        return plus_codes.plus_code_for(obj.latitude, obj.longitude)

    def get_is_profile_complete(self, obj):
        return bool(
            obj.user.first_name
            and obj.address
            and obj.state
            and obj.district
            and obj.pincode
        )

    def validate(self, attrs):
        """
        An email may only reach the account through the OTP flow, which saves
        it itself the moment a code checks out. So by then a verified address
        already matches what is stored -- anything else is an address nobody
        has proved, and is refused here.

        An address that predates verification is left alone: those customers
        are not locked out of saving their own profile, they simply show as
        unverified until they confirm it.
        """
        user_data = attrs.get('user', {})
        if 'email' in user_data:
            new_email = (user_data['email'] or '').strip().lower()
            current = (self.instance.user.email or '').strip().lower() if self.instance else ''
            if new_email and new_email != current:
                raise serializers.ValidationError({
                    'email': 'Please verify this email address with the code '
                             'we send before saving.'
                })
            # Store the same normalised form the OTP flow wrote, so a save
            # cannot quietly turn a verified address into a different string.
            user_data['email'] = new_email
        return attrs

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        # Clearing the email drops the verified badge with it, so whatever is
        # entered next has to be confirmed on its own merits.
        if 'email' in user_data and not (user_data['email'] or '').strip():
            instance.email_verified = False
        for attr, value in user_data.items():
            setattr(instance.user, attr, value)
        instance.user.save()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
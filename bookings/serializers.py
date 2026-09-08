from decimal import Decimal

from rest_framework import serializers
from services.pricing import line_total, parse_money
from .models import Booking, JobStartPhoto
from maps import plus_codes


class BookingCreateSerializer(serializers.ModelSerializer):
    """
    Used by the Customer app to create a new booking.
    Vendor is NOT set here -- it stays null until admin assigns one manually.
    Amount is calculated on the backend from services_json minus discount.
    """
    class Meta:
        model = Booking
        fields = [
            'id',
            'category', 'subcategory', 'services_json',
            'preferred_date', 'preferred_time', 'notes',
            'address_text', 'address_state', 'address_district',
            'address_pincode', 'customer_phone',
            'location_lat', 'location_lng',
            'amount',
            'discount_amount', 'coupon_code', 'discount_details',
            'form_submission',
            'preferred_vendor',
            'status', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'amount']

    def create(self, validated_data):
        customer = self.context['request'].user.customer_profile

        # Calculate subtotal from services_json.
        #
        # Quantity is a Decimal, not an int: a per-sq-ft line carries 1000 and
        # a per-kg line 2.5, and truncating those would charge the customer
        # something other than what the cart showed them.
        services = validated_data.get('services_json', []) or []
        subtotal = sum(
            (line_total(svc) for svc in services), Decimal('0')
        )

        discount = parse_money(validated_data.get('discount_amount'))
        final_amount = max(subtotal - discount, Decimal('0'))
        validated_data['amount'] = final_amount

        booking = Booking.objects.create(customer=customer, **validated_data)

        # The form is submitted before the booking exists, so its own `booking`
        # FK comes back null. Close the loop here — the admin page and the
        # vendor's job both read the answers through that side of the link.
        submission = booking.form_submission
        if submission is not None and submission.booking_id != booking.id:
            submission.booking = booking
            submission.save(update_fields=['booking'])

        return booking

class BookingListSerializer(serializers.ModelSerializer):
    """
    Used to LIST bookings -- shown to both Customer app (their own bookings)
    and Vendor app (their assigned jobs). Includes readable names, not just IDs.
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    subcategory_name = serializers.CharField(source='subcategory.name', read_only=True, default=None)
    customer_name = serializers.SerializerMethodField()
    customer_address = serializers.CharField(source='customer.address', read_only=True)
    customer_phone = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    preferred_vendor_name = serializers.CharField(
        source='preferred_vendor.display_name', read_only=True, default=None
    )
    form_name = serializers.SerializerMethodField()
    form_groups = serializers.SerializerMethodField()
    form_responses = serializers.SerializerMethodField()
    # The pin as a Plus Code, for the vendor to paste into any maps app. Worked
    # out from location_lat/location_lng on the way out rather than stored, so
    # it cannot disagree with them.
    plus_code = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'category', 'category_name', 'subcategory', 'subcategory_name',
            'customer_name', 'customer_address', 'customer_phone',
            'vendor', 'vendor_name', 'preferred_vendor', 'preferred_vendor_name',
            'preferred_date', 'preferred_time', 'status',
            'amount', 'payment_status', 'notes', 'services_json',
           'address_text', 'address_state', 'address_district', 'address_pincode',
            'location_lat', 'location_lng', 'plus_code',
            'form_name', 'form_groups', 'form_responses',
            'created_at', 'assigned_at', 'completed_at',
        ]

    def get_plus_code(self, obj):
        return plus_codes.plus_code_for(obj.location_lat, obj.location_lng)

    def get_customer_name(self, obj):
        u = obj.customer.user
        return u.get_full_name() or u.username

    def get_customer_phone(self, obj):
        """
        Number the vendor should call. Prefers the phone captured on the booking
        itself (the customer may book for someone else's place), falling back to
        the number on their account for bookings made before that field existed.
        """
        return obj.customer_phone or obj.customer.user.phone_number or ''

    def get_vendor_name(self, obj):
        if obj.vendor:
            u = obj.vendor.user
            return u.get_full_name() or u.username
        return None

    def get_form_name(self, obj):
        """Heading for the answers — the service or form they belong to."""
        groups = obj.form_answer_groups
        return groups[0]['title'] if groups else None

    def get_form_groups(self, obj):
        """
        The customer's answers so the vendor knows what the job involves
        before arriving, grouped by service so a multi-service booking stays
        readable. Always a list — empty when no form was filled.
        """
        return obj.form_answer_groups

    def get_form_responses(self, obj):
        """Flattened view of the same answers, for callers that want one list."""
        return [
            response
            for group in obj.form_answer_groups
            for response in group['responses']
        ]


class JobStartPhotoSerializer(serializers.ModelSerializer):
    """
    Vendor uploads this when they arrive on-site to start the job.
    latitude/longitude come from the phone's GPS at the moment the photo is taken
    (captured client-side in Flutter using the geolocator package).
    """
    class Meta:
        model = JobStartPhoto
        fields = ['id', 'image', 'latitude', 'longitude', 'captured_at']
        read_only_fields = ['id', 'captured_at']
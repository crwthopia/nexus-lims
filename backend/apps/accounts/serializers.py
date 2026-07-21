from rest_framework import serializers

from apps.accounts.models import CustomerUser, ESignature, Role, StaffUser


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "permission_set"]


class StaffUserSerializer(serializers.ModelSerializer):
    roles = RoleSerializer(many=True, read_only=True)

    class Meta:
        model = StaffUser
        fields = [
            "id", "display_name", "email", "roles", "is_active",
            "instrument_certifications", "prc_license_number", "prc_license_validity_date",
        ]
        read_only_fields = fields


class CustomerUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerUser
        fields = [
            "id", "email", "is_email_verified", "mfa_enabled",
            "organization_name", "prc_license_number", "created_at",
        ]
        read_only_fields = fields


class CustomerRegisterSerializer(serializers.Serializer):
    """Request-only (Blueprint Section 6: POST /auth/customer/register); response is CustomerUserSerializer."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    organization_name = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    prc_license_number = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_email(self, value):
        if CustomerUser.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value


class CustomerLoginSerializer(serializers.Serializer):
    """Request-only (Blueprint Section 6: POST /auth/customer/login)."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    mfa_code = serializers.CharField(required=False, allow_blank=True)


class CustomerVerifyEmailSerializer(serializers.Serializer):
    """Request-only (Blueprint Section 6: POST /auth/customer/verify-email)."""

    token = serializers.CharField()


class CustomerMFACodeSerializer(serializers.Serializer):
    """Request-only, for POST /auth/customer/mfa/confirm."""

    code = serializers.CharField()


class ESignatureSerializer(serializers.ModelSerializer):
    signer_display_name = serializers.CharField(source="signer.display_name", read_only=True)

    class Meta:
        model = ESignature
        fields = [
            "id", "signer", "signer_display_name", "signer_type", "meaning",
            "signed_entity_type", "signed_entity_id", "timestamp", "authentication_method",
        ]
        read_only_fields = fields

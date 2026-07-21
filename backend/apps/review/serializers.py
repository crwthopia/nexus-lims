from rest_framework import serializers

from apps.review.models import ApprovalAction, ReviewAction


class ReviewActionSerializer(serializers.ModelSerializer):
    reviewer_display_name = serializers.CharField(source="reviewer.display_name", read_only=True)

    class Meta:
        model = ReviewAction
        fields = [
            "id", "test_result", "sample", "reviewer", "reviewer_display_name",
            "action", "comments", "e_signature", "created_at",
        ]
        read_only_fields = fields


class ApprovalActionSerializer(serializers.ModelSerializer):
    approver_display_name = serializers.CharField(source="approver.display_name", read_only=True)

    class Meta:
        model = ApprovalAction
        fields = [
            "id", "sample", "approver", "approver_display_name",
            "disposition", "e_signature", "created_at",
        ]
        read_only_fields = fields

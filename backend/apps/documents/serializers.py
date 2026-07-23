from rest_framework import serializers

from apps.documents.models import Document, DocumentVersion


class DocumentVersionSerializer(serializers.ModelSerializer):
    approved_by_display_name = serializers.CharField(source="approved_by.display_name", read_only=True)

    class Meta:
        model = DocumentVersion
        fields = [
            "id", "document", "version_number", "file_id", "approved_by",
            "approved_by_display_name", "effective_date", "is_current", "created_at",
        ]
        # approved_by/is_current are only ever set via DocumentVersionViewSet.approve
        # (FR-D1-03: designating the current version is a controlled action,
        # not a plain field edit), so they're read-only here.
        read_only_fields = ["id", "approved_by", "is_current", "created_at"]


class DocumentSerializer(serializers.ModelSerializer):
    """current_version_number: read-only convenience field for list UIs, which would otherwise only see current_version's bare FK id."""

    current_version_number = serializers.IntegerField(source="current_version.version_number", read_only=True, default=None)

    class Meta:
        model = Document
        fields = ["id", "title", "type", "current_version", "current_version_number", "created_at"]
        read_only_fields = ["id", "current_version", "created_at"]


class DocumentDetailSerializer(DocumentSerializer):
    versions = DocumentVersionSerializer(many=True, read_only=True)

    class Meta(DocumentSerializer.Meta):
        fields = DocumentSerializer.Meta.fields + ["versions"]

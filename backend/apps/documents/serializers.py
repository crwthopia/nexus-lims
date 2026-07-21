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
    class Meta:
        model = Document
        fields = ["id", "title", "type", "current_version", "created_at"]
        read_only_fields = ["id", "current_version", "created_at"]


class DocumentDetailSerializer(DocumentSerializer):
    versions = DocumentVersionSerializer(many=True, read_only=True)

    class Meta(DocumentSerializer.Meta):
        fields = DocumentSerializer.Meta.fields + ["versions"]

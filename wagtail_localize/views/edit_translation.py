import json

from django.db import models
from django.http import Http404
from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.utils.encoding import force_text
from django.utils.text import capfirst
from modelcluster.fields import ParentalKey
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from wagtail.core.blocks import StructBlock
from wagtail.core.fields import StreamField
from wagtail.core.models import Page, TranslatableMixin

from wagtail_localize.models import Translation, StringTranslation, StringSegment


class StringTranslationSerializer(serializers.ModelSerializer):
    string_id = serializers.ReadOnlyField(source='translation_of_id')
    segment_id = serializers.SerializerMethodField('get_segment_id')
    comment = serializers.SerializerMethodField('get_comment')

    def get_segment_id(self, translation):
        if 'translation_source' in self.context:
            translation_source = self.context['translation_source']
            return translation_source.stringsegment_set.filter(
                string_id=translation.translation_of_id,
                context_id=translation.context_id,
            ).values_list('id', flat=True).first()

    def get_comment(self, translation):
        return "Translated"

    class Meta:
        model = StringTranslation
        fields = ['string_id', 'segment_id', 'data', 'comment']


def edit_translation(request, translation, instance):
    live_url = None
    if isinstance(instance, Page):
        page_perms = instance.permissions_for_user(request.user)

        if instance.live:
            live_url = instance.full_url

    source_instance = translation.source.get_source_instance()

    def get_location(segment):
        context = segment.context
        context_path_components = context.path.split('.')
        field = segment.source.specific_content_type.model_class()._meta.get_field(context_path_components[0])

        if isinstance(field, StreamField):
            stream_value = field.value_from_object(source_instance)
            stream_blocks_by_id = {
                block.id: block
                for block in field.value_from_object(source_instance)
            }
            block_id = context_path_components[1]
            block_value = stream_blocks_by_id[block_id]
            block_type = stream_value.stream_block.child_blocks[block_value.block_type]

            if isinstance(block_type, StructBlock):
                block_field_name = context_path_components[2]
                block_field = block_type.child_blocks[block_field_name].label
            else:
                block_field = None

            return {
                'field': capfirst(block_type.label),
                'blockId': block_id,
                'fieldHelpText': '',
                'subField': block_field,
            }

        elif (
            isinstance(field, (models.ManyToOneRel))
            and isinstance(field.remote_field, ParentalKey)
            and issubclass(field.related_model, TranslatableMixin)
        ):
            child_field = field.related_model._meta.get_field(context_path_components[2])

            return {
                'field': capfirst(force_text(field.related_model._meta.verbose_name)),
                'blockId': context_path_components[1],
                'fieldHelpText':  force_text(child_field.help_text),
                'subField': capfirst(force_text(child_field.verbose_name)),
            }

        else:
            return {
                'field': capfirst(force_text(field.verbose_name)),
                'blockId': None,
                'fieldHelpText': force_text(field.help_text),
                'subField': None,
            }

    string_segments = translation.source.stringsegment_set.all()
    string_translations = string_segments.get_translations(translation.target_locale)

    return render(request, 'wagtail_localize/admin/edit_translation.html', {
        # These props are passed directly to the TranslationEditor react component
        'props': json.dumps({
            'object': {
                'title': str(instance),
                'isDraft': not instance.live if isinstance(instance, Page) else False,
                'isLocked': instance.locked if isinstance(instance, Page) else False,
                'lastPublishedAt': instance.last_published_at.isoformat() if isinstance(instance, Page) and instance.last_published_at else None,
                'liveUrl': live_url,
            },
            'sourceLocale': {
                'code': translation.source.locale.language_code,
                'displayName': translation.source.locale.get_display_name(),
            },
            'locale': {
                'code': translation.target_locale.language_code,
                'displayName': translation.target_locale.get_display_name(),
            },
            'translations': [
                {
                    'title': str(translated_instance),
                    'locale': {
                        'code': translated_instance.locale.language_code,
                        'displayName': translated_instance.locale.get_display_name(),
                    },
                    'editUrl': reverse('wagtailadmin_pages:edit', args=[translated_instance.id]) if isinstance(translated_instance, Page) else None,  # TODO
                }
                for translated_instance in instance.get_translations().select_related('locale')
            ],
            'perms': {
                'canPublish': not isinstance(instance, Page) or page_perms.can_publish(),
                'canUnpublish': isinstance(instance, Page) and page_perms.can_publish(),
                'canLock': isinstance(instance, Page) and page_perms.can_lock(),
                'canDelete': True,  # TODO
            },
            'segments': [
                {
                    'id': segment.id,
                    'contentPath': segment.context.path,
                    'source': segment.string.data,
                    'location': get_location(segment),
                    'editUrl': reverse('wagtail_localize:edit_string_translation', kwargs={'translation_id': translation.id, 'string_segment_id': segment.id}),
                }
                for segment in string_segments
            ],

            # We serialize the translation data using Django REST Framework.
            # This gives us a consistent representation with the APIs so we
            # can dynamically update translations in the view.
            'initialStringTranslations': StringTranslationSerializer(string_translations, many=True, context={'translation_source': translation.source}).data,
        })
    })


@api_view(['PUT', 'DELETE'])
def edit_string_translation(request, translation_id, string_segment_id):
    translation = get_object_or_404(Translation, id=translation_id)
    string_segment = get_object_or_404(StringSegment, id=string_segment_id)

    if string_segment.context.object_id != translation.source.object_id:
        raise Http404

    if request.method == 'PUT':
        string_translation, created = StringTranslation.objects.update_or_create(
            translation_of_id=string_segment.string_id,
            locale_id=translation.target_locale_id,
            context_id=string_segment.context_id,
            defaults={
                'data': request.POST['value'],
            }
        )

        return Response(StringTranslationSerializer(string_translation, context={'translation_source': translation.source}).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    elif request.method == 'DELETE':
        string_translation = StringTranslation.objects.filter(
            translation_of_id=string_segment.string_id,
            locale_id=translation.target_locale_id,
            context_id=string_segment.context_id,
        ).first()

        string_translation.delete()

        return Response(StringTranslationSerializer(string_translation, context={'translation_source': translation.source}).data,  status=status.HTTP_200_OK)

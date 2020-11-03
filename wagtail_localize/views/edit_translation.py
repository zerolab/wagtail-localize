import json
import tempfile
from collections import defaultdict

import polib
from django.contrib.admin.utils import quote
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.functional import cached_property
from django.utils.text import capfirst, slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from modelcluster.fields import ParentalKey
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from wagtail.admin import messages
from wagtail.admin.edit_handlers import TabbedInterface
from wagtail.admin.navigation import get_explorable_root_page
from wagtail.admin.templatetags.wagtailadmin_tags import avatar_url
from wagtail.admin.views.pages.utils import get_valid_next_url_from_request
from wagtail.core import blocks
from wagtail.core.fields import StreamField
from wagtail.core.models import Page, TranslatableMixin
from wagtail.core.utils import cautious_slugify
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.documents.models import AbstractDocument
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import AbstractImage
from wagtail.snippets.permissions import get_permission_name, user_can_edit_snippet_type
from wagtail.snippets.views.snippets import get_snippet_edit_handler

from wagtail_localize.machine_translators import get_machine_translator
from wagtail_localize.models import Translation, StringTranslation, StringSegment, OverridableSegment, SegmentOverride
from wagtail_localize.segments import StringSegmentValue


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField(source='get_full_name')
    avatar_url = serializers.SerializerMethodField('get_avatar_url')

    def get_avatar_url(self, user):
        return avatar_url(user, size=25)

    class Meta:
        model = get_user_model()
        fields = ['full_name', 'avatar_url']


class StringTranslationSerializer(serializers.ModelSerializer):
    string_id = serializers.ReadOnlyField(source='translation_of_id')
    segment_id = serializers.SerializerMethodField('get_segment_id')
    error = serializers.ReadOnlyField(source='get_error')
    comment = serializers.ReadOnlyField(source='get_comment')
    last_translated_by = UserSerializer()

    def get_segment_id(self, translation):
        if 'translation_source' in self.context:
            translation_source = self.context['translation_source']
            return translation_source.stringsegment_set.filter(
                string_id=translation.translation_of_id,
                context_id=translation.context_id,
            ).values_list('id', flat=True).first()

    class Meta:
        model = StringTranslation
        fields = ['string_id', 'segment_id', 'data', 'error', 'comment', 'last_translated_by']


class SegmentOverrideSerializer(serializers.ModelSerializer):
    segment_id = serializers.SerializerMethodField('get_segment_id')
    error = serializers.ReadOnlyField(source='get_error')

    def get_segment_id(self, override):
        if 'translation_source' in self.context:
            translation_source = self.context['translation_source']

            try:
                return translation_source.overridablesegment_set.only('id').get(
                    context_id=override.context_id,
                ).id
            except OverridableSegment.DoesNotExist:
                return

    class Meta:
        model = SegmentOverride
        fields = ['segment_id', 'data', 'error']


class TabHelper:
    def __init__(self, instance):
        self.instance = instance

    @cached_property
    def edit_handler(self):
        if isinstance(self.instance, Page):
            return self.instance.get_edit_handler()
        else:
            return get_snippet_edit_handler(self.instance.__class__)

    @cached_property
    def tabs(self):
        if isinstance(self.edit_handler, TabbedInterface):
            tabs = []

            for tab in self.edit_handler.children:
                tabs.append(tab.heading)

            return tabs

        else:
            return [_("Content")]

    @property
    def tabs_with_slugs(self):
        return [
            {
                'label': label,
                'slug': cautious_slugify(label),
            }
            for label in self.tabs
        ]

    @cached_property
    def field_tab_mapping(self):
        if isinstance(self.edit_handler, TabbedInterface):
            field_tabs = {}
            for tab in self.edit_handler.children:
                for tab_field in tab.required_fields():
                    field_tabs[tab_field] = tab.heading

            return field_tabs
        else:
            return {}

    def get_field_tab(self, field_name):
        if field_name in self.field_tab_mapping:
            return self.field_tab_mapping[field_name]
        else:
            return self.tabs[0]


def get_segment_location_info(source_instance, tab_helper, content_path, widget=False):
    context_path_components = content_path.split('.')
    field = source_instance._meta.get_field(context_path_components[0])

    # Work out which tab the segment is on from edit handler
    tab = cautious_slugify(tab_helper.get_field_tab(field.name))

    def widget_from_field(field):
        if isinstance(field, models.ForeignKey):
            if issubclass(field.related_model, Page):
                # TODO: Allowed page types
                return {
                    'type': 'page_chooser'
                }

            elif issubclass(field.related_model, AbstractDocument):
                return {
                    'type': 'document_chooser'
                }

            elif issubclass(field.related_model, AbstractImage):
                return {
                    'type': 'image_chooser'
                }

        elif isinstance(field, (models.CharField, models.TextField, models.EmailField, models.URLField)):
            return {
                'type': 'text',
            }

        return {
            'type': 'unknown'
        }

    def widget_from_block(block):
        # TODO: Snippet chooser block
        if isinstance(block, blocks.PageChooserBlock):
            # TODO: Allowed page types
            return {
                'type': 'page_chooser'
            }

        elif isinstance(block, DocumentChooserBlock):
            return {
                'type': 'document_chooser'
            }

        elif isinstance(block, ImageChooserBlock):
            return {
                'type': 'image_chooser'
            }

        elif isinstance(block, (blocks.CharBlock, blocks.TextBlock, blocks.EmailBlock, blocks.URLBlock)):
            return {
                'type': 'text',
            }

        return {
            'type': 'unknown'
        }

    if isinstance(field, StreamField):
        stream_value = field.value_from_object(source_instance)
        stream_blocks_by_id = {
            block.id: block
            for block in field.value_from_object(source_instance)
        }
        block_id = context_path_components[1]
        block_value = stream_blocks_by_id[block_id]
        block_type = stream_value.stream_block.child_blocks[block_value.block_type]

        if isinstance(block_type, blocks.StructBlock):
            block_field_name = context_path_components[2]
            block_type = block_type.child_blocks[block_field_name]
            block_field = block_type.child_blocks[block_field_name].label
        else:
            block_field = None

        return {
            'tab': tab,
            'field': capfirst(block_type.label),
            'blockId': block_id,
            'fieldHelpText': '',
            'subField': block_field,
            'widget': widget_from_block(block_type) if widget else None,
        }

    elif (
        isinstance(field, (models.ManyToOneRel))
        and isinstance(field.remote_field, ParentalKey)
        and issubclass(field.related_model, TranslatableMixin)
    ):
        child_field = field.related_model._meta.get_field(context_path_components[2])

        return {
            'tab': tab,
            'field': capfirst(field.related_model._meta.verbose_name),
            'blockId': context_path_components[1],
            'fieldHelpText': child_field.help_text,
            'subField': capfirst(child_field.verbose_name),
            'widget': widget_from_field(child_field) if widget else None,
        }

    else:
        return {
            'tab': tab,
            'field': capfirst(field.verbose_name),
            'blockId': None,
            'fieldHelpText': field.help_text,
            'subField': None,
            'widget': widget_from_field(field) if widget else None,
        }


def edit_translation(request, translation, instance):
    if isinstance(instance, Page):
        # Page
        # Note: Edit permission is already checked by the edit page view

        page_perms = instance.permissions_for_user(request.user)

        is_live = instance.live
        is_locked = instance.locked

        if instance.live_revision:
            last_published_at = instance.live_revision.created_at
            last_published_by = instance.live_revision.user
        else:
            last_published_at = instance.last_published_at
            last_published_by = None

        if instance.live:
            live_url = instance.full_url
        else:
            live_url = None

        can_publish = page_perms.can_publish()
        can_unpublish = page_perms.can_unpublish()
        can_lock = page_perms.can_lock()
        can_unlock = page_perms.can_unlock()
        can_delete = page_perms.can_delete()

    else:
        # Snippet
        # Note: Edit permission is already checked by the edit snippet view

        is_live = True
        is_locked = False
        last_published_at = None
        last_published_by = None
        live_url = None

        can_publish = True
        can_unpublish = False
        can_lock = False
        can_unlock = False
        can_delete = request.user.has_perm(get_permission_name('delete', instance.__class__))

    source_instance = translation.source.get_source_instance()

    if request.method == 'POST':
        if request.POST.get('action') == 'publish':
            if isinstance(instance, Page):
                if not page_perms.can_publish():
                    raise PermissionDenied

            try:
                translation.save_target(user=request.user, publish=True)

            except ValidationError:
                messages.error(request, _("New validation errors were found when publishing '{object}' in {locale}. Please fix them or click publish again to ignore these translations for now.").format(
                    object=str(instance),
                    locale=translation.target_locale.get_display_name()
                ))

            else:
                # Refresh instance to title in success message is up to date
                instance.refresh_from_db()

                string_segments = translation.source.stringsegment_set.all().order_by('order')
                string_translations = string_segments.get_translations(translation.target_locale)

                # Using annotate_translation as this ignores errors by default (so both errors and missing segments treated the same)
                if string_segments.annotate_translation(translation.target_locale).filter(translation__isnull=True).exists():
                    # One or more strings had an error
                    messages.warning(request, _("Published '{object}' in {locale} with missing translations - see below.").format(
                        object=str(instance),
                        locale=translation.target_locale.get_display_name()
                    ))

                else:
                    messages.success(request, _("Published '{object}' in {locale}.").format(
                        object=str(instance),
                        locale=translation.target_locale.get_display_name()
                    ))

        return redirect(request.path)

    string_segments = translation.source.stringsegment_set.all().order_by('order')
    string_translations = string_segments.get_translations(translation.target_locale)

    overridable_segments = translation.source.overridablesegment_set.all().order_by('order')
    segment_overrides = overridable_segments.get_overrides(translation.target_locale)

    tab_helper = TabHelper(source_instance)

    breadcrumb = []
    if isinstance(instance, Page):
        # find the closest common ancestor of the pages that this user has direct explore permission
        # (i.e. add/edit/publish/lock) over; this will be the root of the breadcrumb
        cca = get_explorable_root_page(request.user)
        if cca:
            breadcrumb = [
                {
                    'id': page.id,
                    'isRoot': page.is_root(),
                    'title': page.title,
                    'exploreUrl': reverse('wagtailadmin_explore_root') if page.is_root() else reverse('wagtailadmin_explore', args=[page.id]),
                }
                for page in instance.get_ancestors(inclusive=False).descendant_of(cca, inclusive=True)
            ]

    machine_translator = None
    translator = get_machine_translator()
    if translator and translator.can_translate(translation.source.locale, translation.target_locale):
        machine_translator = {
            'name': translator.display_name,
            'url': reverse('wagtail_localize:machine_translate', args=[translation.id]),
        }

    string_segment_data = [
        {
            'type': 'string',
            'id': segment.id,
            'contentPath': segment.context.path,
            'source': segment.string.data,
            'location': get_segment_location_info(source_instance, tab_helper, segment.context.path),
            'editUrl': reverse('wagtail_localize:edit_string_translation', kwargs={'translation_id': translation.id, 'string_segment_id': segment.id}),
            'order': segment.order,
        }
        for segment in string_segments
    ]
    syncronised_value_segment_data = [
        {
            'type': 'synchronised_value',
            'id': segment.id,
            'contentPath': segment.context.path,
            'location': get_segment_location_info(source_instance, tab_helper, segment.context.path, widget=True),
            'value': segment.data,
            'editUrl': reverse('wagtail_localize:edit_override', kwargs={'translation_id': translation.id, 'overridable_segment_id': segment.id}),
            'order': segment.order,
        }
        for segment in overridable_segments
    ]

    segments = string_segment_data + syncronised_value_segment_data
    segments.sort(key=lambda segment: segment['order'])

    return render(request, 'wagtail_localize/admin/edit_translation.html', {
        # These props are passed directly to the TranslationEditor react component
        'props': json.dumps({
            'object': {
                'title': str(instance),
                'isLive': is_live,
                'isLocked': is_locked,
                'lastPublishedDate': last_published_at.strftime('%-d %B %Y') if last_published_at is not None else None,
                'lastPublishedBy': UserSerializer(last_published_by).data if last_published_by is not None else None,
                'liveUrl': live_url,
            },
            'breadcrumb': breadcrumb,
            'tabs': tab_helper.tabs_with_slugs,
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
                    'editUrl': reverse('wagtailadmin_pages:edit', args=[translated_instance.id]) if isinstance(translated_instance, Page) else reverse('wagtailsnippets:edit', args=[translated_instance._meta.app_label, translated_instance._meta.model_name, quote(translated_instance.id)]),
                }
                for translated_instance in instance.get_translations().select_related('locale')
            ],
            'perms': {
                'canPublish': can_publish,
                'canUnpublish': can_unpublish,
                'canLock': can_lock,
                'canUnlock': can_unlock,
                'canDelete': can_delete,
            },
            'links': {
                'downloadPofile': reverse('wagtail_localize:download_pofile', args=[translation.id]),
                'uploadPofile': reverse('wagtail_localize:upload_pofile', args=[translation.id]),
                'unpublishUrl': reverse('wagtailadmin_pages:unpublish', args=[instance.id]) if isinstance(instance, Page) else None,
                'lockUrl': reverse('wagtailadmin_pages:lock', args=[instance.id]) if isinstance(instance, Page) else None,
                'unlockUrl': reverse('wagtailadmin_pages:unlock', args=[instance.id]) if isinstance(instance, Page) else None,
                'deleteUrl': reverse('wagtailadmin_pages:delete', args=[instance.id]) if isinstance(instance, Page) else reverse('wagtailsnippets:delete', args=[instance._meta.app_label, instance._meta.model_name, quote(instance.pk)]),
                'stopTranslationUrl': reverse('wagtail_localize:stop_translation', args=[translation.id]),
            },
            'previewModes': [
                {
                    'mode': mode,
                    'label': label,
                    'url': reverse('wagtail_localize:preview_translation', args=[translation.id]) if mode == instance.default_preview_mode else reverse('wagtail_localize:preview_translation', args=[translation.id, mode]),
                }
                for mode, label in (instance.preview_modes if isinstance(instance, Page) else [])
            ],
            'machineTranslator': machine_translator,
            'segments': segments,

            # We serialize the translation data using Django REST Framework.
            # This gives us a consistent representation with the APIs so we
            # can dynamically update translations in the view.
            'initialStringTranslations': StringTranslationSerializer(string_translations, many=True, context={'translation_source': translation.source}).data,
            'initialOverrides': SegmentOverrideSerializer(segment_overrides, many=True, context={'translation_source': translation.source}).data,
        }, cls=DjangoJSONEncoder)
    })


def user_can_edit_instance(user, instance):
    if isinstance(instance, Page):
        # Page
        page_perms = instance.permissions_for_user(user)
        return page_perms.can_edit()

    else:
        # Snippet
        return user_can_edit_snippet_type(user, instance.__class__)


def preview_translation(request, translation_id, mode=None):
    translation = get_object_or_404(Translation, id=translation_id)

    instance = translation.get_target_instance()

    if not isinstance(instance, Page):
        raise Http404

    if not user_can_edit_instance(request.user, instance):
        raise PermissionDenied

    if mode is None:
        mode = instance.default_preview_mode

    if mode not in dict(instance.preview_modes):
        raise Http404

    translation = translation.source.get_ephemeral_translated_instance(translation.target_locale, fallback=True)

    return translation.make_preview_request(request, mode)


@require_POST
def stop_translation(request, translation_id):
    translation = get_object_or_404(Translation, id=translation_id)

    instance = translation.get_target_instance()
    if not user_can_edit_instance(request.user, instance):
        raise PermissionDenied

    translation.enabled = False
    translation.save(update_fields=['enabled'])

    next_url = get_valid_next_url_from_request(request)
    if not next_url:
        # Note: You should always provide a next URL when using this view!
        next_url = reverse('wagtailadmin_home')

    messages.success(
        request,
        _("Translation has been stopped.")
    )

    return redirect(next_url)


@require_POST
def restart_translation(request, translation, instance):
    # This view is hooked in using the before_edit_page hook so we don't need to check for edit permission
    translation.enabled = True
    translation.save(update_fields=['enabled'])

    messages.success(
        request,
        _("Translation has been restarted.")
    )

    if isinstance(instance, Page):
        return redirect('wagtailadmin_pages:edit', instance.id)
    else:
        return redirect('wagtailsnippets:edit', instance._meta.app_label, instance._meta.model_name, quote(instance.pk))


@api_view(['PUT', 'DELETE'])
def edit_string_translation(request, translation_id, string_segment_id):
    translation = get_object_or_404(Translation, id=translation_id)
    string_segment = get_object_or_404(StringSegment, id=string_segment_id)

    if string_segment.context.object_id != translation.source.object_id:
        raise Http404

    instance = translation.get_target_instance()
    if not user_can_edit_instance(request.user, instance):
        raise PermissionDenied

    if request.method == 'PUT':
        string_translation, created = StringTranslation.objects.update_or_create(
            translation_of_id=string_segment.string_id,
            locale_id=translation.target_locale_id,
            context_id=string_segment.context_id,
            defaults={
                'data': request.POST['value'],
                'translation_type': StringTranslation.TRANSLATION_TYPE_MANUAL,
                'tool_name': "",
                'last_translated_by': request.user,
                'has_error': False,
                'field_error': "",
            }
        )

        return Response(StringTranslationSerializer(string_translation, context={'translation_source': translation.source}).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    elif request.method == 'DELETE':
        string_translation = StringTranslation.objects.filter(
            translation_of_id=string_segment.string_id,
            locale_id=translation.target_locale_id,
            context_id=string_segment.context_id,
        ).first()

        if string_translation:
            string_translation.delete()

            return Response(StringTranslationSerializer(string_translation, context={'translation_source': translation.source}).data, status=status.HTTP_200_OK)

        else:
            # Note: this is still considered a success in the frontend
            return Response(status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT', 'DELETE'])
def edit_override(request, translation_id, overridable_segment_id):
    translation = get_object_or_404(Translation, id=translation_id)
    overridable_segment = get_object_or_404(OverridableSegment, id=overridable_segment_id)

    if overridable_segment.context.object_id != translation.source.object_id:
        raise Http404

    instance = translation.get_target_instance()
    if not user_can_edit_instance(request.user, instance):
        raise PermissionDenied

    if request.method == 'PUT':
        override, created = SegmentOverride.objects.update_or_create(
            locale_id=translation.target_locale_id,
            context_id=overridable_segment.context_id,
            defaults={
                'data_json': json.dumps(request.POST['value']),
                'last_translated_by': request.user,
            }
        )

        return Response(SegmentOverrideSerializer(override, context={'translation_source': translation.source}).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    elif request.method == 'DELETE':
        override = SegmentOverride.objects.filter(
            locale_id=translation.target_locale_id,
            context_id=overridable_segment.context_id,
        ).first()

        if override:
            override.delete()

            return Response(SegmentOverrideSerializer(override, context={'translation_source': translation.source}).data, status=status.HTTP_200_OK)

        else:
            # Note: this is still considered a success in the frontend
            return Response(status=status.HTTP_404_NOT_FOUND)


def download_pofile(request, translation_id):
    translation = get_object_or_404(Translation, id=translation_id)

    instance = translation.get_target_instance()
    if not user_can_edit_instance(request.user, instance):
        raise PermissionDenied

    response = HttpResponse(str(translation.export_po()), content_type="text/x-gettext-translation")
    response["Content-Disposition"] = (
        "attachment; filename=%s-%s.po" % (
            slugify(translation.source.object_repr),
            translation.target_locale.language_code,
        )
    )
    return response


@require_POST
def upload_pofile(request, translation_id):
    translation = get_object_or_404(Translation, id=translation_id)

    instance = translation.get_target_instance()
    if not user_can_edit_instance(request.user, instance):
        raise PermissionDenied

    do_import = True

    with tempfile.NamedTemporaryFile() as f:
        # Note: polib.pofile accepts either a filename or contents. We cannot pass the
        # contents directly into polib.pofile or users could upload a file containing
        # a filename and this will be read by polib!
        f.write(request.FILES["file"].read())
        f.flush()

        try:
            po = polib.pofile(f.name)

        except (OSError, UnicodeDecodeError):
            # Annoyingly, POLib uses OSError for parser exceptions...
            messages.error(
                request,
                _("Please upload a valid PO file.")
            )
            do_import = False

    if do_import:
        translation_id = po.metadata['X-WagtailLocalize-TranslationID']
        if translation_id != str(translation.uuid):
            messages.error(
                request,
                _("Cannot import PO file that was created for a different translation.")
            )
            do_import = False

    if do_import:
        translation.import_po(po, user=request.user, tool_name="PO File")

        messages.success(
            request,
            _("Successfully imported translations from PO File.")
        )

    # Work out where to redirect to
    next_url = get_valid_next_url_from_request(request)
    if not next_url:
        # Note: You should always provide a next URL when using this view!
        next_url = reverse('wagtailadmin_home')

    return redirect(next_url)


@require_POST
def machine_translate(request, translation_id):
    translation = get_object_or_404(Translation, id=translation_id)

    instance = translation.get_target_instance()
    if not user_can_edit_instance(request.user, instance):
        raise PermissionDenied

    translator = get_machine_translator()
    if translator is None:
        raise Http404

    if not translator.can_translate(translation.source.locale, translation.target_locale):
        raise Http404

    # Get segments
    segments = defaultdict(list)
    for string_segment in translation.source.stringsegment_set.all().select_related("context", "string"):
        segment = StringSegmentValue(
            string_segment.context.path, string_segment.string.as_value()
        ).with_order(string_segment.order)
        if string_segment.attrs:
            segment.attrs = json.loads(string_segment.attrs)

        # Don't translate if there already is a translation
        if StringTranslation.objects.filter(
            translation_of_id=string_segment.string_id,
            locale=translation.target_locale,
            context_id=string_segment.context_id,
        ).exists():
            continue

        segments[segment.string].append((string_segment.string_id, string_segment.context_id))

    if segments:
        translations = translator.translate(translation.source.locale, translation.target_locale, segments.keys())

        with transaction.atomic():
            for string, contexts in segments.items():
                for string_id, context_id in contexts:
                    StringTranslation.objects.get_or_create(
                        translation_of_id=string_id,
                        locale=translation.target_locale,
                        context_id=context_id,
                        defaults={
                            'data': translations[string].data,
                            'translation_type': StringTranslation.TRANSLATION_TYPE_MACHINE,
                            'tool_name': translator.display_name,
                            'last_translated_by': request.user,
                            'has_error': False,
                            'field_error': "",
                        }
                    )

        messages.success(
            request,
            _("Successfully translated with {}.").format(translator.display_name)
        )

    else:
        messages.warning(
            request,
            _("There isn't anything left to translate.")
        )

    # Work out where to redirect to
    next_url = get_valid_next_url_from_request(request)
    if not next_url:
        # Note: You should always provide a next URL when using this view!
        next_url = reverse('wagtailadmin_home')

    return redirect(next_url)

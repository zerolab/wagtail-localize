from urllib.parse import urlencode

from django.contrib.admin.utils import quote
from django.contrib.auth.models import Permission
from django.urls import reverse, path, include
from django.utils.translation import gettext as _
from django.templatetags.static import static
from django.urls import path, reverse
from django.utils.html import format_html_join
from django.utils.translation import ugettext_lazy as _
from django.views.i18n import JavaScriptCatalog

from wagtail.admin import widgets as wagtailadmin_widgets
from wagtail.admin.menu import MenuItem
from wagtail.core import hooks
from wagtail.core.models import Locale, TranslatableMixin
from wagtail.snippets.widgets import SnippetListingButton

from .models import Translation
from .views import submit_translations
from .views.api import ListTranslationsView
from .views.edit_translation import edit_translation, edit_string_translation
from .views.reports import translations_report


from wagtail.snippets.widgets import SnippetListingButton


@hooks.register("register_admin_urls")
def register_admin_urls():
    api_urls = [
        path('translations/', ListTranslationsView.as_view(), name='translations'),
    ]

    urls = [
        path('api/', include((api_urls, "api"), namespace="api")),
        path('jsi18n/', JavaScriptCatalog.as_view(packages=['wagtail_localize']), name='javascript_catalog'),
        path("submit/page/<int:page_id>/", submit_translations.SubmitPageTranslationView.as_view(), name="submit_page_translation"),
        path("submit/snippet/<slug:app_label>/<slug:model_name>/<str:pk>/", submit_translations.SubmitSnippetTranslationView.as_view(), name="submit_snippet_translation"),
        path("translate/<int:translation_id>/strings/<int:string_segment_id>/edit/", edit_string_translation, name="edit_string_translation"),
        path('reports/translations/', translations_report, name='translations_report'),
    ]

    return [
        path(
            "localize/",
            include(
                (urls, "wagtail_localize"),
                namespace="wagtail_localize",
            ),
        )
    ]


@hooks.register('register_permissions')
def register_submit_translation_permission():
    return Permission.objects.filter(content_type__app_label='wagtail_localize', codename='submit_translation')


@hooks.register("register_page_listing_more_buttons")
def page_listing_more_buttons(page, page_perms, is_parent=False, next_url=None):
    if page_perms.user.has_perm('wagtail_localize.submit_translation'):
        # If there's at least one locale that we haven't translated into yet, show "Translate this page" button
        has_locale_to_translate_to = Locale.objects.exclude(
            id__in=page.get_translations(inclusive=True).values_list('locale_id', flat=True)
        ).exists()

        if has_locale_to_translate_to:
            url = reverse("wagtail_localize:submit_page_translation", args=[page.id])
            if next_url is not None:
                url += '?' + urlencode({'next': next_url})

            yield wagtailadmin_widgets.Button(_("Translate this page"), url, priority=60)


@hooks.register('register_snippet_listing_buttons')
def register_snippet_listing_buttons(snippet, user, next_url=None):
    model = type(snippet)

    if issubclass(model, TranslatableMixin) and user.has_perm('wagtail_localize.submit_translation'):
        # If there's at least one locale that we haven't translated into yet, show "Translate" button
        has_locale_to_translate_to = Locale.objects.exclude(
            id__in=snippet.get_translations(inclusive=True).values_list('locale_id', flat=True)
        ).exists()

        if has_locale_to_translate_to:
            url = reverse('wagtail_localize:submit_snippet_translation', args=[model._meta.app_label, model._meta.model_name, quote(snippet.pk)])
            if next_url is not None:
                url += '?' + urlencode({'next': next_url})

            yield SnippetListingButton(
                _('Translate'),
                url,
                attrs={'aria-label': _("Translate '%(title)s'") % {'title': str(snippet)}},
                priority=100
            )


@hooks.register("before_edit_page")
def before_edit_page(request, page):
    # Overrides the edit page view if the page is the target of a translation
    try:
        translation = Translation.objects.get(source__object_id=page.translation_key, target_locale_id=page.locale_id, enabled=True)
        return edit_translation(request, translation, page)

    except Translation.DoesNotExist:
        pass


@hooks.register("before_edit_snippet")
def before_edit_snippet(request, instance):
    # Overrides the edit snippet view if the snippet is translatable and the target of a translation
    if isinstance(instance, TranslatableMixin):
        try:
            translation = Translation.objects.get(source__object_id=instance.translation_key, target_locale_id=instance.locale_id, enabled=True)
            return edit_translation(request, translation, instance)

        except Translation.DoesNotExist:
            pass


class TranslationsMenuItem(MenuItem):
    def is_shown(self, request):
        return True


@hooks.register("register_reports_menu_item")
def register_menu_item():
    return TranslationsMenuItem(
        _("Translations"),
        reverse("wagtail_localize:translations_report"),
        classnames="icon icon-site",
        order=500,
    )

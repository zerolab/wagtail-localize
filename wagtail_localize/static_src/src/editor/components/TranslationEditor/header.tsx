import React, { FunctionComponent } from 'react';
import gettext from 'gettext';

import Header, {
    HeaderLinkAction,
    HeaderMeta,
    HeaderMetaDropdown
} from '../../../common/components/Header';

import { EditorProps } from '.';
import { EditorState } from './reducer';

interface EditorHeaderProps extends EditorProps, EditorState {}

const EditorHeader: FunctionComponent<EditorHeaderProps> = ({
    object,
    sourceLocale,
    locale,
    translations,
    segments,
    stringTranslations
}) => {
    // Build actions
    let actions = [];
    if (object.liveUrl) {
        actions.push(
            <HeaderLinkAction
                key="live"
                label={gettext('Live')}
                href={object.liveUrl}
                classes={['button-nostroke button--live']}
                icon="link-external"
            />
        );
    }

    let status = '';
    if (object.isLive) {
        if (object.lastPublishedAt) {
            status = gettext('Published at ') + object.lastPublishedAt;
        } else {
            status = gettext('Published');
        }
    } else {
        status = gettext('Draft');
    }

    // Build meta
    let meta = [
        <HeaderMeta key="status" value={status} />,
        <HeaderMeta key="source-locale" value={sourceLocale.displayName} />
    ];

    let translationOptions = translations
        .filter(({ locale }) => locale.code != sourceLocale.code)
        .map(({ locale, editUrl }) => {
            return {
                label: locale.displayName,
                href: editUrl
            };
        });

    if (translationOptions.length > 0) {
        meta.push(
            <HeaderMetaDropdown
                key="target-locale"
                label={locale.displayName}
                icon="arrow-right"
                options={translationOptions}
            />
        );
    } else {
        meta.push(
            <HeaderMeta
                key="target-locale"
                icon="arrow-right"
                value={locale.displayName}
            />
        );
    }

    let totalSegments = segments.length;
    let translatedSegments = Array.from(stringTranslations.keys()).length;

    if (totalSegments == translatedSegments) {
        meta.push(<HeaderMeta key="progress" value={gettext('Up to date')} />);
    } else {
        // TODO: Make translatable
        meta.push(
            <HeaderMeta
                key="progress"
                value={`In progress (${translatedSegments}/${totalSegments} strings)`}
            />
        );
    }

    return (
        <Header
            title={object.title}
            actions={actions}
            meta={meta}
            merged={true}
            tabbed={true}
        />
    );
};

export default EditorHeader;

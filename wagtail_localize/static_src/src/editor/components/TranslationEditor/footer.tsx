import React, { FunctionComponent } from 'react';
import gettext from 'gettext';

import Icon from '../../../common/components/Icon';
import ActionMenu from '../../../common/components/ActionMenu';

import { EditorProps } from '.';

const EditorFooter: FunctionComponent<EditorProps> = ({ perms, locale }) => {
    let actions = [
        <a className="button action-secondary" href="/admin/pages/60/delete/">
            <Icon name="cross" />
            {gettext('Disable')}
        </a>
    ];

    if (perms.canDelete) {
        actions.push(
            <a
                className="button action-secondary"
                href="/admin/pages/60/delete/"
            >
                <Icon name="bin" />
                {gettext('Delete')}
            </a>
        );
    }

    // TODO unlock
    if (perms.canLock) {
        actions.push(
            <button
                className="button action-secondary"
                data-locking-action="/admin/pages/60/lock/"
                aria-label={gettext('Apply editor lock')}
            >
                <Icon name="lock" />
                {gettext('Lock')}
            </button>
        );
    }

    if (perms.canUnpublish) {
        actions.push(
            <a
                className="button action-secondary"
                href="/admin/pages/60/unpublish/"
            >
                <Icon name="download-alt" />
                {gettext('Unpublish')}
            </a>
        );
    }

    if (perms.canPublish) {
        actions.push(
            <button
                className="button button-longrunning "
                data-clicked-text={gettext('Publishing…')}
            >
                <Icon name="upload" className={'button-longrunning__icon'} />
                <Icon name="spinner" />
                <em>{gettext('Publish in ') + locale.displayName}</em>
            </button>
        );
    }

    // Make last action the default
    const defaultAction = actions.pop();

    return (
        <footer>
            <ActionMenu defaultAction={defaultAction} actions={actions} />
        </footer>
    );
};

export default EditorFooter;

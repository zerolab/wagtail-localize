import React, { FunctionComponent } from 'react';

//import Icon from '../../../common/components/Icon';

import {
    EditorProps,
    StringSegment,
    StringTranslation,
    StringTranslationAPI
} from '.';
import {
    EditorState,
    EditorAction,
    EDIT_STRING_TRANSLATION,
    TRANSLATION_SAVE_SERVER_ERROR,
    TRANSLATION_SAVED,
    TRANSLATION_DELETED
} from './reducer';

import gettext from 'gettext';

function saveTranslation(
    segment: StringSegment,
    value: string,
    csrfToken: string,
    dispatch: React.Dispatch<EditorAction>
) {
    dispatch({
        type: EDIT_STRING_TRANSLATION,
        segmentId: segment.id,
        value: value
    });
    if (value) {
        // Create/update the translation
        const formData = new FormData();
        formData.set('value', value);

        fetch(segment.editUrl, {
            credentials: 'same-origin',
            method: 'PUT',
            body: formData,
            headers: {
                'X-CSRFToken': csrfToken
            }
        })
            .then(response => {
                if (response.status == 200 || response.status == 201) {
                    return response.json();
                } else {
                    throw new Error('Unrecognised HTTP status returned');
                }
            })
            .then((translation: StringTranslationAPI) => {
                dispatch({
                    type: TRANSLATION_SAVED,
                    segmentId: segment.id,
                    translation
                });
            })
            .catch(() => {
                dispatch({
                    type: TRANSLATION_SAVE_SERVER_ERROR,
                    segmentId: segment.id
                });
            });
    } else {
        // Delete the translation
        fetch(segment.editUrl, {
            credentials: 'same-origin',
            method: 'DELETE',
            headers: {
                'X-CSRFToken': csrfToken
            }
        }).then(response => {
            if (response.status == 200) {
                dispatch({
                    type: TRANSLATION_DELETED,
                    segmentId: segment.id
                });
            } else {
                dispatch({
                    type: TRANSLATION_SAVE_SERVER_ERROR,
                    segmentId: segment.id
                });
            }
        });
    }
}

interface EditorSegmentProps {
    segment: StringSegment;
    translation: StringTranslation | null;
    dispatch: React.Dispatch<EditorAction>;
    csrfToken: string;
}

const EditorSegment: FunctionComponent<EditorSegmentProps> = ({
    segment,
    translation,
    dispatch,
    csrfToken
}) => {
    const [isEditing, setIsEditing] = React.useState(false);
    const [editingValue, setEditingValue] = React.useState(
        (translation && translation.value) || ''
    );

    if (isEditing) {
        const onChangeValue = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
            setEditingValue(e.target.value);
        };

        const onClickSave = () => {
            setIsEditing(false);
            saveTranslation(segment, editingValue, csrfToken, dispatch);
        };

        const onClickCancel = () => {
            setIsEditing(false);
        };

        return (
            <li className="segments__subfield">
                {segment.location.subField && (
                    <h4 className="segments__subfield-label">
                        {segment.location.subField}
                    </h4>
                )}
                <p className="segments__segment-source">{segment.source}</p>
                <textarea onChange={onChangeValue}>{editingValue}</textarea>
                <p className="segments__segment-help">
                    {segment.location.helpText}
                </p>
                <ul className="segments__segment-toolbar">
                    <li>
                        <button
                            className="segments__button segments__button--save"
                            onClick={onClickSave}
                        >
                            {gettext('Save')}
                        </button>
                    </li>
                    <li>
                        <button
                            className="segments__button segments__button--cancel"
                            onClick={onClickCancel}
                        >
                            {gettext('Cancel')}
                        </button>
                    </li>
                </ul>
            </li>
        );
    } else if (translation && translation.isSaving) {
        return (
            <li className="segments__subfield">
                {segment.location.subField && (
                    <h4 className="segments__subfield-label">
                        {segment.location.subField}
                    </h4>
                )}
                <p className="segments__segment-source">{segment.source}</p>
                <p className="segments__segment-value">
                    {translation && translation.value}
                </p>
                <ul className="segments__segment-toolbar">
                    <li>{gettext('Saving...')}</li>
                </ul>
            </li>
        );
    } else {
        const onClickEdit = () => {
            setIsEditing(true);
            setEditingValue((translation && translation.value) || '');
        };

        let toolbar = <></>;
        if (translation) {
            toolbar = (
                <>
                    <li>
                        {/* FIXME (<Icon name={translation.isErrored ? "warning" : "tick-inverse"} />*/}
                        {translation.comment}
                    </li>
                    <li>
                        <button
                            className="segments__button segments__button--edit"
                            onClick={onClickEdit}
                        >
                            {gettext('Edit')}
                        </button>
                    </li>
                </>
            );
        } else {
            toolbar = (
                <>
                    <li>
                        <button
                            className="segments__button segments__button--edit"
                            onClick={onClickEdit}
                        >
                            {gettext('Translate')}
                        </button>
                    </li>
                </>
            );
        }

        return (
            <li className="segments__subfield">
                {segment.location.subField && (
                    <h4 className="segments__subfield-label">
                        {segment.location.subField}
                    </h4>
                )}
                <p className="segments__segment-source">{segment.source}</p>
                <p className="segments__segment-value">
                    {translation && translation.value}
                </p>
                <ul className="segments__segment-toolbar">{toolbar}</ul>
            </li>
        );
    }
};

interface EditorSegmentListProps extends EditorProps, EditorState {
    dispatch: React.Dispatch<EditorAction>;
    csrfToken: string;
}

const EditorSegmentList: FunctionComponent<EditorSegmentListProps> = ({
    segments,
    stringTranslations,
    dispatch,
    csrfToken
}) => {
    // Group segments by field/block
    const segmentsByFieldBlock: Map<string, StringSegment[]> = new Map();
    segments.forEach(segment => {
        const field = segment.location.field;
        const blockId = segment.location.blockId || 'null';
        const key = `${field}/${blockId}`;
        if (!segmentsByFieldBlock.has(key)) {
            segmentsByFieldBlock.set(key, []);
        }
        segmentsByFieldBlock.get(key).push(segment);
    });

    const segmentRendered = Array.from(segmentsByFieldBlock.entries()).map(
        ([, segments]) => {
            // Render segments in field/block
            const segmentsRendered = segments.map(segment => {
                return (
                    <EditorSegment
                        key={segment.id}
                        segment={segment}
                        translation={stringTranslations.get(segment.id)}
                        dispatch={dispatch}
                        csrfToken={csrfToken}
                    />
                );
            });

            return (
                <li className="segments__field">
                    <h3 className="segments__field-label">{segments[0].location.field}</h3>
                    <div className="segments__field-content">
                        <ul>{segmentsRendered}</ul>
                    </div>
                </li>
            );
        }
    );

    return <ul className="segments">{segmentRendered}</ul>;
};

export default EditorSegmentList;

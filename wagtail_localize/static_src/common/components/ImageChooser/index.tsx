import React, { FunctionComponent } from 'react';
import gettext from 'gettext';

interface ImageAPI {
    id: number;
    title: string;
    thumbnail: {
        url: string;
        width: number;
        height: number;
    };
}

interface ImageChooserProps {
    imageId: number | null;
}

const ImageChooser: FunctionComponent<ImageChooserProps> = ({ imageId }) => {
    const [imageInfo, setImageInfo] = React.useState<ImageAPI | null>(null);

    React.useEffect(() => {
        setImageInfo(null);

        if (imageId) {
            fetch(`/admin/api/main/images/${imageId}/`)
                .then(response => response.json())
                .then(setImageInfo);
        }
    }, [imageId]);

    // Render
    let classNames = ['chooser', 'image-chooser'];
    let inner;
    if (imageId) {
        if (imageInfo) {
            inner = (
                <div className="chosen">
                    <div className="preview-image">
                        <img
                            alt={imageInfo.title}
                            className="show-transparency"
                            src={imageInfo.thumbnail.url}
                            title={imageInfo.title}
                            width={imageInfo.thumbnail.width}
                            height={imageInfo.thumbnail.height}
                        />
                    </div>

                    <ul className="actions" style={{ listStyleType: 'none' }}>
                        {/*<li><button type="button" className="button action-clear button-small button-secondary">{gettext('Clear choice')}</button></li>
                        <li><button type="button" className="button action-choose button-small button-secondary">{gettext('Change image')}</button></li>*/}
                        <li>
                            <a
                                href={`/admin/images/${imageInfo.id}/`}
                                className="edit-link button button-small button-secondary"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                {gettext('Edit this image')}
                            </a>
                        </li>
                    </ul>
                </div>
            );
        } else {
            inner = <p>{gettext('Fetching image information...')}</p>;
        }
    } else {
        classNames.push('blank');

        inner = (
            <div className="unchosen">
                <button
                    type="button"
                    className="button action-choose button-small button-secondary"
                >
                    {gettext('Choose an image')}
                </button>
            </div>
        );
    }

    return <div className={classNames.join(' ')}>{inner}</div>;
};

export default ImageChooser;

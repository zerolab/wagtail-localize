import React from 'react';
import ReactDOM from 'react-dom';
import Frame, { FrameContextConsumer } from 'react-frame-component'
import { StyleSheetManager } from 'styled-components'

import TranslationEditor from './components/TranslationEditor';

document.addEventListener('DOMContentLoaded', () => {
    const element = document.querySelector('.js-translation-editor');

    if (element instanceof HTMLElement && element.dataset.props) {
        const csrfTokenElement = element.querySelector(
            '[name="csrfmiddlewaretoken"]'
        );

        if (csrfTokenElement instanceof HTMLInputElement) {
            const csrfToken = csrfTokenElement.value;

            ReactDOM.render(
                <Frame
                    style={{
                        display: 'block',
                        overflow: 'scroll',
                        border: 0,
                        width: '100%',
                        height: '100%',
                        position: 'absolute',
                        top: 0,
                        left: 0,
                    }}
                >
                    <FrameContextConsumer>
                        {(frameContext) => {
                            // Add a <base target="_parent"> tag to tell the browser to open all links in the parent window
                            const baseTag = frameContext.document.createElement('base');
                            baseTag.target = '_parent';
                            frameContext.document.head.appendChild(baseTag);

                            return (
                                <StyleSheetManager target={frameContext.document.head}>
                                    <TranslationEditor
                                    csrfToken={csrfToken}
                                        {...JSON.parse(element.dataset.props||'')}
                                    />
                                </StyleSheetManager>
                            );
                        }}
                    </FrameContextConsumer>
                </Frame>
                ,
                element
            );
        } else {
            console.error(
                "Not starting translation editor because I couldn't find the CSRF token element!"
            );
        }
    }
});
